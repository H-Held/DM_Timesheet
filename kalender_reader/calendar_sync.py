"""
calendar_sync.py
────────────────
Syncs "Zeitnachweis" (timesheet) PDFs into Google Calendar.

Two entry points, both called from main.py:

  sync_zeitnachweis(pdf_source, month, year, with_reminders, calendar=None)
      → syncs a single PDF: adds / updates / removes the events for that month
        so the calendar always matches the PDF exactly.

  full_sync(download_dir)
      → scans ALL saved Zeitnachweis PDFs on disk and syncs every one of them,
        authenticating with Google only once. Reads and writes are batched
        across months (see _FULL_SYNC_CHUNK_SIZE) instead of one HTTP round
        trip per month, let alone per event.

What this module puts on the calendar
─────────────────────────────────────
* Work shifts  → one timed event per worked day, titled "DM".
                 Colour depends on the shift's end time:
                   end time already passed  → graphite (grey)
                   end time still in future → grape    (violet)
* Vacation     → one all-day event per *block* of vacation days, titled
                 "Urlaub", coloured dark green, with the description
                 "eingetragener Urlaub" and a single reminder the day before.
                 Consecutive vacation days (weekends in between included) are
                 merged into a single multi-day event instead of one per day.

Every event this tool creates is tagged with a private marker
(``extendedProperties.private[MANAGED_KEY]``) so we can reliably find our own
events again later — and never touch the user's other calendar entries.
Events created before that marker existed were all titled "DM", so those are
still recognised by their title as a fallback.

Logging note: an unchanged day/vacation block is logged at DEBUG, not INFO —
on a full re-sync spanning many months, most days are unchanged, so keeping
that outcome off the INFO level is intentional and keeps INFO focused on
actual creates/updates/deletes/failures. Do not "fix" this back to INFO.
"""

import csv
import os
import logging
from collections import namedtuple
from datetime import datetime, timedelta, date

import app_paths
from google_calendar import GoogleCalendar, COLORS
from zeitnachweis_parser import (
    parse_zeitnachweis_pdf,
    month_year_from_filename,
    KIND_WORK,
    KIND_VACATION,
)

logger = logging.getLogger(__name__)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Event appearance ─────────────────────────────────────────────────────────
COLOR_PAST = "graphite"     # grey       — work shift whose end time has passed
COLOR_FUTURE = "grape"      # violet     — work shift that has not ended yet
COLOR_VACATION = "green"    # dark green — approved leave ("Urlaub")

WORK_TITLE = "DM"                          # title of every work-shift event
VACATION_TITLE = "Urlaub"                  # title of every vacation event
VACATION_DESCRIPTION = "eingetragener Urlaub"

# ── Managed-event marker ─────────────────────────────────────────────────────
# Stored under extendedProperties.private on every event we create, so we can
# recognise our own events without clobbering anything the user made.
MANAGED_KEY = "dmTimesheet"
MANAGED_VALUE = "managed"
MANAGED_PROPERTIES = {"private": {MANAGED_KEY: MANAGED_VALUE}}

# A queued batch write (create/update/delete) plus the info needed to log and
# count it once the batch comes back — see _apply_batch_results().
_Action = namedtuple("_Action", "stat_key message")


# ─────────────────────────────────────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_calendar() -> GoogleCalendar:
    """
    Create a GoogleCalendar client.

    Credentials and the saved token live next to this file when running from
    source, or next to the executable when running as a packaged .exe.
    """
    return GoogleCalendar(
        credentials_path=app_paths.resolve("credentials.json", SCRIPT_DIR),
        token_path=app_paths.resolve("token.pickle", SCRIPT_DIR),
    )


def _is_managed_event(event: dict) -> bool:
    """True if this event was created by this tool (marker or legacy title)."""
    private = event.get("extendedProperties", {}).get("private", {})
    if private.get(MANAGED_KEY) == MANAGED_VALUE:
        return True
    # Legacy events (created before the marker existed) were all titled "DM".
    return event.get("summary", "").upper().startswith("DM")


def _is_all_day(event: dict) -> bool:
    """True for an all-day event (it has a 'date' rather than a 'dateTime')."""
    return "date" in event.get("start", {})


