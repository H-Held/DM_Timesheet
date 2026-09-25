"""
zeitnachweis_parser.py
──────────────────────
Parses a "Zeitnachweis" (German monthly timesheet) PDF into structured rows.

The PDF text itself is German, so the regular expressions below intentionally
match German words ("Urlaub" = vacation) and the month map uses German month
names — that is the format the employer delivers. Everything the rest of the
program works with afterwards is plain English (see the row schema below).
"""

import io
import re
import logging
from datetime import datetime

import pdfplumber

logger = logging.getLogger(__name__)

# German month name → month number. The employer names every file in German
# (e.g. "Zeitnachweis_04_April_2026.pdf"), so this map is the single source of
# truth for turning those names into numbers across the whole project.
GERMAN_MONTHS: dict[str, int] = {
    "januar": 1, "februar": 2, "maerz": 3, "märz": 3, "april": 4,
    "mai": 5, "juni": 6, "juli": 7, "august": 8, "september": 9,
    "oktober": 10, "november": 11, "dezember": 12,
}

# Row "kind" values used throughout the project (English, stable identifiers).
KIND_WORK = "work"          # a worked shift with start/end times
KIND_VACATION = "vacation"  # an approved day of leave ("Urlaub")
KIND_OFF = "off"            # a free day with no entry

# ── Line patterns found inside the PDF ───────────────────────────────────────
# Matches: "05 Di  Tagschicht (final) 08:00 16:30 7,5 7,5 7,5 D3AD"
# The trailing "rest" group holds every column after the hours — Pause /
# Istzt / SpätZ / MAZ / Gesamt / Na-So-Ft are all further [\d,]+ numbers,
# and whatever text is left over (if any) is the "Kommentar" column, e.g. a
# branch code like "D3AD" the employer sometimes prints there.
_RE_SHIFT = re.compile(
    r"^(\d{2})\s+(\w{2})\s+\S.*?\((\w+)\)\s+(\d{2}:\d{2})\s+(\d{2}:\d{2})\s+([\d,]+)(?P<rest>.*)$"
)
# Matches: "12 Fr  Urlaub  8,0"
_RE_VACATION = re.compile(r"^(\d{2})\s+(\w{2})\s+Urlaub\s+([\d,]+)")
# Matches: "01 Mo" — free day, no entry
_RE_FREE = re.compile(r"^(\d{2})\s+(\w{2})\s*$")

_RE_NUMERIC_TOKEN = re.compile(r"^[\d,]+$")


def _extract_comment(rest: str) -> str | None:
    """
    Whatever text is left in a shift line's trailing "Kommentar" column, once
    every other numeric column (Pause/Istzt/SpätZ/MAZ/Gesamt/Na-So-Ft) is
    filtered out. Returns None if the column was empty.
    """
    tokens = [t for t in rest.split() if not _RE_NUMERIC_TOKEN.match(t)]
    return " ".join(tokens) if tokens else None

# Matches a Zeitnachweis filename: "Zeitnachweis_04_April_2026.pdf"
_RE_FILENAME = re.compile(r"_(\d{2})_(\w+)_(\d{4})")


def month_year_from_filename(filename: str) -> tuple[int, int] | None:
    """
    Extract (month, year) from a filename such as 'Zeitnachweis_04_April_2026.pdf'.

    Returns None if the name does not contain a recognizable German month.
    """
    match = _RE_FILENAME.search(filename)
    if not match:
        return None
    month = GERMAN_MONTHS.get(match.group(2).lower())
    if not month:
        return None
    return month, int(match.group(3))


def _open_pdf(source):
    """Open a PDF from a file path (str) or raw bytes."""
    if isinstance(source, (bytes, bytearray)):
        return pdfplumber.open(io.BytesIO(source))
    return pdfplumber.open(source)


def parse_zeitnachweis_pdf(source, month: int, year: int) -> list[dict]:
    """
    Parse a Zeitnachweis PDF and return every listed day as a list of dicts.

    Args:
        source: File path (str) or raw PDF bytes.
        month:  Calendar month of the Zeitnachweis (1-12).
        year:   Calendar year of the Zeitnachweis.

    Each returned dict has:
        date        datetime  — date of the day
        day         int       — day of month
        weekday     str       — e.g. "Mo", "Di"
        status      str|None  — "final", "Plan", or None
        start_time  str|None  — start time "08:00"
        end_time    str|None  — end time   "16:30"
        hours       str|None  — hours "7,5"
        comment     str|None  — the PDF's "Kommentar" column, e.g. a branch
                                 code like "D3AD" (work days only, else None)
        kind        str       — KIND_WORK, KIND_VACATION, or KIND_OFF
    """
    with _open_pdf(source) as pdf:
        text = pdf.pages[0].extract_text() or ""

    rows: list[dict] = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()

        match = _RE_SHIFT.match(line)
        if match:
            day = int(match.group(1))
            rows.append({
                "date":       datetime(year, month, day),
                "day":        day,
                "weekday":    match.group(2),
                "status":     match.group(3),
                "start_time": match.group(4),
                "end_time":   match.group(5),
                "hours":      match.group(6),
                "comment":    _extract_comment(match.group("rest")),
                "kind":       KIND_WORK,
            })
            continue

        match = _RE_VACATION.match(line)
        if match:
            day = int(match.group(1))
            rows.append({
                "date":       datetime(year, month, day),
                "day":        day,
                "weekday":    match.group(2),
                "status":     "final",
                "start_time": None,
                "end_time":   None,
                "hours":      match.group(3),
                "comment":    None,
                "kind":       KIND_VACATION,
            })
            continue

        match = _RE_FREE.match(line)
        if match:
            day = int(match.group(1))
            rows.append({
                "date":       datetime(year, month, day),
                "day":        day,
                "weekday":    match.group(2),
                "status":     None,
                "start_time": None,
                "end_time":   None,
                "hours":      None,
                "comment":    None,
                "kind":       KIND_OFF,
            })

    logger.debug(
        "[parser] %02d/%d: %d rows (%d shifts, %d vacation, %d off)",
        month, year, len(rows),
        sum(1 for r in rows if r["kind"] == KIND_WORK),
        sum(1 for r in rows if r["kind"] == KIND_VACATION),
        sum(1 for r in rows if r["kind"] == KIND_OFF),
    )
    return rows