def _event_date_key(event: dict) -> str:
    """Return the event's start date as 'YYYY-MM-DD'."""
    start = event.get("start", {})
    return start.get("dateTime", start.get("date", ""))[:10]


def _format_datetime(day: datetime, time_str: str) -> str:
    """Combine a date and a 'HH:MM' string into '2026-04-28T08:00:00'."""
    return f"{day.strftime('%Y-%m-%d')}T{time_str}:00"


def _color_for_shift(end_iso: str) -> str:
    """Return graphite if the shift end is in the past, grape otherwise."""
    end_dt = datetime.fromisoformat(end_iso)
    if end_dt.tzinfo is not None:  # compare against a naive 'now'
        end_dt = end_dt.replace(tzinfo=None)
    return COLOR_PAST if end_dt < datetime.now() else COLOR_FUTURE


def _reminders_for_shift(start_iso: str) -> list[dict]:
    """
    Build four popup reminders for a work shift:
      - the day before at 17:00
      - 60 minutes before the start
      - 30 minutes before the start
      - 15 minutes before the start
    """
    start_dt = datetime.fromisoformat(start_iso)
    day_before_17 = start_dt.replace(hour=17, minute=0, second=0) - timedelta(days=1)
    minutes_until_start = max(int((start_dt - day_before_17).total_seconds() / 60), 1)
    return [
        {"method": "popup", "minutes": minutes_until_start},
        {"method": "popup", "minutes": 60},
        {"method": "popup", "minutes": 30},
        {"method": "popup", "minutes": 15},
    ]


def _vacation_reminder() -> list[dict]:
    """
    One popup the day before the vacation starts, at 17:00.

    For an all-day event the minutes count back from midnight of the first day,
    so 17:00 the previous day = 7 hours = 420 minutes.
    """
    return [{"method": "popup", "minutes": 420}]


# ─────────────────────────────────────────────────────────────────────────────
# Core sync — one PDF
# ─────────────────────────────────────────────────────────────────────────────

def sync_zeitnachweis(
    pdf_source,
    month: int,
    year: int,
    with_reminders: bool = False,
    calendar: GoogleCalendar | None = None,
) -> dict:
    """
    Sync one Zeitnachweis PDF with Google Calendar.

    Args:
        pdf_source:     File path (str) or raw PDF bytes.
        month:          Month of the timesheet (1-12).
        year:           Year of the timesheet, e.g. 2026.
        with_reminders: If True, add the day-before + 60/30/15-minute popups
                        to work shifts (vacation always gets its one reminder).
        calendar:       An existing GoogleCalendar client to reuse. If None, a
                        new one is created (and authenticated) for this call.

    Returns:
        dict with the keys: added, removed, updated, skipped.
    """
    cal = calendar or _build_calendar()
    stats = {"added": 0, "removed": 0, "updated": 0, "skipped": 0}

    # 1. Parse the PDF into the worked days and the vacation days we want.
    rows = parse_zeitnachweis_pdf(pdf_source, month, year)
    work_rows, vacation_dates = _split_rows(rows)

    # 2. Load the events this tool already put on the calendar for this month.
    start_dt, end_dt = _month_window(year, month)
    existing = [
        e for e in cal.get_events_in_range(start_dt, end_dt, max_results=200)
        if _is_managed_event(e)
    ]
    timed_events = [e for e in existing if not _is_all_day(e)]
    allday_events = [e for e in existing if _is_all_day(e)]

    logger.info(
        "[sync] %02d/%d — PDF: %d work, %d vacation days | "
        "Calendar: %d timed, %d all-day",
        month, year, len(work_rows), len(vacation_dates),
        len(timed_events), len(allday_events),
    )

    # 3. Reconcile work shifts and vacation blocks independently, queuing all
    #    writes into one batch instead of firing an HTTP request per event.
    batch = cal.new_batch()
    actions: list[_Action] = []
    _sync_work_events(batch, actions, work_rows, timed_events, stats, with_reminders)
    _sync_vacation_events(batch, actions, vacation_dates, allday_events, stats)

    # 4. Send every queued create/update/delete in a single round trip.
    results = batch.execute()
    _apply_batch_results(actions, results, stats)

    logger.info(
        "[sync] done: +%d -%d ~%d =%d",
        stats["added"], stats["removed"], stats["updated"], stats["skipped"],
    )
    return stats


def _split_rows(rows: list[dict]) -> tuple[dict, list[date]]:
    """Split parsed PDF rows into work_rows (keyed by 'YYYY-MM-DD') and sorted vacation dates."""
    work_rows = {
        row["date"].strftime("%Y-%m-%d"): row
        for row in rows if row["kind"] == KIND_WORK
    }
    vacation_dates = sorted(
        row["date"].date() for row in rows if row["kind"] == KIND_VACATION
    )
    return work_rows, vacation_dates


def _month_window(year: int, month: int) -> tuple[datetime, datetime]:
    """The [start, end) datetime window covering one calendar month."""
    start_dt = datetime(year, month, 1)
    end_dt = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    return start_dt, end_dt


def _apply_batch_results(actions: list[_Action], results: list, stats: dict) -> None:
    """Log and count each queued write once the batch response comes back."""
    for action, result in zip(actions, results):
        if result.ok:
            logger.info(action.message)
            stats[action.stat_key] += 1
        else:
            logger.error("%s — FAILED: %s", action.message, result.error, exc_info=result.error)


# ─────────────────────────────────────────────────────────────────────────────
# Work shifts (timed events)
# ─────────────────────────────────────────────────────────────────────────────

def _sync_work_events(batch, actions, work_rows, timed_events, stats, with_reminders) -> None:
    """Queue whatever it takes to make the timed 'DM' events match the worked days in the PDF."""
    # Group existing timed events by date. A day should hold exactly one, but
    # earlier bugs (or manual edits) may have left several — we handle that.
    by_date: dict[str, list[dict]] = {}
    for event in timed_events:
        by_date.setdefault(_event_date_key(event), []).append(event)

    # Create / update the shift for every worked day in the PDF.
    for date_key, row in work_rows.items():
        events_today = by_date.pop(date_key, [])
        _sync_one_work_day(batch, actions, stats, date_key, row, events_today, with_reminders)

    # Whatever is left sits on a day the PDF no longer lists as work (it became
    # a vacation day, a free day, or was removed) → delete it.
    for leftover in by_date.values():
        for event in leftover:
            batch.delete_event(event["id"])
            actions.append(_Action("removed", f"[sync] - {_event_date_key(event)} (stale work event)"))


def _sync_one_work_day(batch, actions, stats, date_key, row, events_today, with_reminders) -> None:
    """Queue the create/update for the single shift event of one worked day (or skip if unchanged)."""
    start_iso = _format_datetime(row["date"], row["start_time"])
    end_iso = _format_datetime(row["date"], row["end_time"])
    color = _color_for_shift(end_iso)
    reminders = _reminders_for_shift(start_iso) if with_reminders else None
    # The PDF's "Kommentar" column (e.g. a branch code like "D3AD") — shown
    # as the event's description so it's visible in Google Calendar too.
    comment = row.get("comment")
    description = f"Kommentar: {comment}" if comment else ""

    # Nothing on this day yet → create the event.
    if not events_today:
        batch.create_event(
            title=WORK_TITLE, start=start_iso, end=end_iso,
            color=color, reminders=reminders, description=description,
            extended_properties=MANAGED_PROPERTIES,
        )
        actions.append(_Action(
            "added",
            f"[sync] + {date_key} {row['start_time']}-{row['end_time']} ({color})"
            + (f" [{comment}]" if comment else ""),
        ))
        return

    # Keep exactly one event for the day; delete any duplicates.
    event = events_today[0]
    for duplicate in events_today[1:]:
        batch.delete_event(duplicate["id"])
        actions.append(_Action("removed", f"[sync] - {date_key} (duplicate work event)"))

    if _work_event_matches(date_key, event, start_iso, end_iso, color, with_reminders, description):
        logger.debug("[sync] = %s (unchanged)", date_key)
        stats["skipped"] += 1
    else:
        batch.update_event(
            event_id=event["id"], title=WORK_TITLE, start=start_iso, end=end_iso,
            color=color, reminders=reminders, description=description,
            extended_properties=MANAGED_PROPERTIES,
        )
        actions.append(_Action(
            "updated",
            f"[sync] ~ {date_key} {row['start_time']}-{row['end_time']} ({color})"
            + (f" [{comment}]" if comment else ""),
        ))


def _work_event_matches(date_key, event, start_iso, end_iso, color, with_reminders, description) -> bool:
    """True if the existing event already has the desired times, colour, description, etc."""
    existing_start = event.get("start", {}).get("dateTime", "")[:16]
    existing_end = event.get("end", {}).get("dateTime", "")[:16]
    if existing_start != start_iso[:16] or existing_end != end_iso[:16]:
        logger.debug(
            "[sync] %s changed: time mismatch (%s-%s vs %s-%s)",
            date_key, existing_start, existing_end, start_iso[:16], end_iso[:16],
        )
        return False
    if event.get("colorId", "") != COLORS.get(color, ""):
        logger.debug(
            "[sync] %s changed: color mismatch (%s vs %s)",
            date_key, event.get("colorId", ""), COLORS.get(color, ""),
        )
        return False
    if event.get("summary", "") != WORK_TITLE:
        logger.debug(
            "[sync] %s changed: title mismatch (%r vs %r)",
            date_key, event.get("summary", ""), WORK_TITLE,
        )
        return False
    if event.get("description", "") != description:
        logger.debug(
            "[sync] %s changed: description mismatch (%r vs %r)",
            date_key, event.get("description", ""), description,
        )
        return False
    if with_reminders:
        reminders = event.get("reminders", {})
        if reminders.get("useDefault", True) or not reminders.get("overrides"):
            logger.debug("[sync] %s changed: reminders missing/default", date_key)
            return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Vacation (all-day events)
# ─────────────────────────────────────────────────────────────────────────────

def _sync_vacation_events(batch, actions, vacation_dates, allday_events, stats) -> None:
    """Queue whatever it takes to make the all-day 'Urlaub' events match the vacation days in the PDF."""
    desired_ranges = _merge_vacation_ranges(vacation_dates)

    remaining = list(allday_events)
    for start_date, last_date in desired_ranges:
        match = _find_matching_vacation(remaining, start_date, last_date)
        if match is not None:
            remaining.remove(match)
            logger.debug("[sync] = vacation %s–%s (unchanged)", start_date, last_date)
            stats["skipped"] += 1
        else:
            batch.create_all_day_event(
                title=VACATION_TITLE, day=start_date, end_day=last_date,
                description=VACATION_DESCRIPTION, color=COLOR_VACATION,
                reminders=_vacation_reminder(),
                extended_properties=MANAGED_PROPERTIES,
            )
            actions.append(_Action("added", f"[sync] + vacation {start_date}–{last_date}"))

    # Any all-day event that no longer matches a vacation block (e.g. the old
    # one-event-per-day or yellow events) → delete it.
    for event in remaining:
        batch.delete_event(event["id"])
        actions.append(_Action("removed", f"[sync] - {_event_date_key(event)} (stale vacation event)"))


def _find_matching_vacation(events: list[dict], start_date: date, last_date: date):
    """Return an existing all-day event that already covers exactly this block."""
    want_start = start_date.strftime("%Y-%m-%d")
    want_end = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")  # Google end is exclusive
    for event in events:
        if (
            event.get("start", {}).get("date") == want_start
            and event.get("end", {}).get("date") == want_end
            and event.get("summary", "") == VACATION_TITLE
            and event.get("colorId", "") == COLORS.get(COLOR_VACATION, "")
        ):
            return event
    return None


def _merge_vacation_ranges(dates: list[date]) -> list[tuple[date, date]]:
    """
    Merge sorted vacation dates into inclusive (start, last) ranges.

    A gap between two vacation days is bridged when every day in between is a
    weekend (Sat/Sun), so a two-week vacation becomes a single event instead of
    one event per work-week.
    """
    if not dates:
        return []

    ordered = sorted(set(dates))
    ranges: list[tuple[date, date]] = []
    start = prev = ordered[0]
    for current in ordered[1:]:
        if _only_weekend_between(prev, current):
            prev = current  # still part of the same block
        else:
            ranges.append((start, prev))
            start = prev = current
    ranges.append((start, prev))
    return ranges


def _only_weekend_between(earlier: date, later: date) -> bool:
    """True if every day strictly between the two dates is a Saturday/Sunday."""
    day = earlier + timedelta(days=1)
    while day < later:
        if day.weekday() < 5:  # 0-4 == Monday-Friday
            return False
        day += timedelta(days=1)
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Full sync — every saved PDF on disk
# ─────────────────────────────────────────────────────────────────────────────

# Google's batch endpoint accepts up to 1000 calls per HTTP request.
# Writes per month vary a lot (0 on a re-run where nothing changed, ~30-40
# on a freshly imported, fully-booked month) — so instead of guessing a
# fixed number of months per round trip, the write batch below is flushed
# dynamically, right before it would cross this margin. That packs every
# request as full as the actual data allows, rather than leaving room on
# the table with a conservative fixed guess.
_BATCH_CALL_LIMIT = 1000
_BATCH_FLUSH_AT = 950  # safety margin below the hard limit


def full_sync(download_dir: str) -> None:
    """
    Scan every saved Zeitnachweis PDF under
    ``download_dir/DM/{year}/Zeitnachweis/`` and sync them all to Google
    Calendar. Authentication happens once. Every month's calendar read is
    batched into a single request (one list() call per month practically
    never crosses Google's 1000-calls-per-batch limit), and every change is
    batched too, flushed dynamically as it fills up — see _BATCH_FLUSH_AT.
    No email operations are performed.
    """
    dm_root = os.path.join(download_dir, "DM")
    if not os.path.isdir(dm_root):
        logger.error("[full_sync] DM folder not found: %s", dm_root)
        return

    pdfs = _collect_zeitnachweis_pdfs(dm_root)
    logger.info("[full_sync] Found %d Zeitnachweis PDFs", len(pdfs))
    if not pdfs:
        return

    # Authenticate once and reuse the same client for every PDF.
    calendar = _build_calendar()
    total = {"added": 0, "removed": 0, "updated": 0, "skipped": 0}

    # Phase 1 — read every month's existing calendar state. One list() call
    # per month, so this only needs more than one batch in the (essentially
    # theoretical) case of an archive spanning more than 1000 months.
    read_results: list = []
    for i in range(0, len(pdfs), _BATCH_CALL_LIMIT):
        read_batch = calendar.new_batch()
        for year, month, _path in pdfs[i : i + _BATCH_CALL_LIMIT]:
            start_dt, end_dt = _month_window(year, month)
            read_batch.list_events_in_range(start_dt, end_dt, max_results=200)
        read_results.extend(read_batch.execute())

    # Phase 2 — parse every PDF and plan every month's writes into a shared
    # batch, flushing it just before it would cross the limit.
    write_batch = calendar.new_batch()
    actions: list[_Action] = []

    for (year, month, path), read_result in zip(pdfs, read_results):
        logger.info("[full_sync] Processing %s", os.path.basename(path))
        try:
            if not read_result.ok:
                raise read_result.error or RuntimeError("batch read failed")

            existing = [e for e in read_result.event.get("items", []) if _is_managed_event(e)]
            timed_events = [e for e in existing if not _is_all_day(e)]
            allday_events = [e for e in existing if _is_all_day(e)]

            rows = parse_zeitnachweis_pdf(path, month, year)
            work_rows, vacation_dates = _split_rows(rows)

            logger.info(
                "[sync] %02d/%d — PDF: %d work, %d vacation days | "
                "Calendar: %d timed, %d all-day",
                month, year, len(work_rows), len(vacation_dates),
                len(timed_events), len(allday_events),
            )

            _sync_work_events(write_batch, actions, work_rows, timed_events, total, with_reminders=False)
            _sync_vacation_events(write_batch, actions, vacation_dates, allday_events, total)
        except Exception:
            logger.exception("[full_sync] Failed %s", os.path.basename(path))

        if len(actions) >= _BATCH_FLUSH_AT:
            write_results = write_batch.execute()
            _apply_batch_results(actions, write_results, total)
            write_batch = calendar.new_batch()
            actions = []

    # Final partial batch (almost always the only one in practice).
    write_results = write_batch.execute()
    _apply_batch_results(actions, write_results, total)

    if total["added"] or total["removed"] or total["updated"]:
        logger.info(
            "[full_sync] Complete: +%d added  -%d removed  ~%d updated  =%d unchanged",
            total["added"], total["removed"], total["updated"], total["skipped"],
        )
    else:
        logger.info(
            "[full_sync] Complete: no changes — everything already up to date (%d unchanged).",
            total["skipped"],
        )


def _collect_zeitnachweis_pdfs(dm_root: str) -> list[tuple[int, int, str]]:
    """Return (year, month, path) for every Zeitnachweis PDF found under dm_root."""
    pdfs: list[tuple[int, int, str]] = []
    for year_dir in sorted(os.listdir(dm_root)):
        zt_dir = os.path.join(dm_root, year_dir, "Zeitnachweis")
        if not os.path.isdir(zt_dir):
            continue
        for filename in sorted(os.listdir(zt_dir)):
            if not filename.lower().endswith(".pdf"):
                continue
            month_year = month_year_from_filename(filename)
            if month_year:
                month, year = month_year
                pdfs.append((year, month, os.path.join(zt_dir, filename)))
    return pdfs


# ─────────────────────────────────────────────────────────────────────────────
# Local CSV export — a plain-text mirror of everything that goes to Calendar
# ─────────────────────────────────────────────────────────────────────────────

CSV_FILENAME = "Kalender_Uebersicht.csv"
CSV_FIELDS = ["Datum", "Wochentag", "Typ", "Von", "Bis", "Stunden", "Kommentar", "Status"]


def export_csv(download_dir: str) -> str | None:
    """
    Write every worked day and vacation block from every saved Zeitnachweis
    PDF into one local CSV file (``DM/Kalender_Uebersicht.csv``) — the same
    data that gets synced to Google Calendar, as a plain-text file you can
    open in Excel without needing calendar access.

    Always fully rebuilt from the PDFs on disk (no Google Calendar calls
    involved), so it can't drift: re-running this always reflects exactly
    what's currently on disk, the same way the calendar sync does.

    Returns the CSV path, or None if there was nothing to export.
    """
    dm_root = os.path.join(download_dir, "DM")
    pdfs = _collect_zeitnachweis_pdfs(dm_root) if os.path.isdir(dm_root) else []
    if not pdfs:
        logger.info("[export_csv] No Zeitnachweis PDFs found — nothing to export.")
        return None

    csv_rows: list[dict] = []
    for year, month, path in pdfs:
        try:
            rows = parse_zeitnachweis_pdf(path, month, year)
        except Exception:
            logger.exception("[export_csv] Failed to parse %s", os.path.basename(path))
            continue

        work_rows, vacation_dates = _split_rows(rows)

        for date_key, row in work_rows.items():
            end_iso = _format_datetime(row["date"], row["end_time"])
            status = "vergangen" if _color_for_shift(end_iso) == COLOR_PAST else "geplant"
            csv_rows.append({
                "Datum":     date_key,
                "Wochentag": row["weekday"],
                "Typ":       "Arbeit",
                "Von":       row["start_time"],
                "Bis":       row["end_time"],
                "Stunden":   row["hours"],
                "Kommentar": row.get("comment") or "",
                "Status":    status,
            })

        for start_date, last_date in _merge_vacation_ranges(vacation_dates):
            csv_rows.append({
                "Datum":     start_date.strftime("%Y-%m-%d"),
                "Wochentag": "",
                "Typ":       "Urlaub",
                "Von":       "",
                "Bis":       last_date.strftime("%Y-%m-%d"),
                "Stunden":   "",
                "Kommentar": VACATION_DESCRIPTION,
                "Status":    "",
            })

    csv_rows.sort(key=lambda r: r["Datum"])

    csv_path = os.path.join(dm_root, CSV_FILENAME)
    # utf-8-sig + ';' delimiter: German Excel expects a semicolon separator
    # (comma is the decimal separator, and "Stunden" values look like "2,00")
    # and the BOM so umlauts render correctly on double-click.
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, delimiter=";")
        writer.writeheader()
        writer.writerows(csv_rows)

    logger.info("[export_csv] Wrote %d rows to %s", len(csv_rows), csv_path)
    return csv_path
    return pdfs
