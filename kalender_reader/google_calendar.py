"""
================================================================================
  google_calendar.py  —  A complete Google Calendar control library
================================================================================

  Provides a single class (GoogleCalendar) that wraps every common operation
  against the Google Calendar REST API v3:

    • Authentication (OAuth 2.0 with automatic token refresh)
    • Reading events  (upcoming, by date-range, by keyword, by ID)
    • Creating events (timed, all-day, recurring)
    • Updating events (any field: title, time, location, color, reminders …)
    • Deleting events (single or bulk)
    • Calendar management (list, get metadata)
    • Utility helpers  (duplicate detection, color listing, pretty-print)

  Requirements:
    pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib

  Quick start:
    from google_calendar import GoogleCalendar
    cal = GoogleCalendar()                    # opens browser for auth on first run
    events = cal.get_upcoming_events(10)
    cal.print_events(events)

  See GUIDE.md for the full walkthrough with examples.

================================================================================
"""

import os
import pickle
import logging
from datetime import datetime, timedelta, date, timezone
from typing import Optional, Union

import pytz

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# OAuth 2.0 scopes — full read/write access to Google Calendar.
# IMPORTANT: if you change this list, delete token.pickle so a new token
#            is requested with the updated permissions.
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Default timezone used when creating / updating events.
# Change this to match your local timezone, e.g. "America/New_York".
DEFAULT_TIMEZONE = "Europe/Berlin"

# Human-readable color names mapped to Google Calendar color IDs.
# These IDs are fixed by the API and will not change.
COLORS: dict[str, str] = {
    "lavender":  "1",   # #a4bdfc — light blue/lavender
    "sage":      "2",   # #7ae7bf — green/teal
    "grape":     "3",   # #dbadff — purple/violet
    "flamingo":  "4",   # #ff887c — pink/coral
    "banana":    "5",   # #fbd75b — yellow
    "tangerine": "6",   # #ffb878 — orange
    "peacock":   "7",   # #46d6db — cyan/turquoise
    "graphite":  "8",   # #e1e1e1 — grey
    "blueberry": "9",   # #5484ed — dark blue
    "green":     "10",  # #51b749 — dark green
    "tomato":    "11",  # #dc2127 — red
}

# Reverse lookup: color ID  →  color name (built automatically)
COLOR_ID_TO_NAME: dict[str, str] = {v: k for k, v in COLORS.items()}


# ---------------------------------------------------------------------------
# Type aliases  (makes function signatures easier to read)
# ---------------------------------------------------------------------------
EventDict   = dict                          # a raw Google Calendar event object
TimeInput   = Union[str, datetime, date]    # anything we accept as a time/date


# ---------------------------------------------------------------------------
# Helper utilities (module-level, not tied to the class)
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    """Return the current UTC time as an RFC-3339 string, e.g. '2026-06-29T08:00:00Z'."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_iso_datetime(value: TimeInput) -> str:
    """
    Convert a datetime / date / ISO-string to a plain ISO-8601 datetime string
    without timezone suffix (the API receives the timezone separately).

    Args:
        value: A datetime object, a date object, or an ISO-8601 string like
               '2026-04-28T14:00:00' or '2026-04-28T14:00:00+02:00'.

    Returns:
        ISO-8601 string without timezone offset, e.g. '2026-04-28T14:00:00'.
    """
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).isoformat()
    if isinstance(value, date):
        # date-only → assume start of day
        return datetime(value.year, value.month, value.day).isoformat()
    # It's already a string — strip any trailing timezone offset
    return value.split("+")[0].split("Z")[0]


def _to_date_string(value: TimeInput) -> str:
    """
    Convert a datetime / date / ISO-string to a plain date string 'YYYY-MM-DD'.

    Used exclusively for all-day events.
    """
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    # String — take just the date portion
    return str(value)[:10]


def _build_timed_body(
    title: str,
    start_str: str,
    end_str: str,
    timezone: str,
    location: str = "",
    description: str = "",
    color: str = "",
    reminders: Optional[list[dict]] = None,
    attendees: Optional[list[str]] = None,
    extended_properties: Optional[dict] = None,
) -> EventDict:
    """Build the request body for a timed event (shared by create_event and batched creates)."""
    body: EventDict = {
        "summary": title,
        "start": {"dateTime": start_str, "timeZone": timezone},
        "end":   {"dateTime": end_str,   "timeZone": timezone},
    }
    if location:
        body["location"] = location
    if description:
        body["description"] = description
    if color and color.lower() in COLORS:
        body["colorId"] = COLORS[color.lower()]
    if attendees:
        body["attendees"] = [{"email": addr} for addr in attendees]
    if reminders:
        body["reminders"] = {"useDefault": False, "overrides": reminders}
    else:
        body["reminders"] = {"useDefault": True}
    if extended_properties:
        body["extendedProperties"] = extended_properties
    return body


def _build_all_day_body(
    title: str,
    start_date: str,
    end_date: str,
    location: str = "",
    description: str = "",
    color: str = "",
    reminders: Optional[list[dict]] = None,
    extended_properties: Optional[dict] = None,
) -> EventDict:
    """Build the request body for an all-day event (shared by create_all_day_event and batched creates)."""
    body: EventDict = {
        "summary": title,
        "start": {"date": start_date},
        "end":   {"date": end_date},
    }
    if location:
        body["location"] = location
    if description:
        body["description"] = description
    if color and color.lower() in COLORS:
        body["colorId"] = COLORS[color.lower()]
    if reminders:
        body["reminders"] = {"useDefault": False, "overrides": reminders}
    if extended_properties:
        body["extendedProperties"] = extended_properties
    return body


def _build_patch_body(
    title: Optional[str] = None,
    start: Optional[TimeInput] = None,
    end: Optional[TimeInput] = None,
    timezone: str = DEFAULT_TIMEZONE,
    location: Optional[str] = None,
    description: Optional[str] = None,
    color: Optional[str] = None,
    reminders: Optional[list[dict]] = None,
    attendees: Optional[list[str]] = None,
    extended_properties: Optional[dict] = None,
) -> EventDict:
    """
    Build a partial-update (PATCH) body containing only the fields that were
    actually passed — used for batched updates, which skip the GET-then-PUT
    round trip that update_event() uses.

    Note: unlike update_event()'s extended_properties (merged into whatever
    the event already has), a PATCH replaces extendedProperties wholesale —
    pass every key you want to keep.
    """
    body: EventDict = {}
    if title is not None:
        body["summary"] = title
    if start is not None:
        body["start"] = {"dateTime": _to_iso_datetime(start), "timeZone": timezone}
    if end is not None:
        body["end"] = {"dateTime": _to_iso_datetime(end), "timeZone": timezone}
    if location is not None:
        body["location"] = location
    if description is not None:
        body["description"] = description
    if color is not None and color.lower() in COLORS:
        body["colorId"] = COLORS[color.lower()]
    if reminders is not None:
        body["reminders"] = {"useDefault": False, "overrides": reminders}
    if attendees is not None:
        body["attendees"] = [{"email": addr} for addr in attendees]
    if extended_properties is not None:
        body["extendedProperties"] = extended_properties
    return body


def _to_utc_z(value: TimeInput, timezone: str) -> str:
    """
    Convert a datetime / date / ISO-string to an RFC-3339 UTC 'Z' timestamp,
    localizing naive values to ``timezone`` first. Shared by
    get_events_in_range() and EventBatch.list_events_in_range().
    """
    try:
        tz = pytz.timezone(timezone)
    except pytz.UnknownTimeZoneError:
        logger.warning("Unknown timezone %r in config — falling back to UTC.", timezone)
        tz = pytz.timezone("UTC")
    dt_str = _to_iso_datetime(value)
    dt = datetime.fromisoformat(dt_str)
    if dt.tzinfo is None:
        dt = tz.localize(dt)
    return dt.astimezone(pytz.UTC).isoformat().replace("+00:00", "Z")


def _format_event_time(event: EventDict) -> tuple[str, str]:
    """
    Extract start and end display strings from a raw event dict.

    Returns a tuple (start_str, end_str).  For all-day events, only the date
    is returned; for timed events the full ISO datetime is returned.
    """
    start = event["start"].get("dateTime", event["start"].get("date", "?"))
    end   = event["end"].get("dateTime",   event["end"].get("date",   "?"))
    return start, end


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class GoogleCalendar:
    """
    Full-featured Google Calendar client.

    All methods return raw Google Calendar API dicts (or lists thereof) so
    you always have access to every field the API provides.  Convenience
    methods like ``print_events`` and ``print_summary`` are provided so you
    can inspect results without writing any extra code.

    Parameters
    ----------
    credentials_path : str
        Path to the OAuth 2.0 ``credentials.json`` file downloaded from
        Google Cloud Console.  Defaults to ``'credentials.json'`` in the
        current working directory.
    token_path : str
        Path where the access/refresh token is stored after the first
        successful login.  Defaults to ``'token.pickle'``.  The file is
        created automatically; you should keep it out of version control.
    timezone : str
        IANA timezone name used for all event creation / queries.
        Defaults to ``'Europe/Berlin'``.
    """

    # ------------------------------------------------------------------
    # Construction & authentication
    # ------------------------------------------------------------------

    def __init__(
        self,
        credentials_path: str = "credentials.json",
        token_path: str = "token.pickle",
        timezone: str = DEFAULT_TIMEZONE,
    ) -> None:
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.timezone = timezone
        self.service = None          # set by _authenticate()
        self._authenticate()

    def _authenticate(self) -> None:
        """
        Authenticate with Google using OAuth 2.0.

        On the very first run a browser window opens for the user to grant
        access.  The resulting token is saved to ``self.token_path`` and
        reused (with automatic refresh) on all subsequent runs.

        If the stored token can no longer be refreshed (e.g. Google rejects
        the refresh token with ``invalid_grant`` because it expired or was
        revoked), the stale token is deleted and a fresh interactive login
        is started automatically instead of crashing.

        Raises
        ------
        FileNotFoundError
            If ``credentials.json`` is missing and no valid token exists.
        """
        creds = self._load_token()

        # The token is valid and ready to use — nothing else to do.
        if creds and creds.valid:
            self.service = build("calendar", "v3", credentials=creds)
            logger.debug("Authenticated with Google Calendar API (cached token).")
            return

        # The token exists but is expired: try a silent refresh first.
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                logger.info("Access token refreshed.")
            except RefreshError as err:
                # invalid_grant → refresh token expired or revoked. The only
                # way forward is to discard it and log in again.
                logger.warning(
                    "Stored refresh token rejected by Google (%s). "
                    "Deleting stale token and starting a new login.", err
                )
                self._delete_token()
                creds = None

        # No usable token → run the interactive browser login.
        if not creds:
            creds = self._run_interactive_login()

        self._save_token(creds)
        self.service = build("calendar", "v3", credentials=creds)
        logger.info("Authenticated with Google Calendar API.")

    def _load_token(self) -> Optional[Credentials]:
        """Load the saved OAuth token, or return None if none exists / is unreadable."""
        if not os.path.exists(self.token_path):
            return None
        try:
            with open(self.token_path, "rb") as fh:
                return pickle.load(fh)
        except (pickle.UnpicklingError, EOFError, OSError) as err:
            logger.warning("Could not read token file (%s) — ignoring it.", err)
            return None

    def _save_token(self, creds: Credentials) -> None:
        """Persist the token so the next run does not need a browser login."""
        with open(self.token_path, "wb") as fh:
            pickle.dump(creds, fh)

    def _delete_token(self) -> None:
        """Remove the stored token file if present (used after a failed refresh)."""
        try:
            os.remove(self.token_path)
        except OSError as exc:
            logger.warning(
                "Could not delete stale token file %s (%s) — next run may fail to refresh again.",
                self.token_path, exc,
            )

    def _run_interactive_login(self) -> Credentials:
        """Open the browser OAuth consent flow and return fresh credentials."""
        if not os.path.exists(self.credentials_path):
            raise FileNotFoundError(
                f"credentials.json not found at: {self.credentials_path}\n"
                "Download it from https://console.cloud.google.com/  ->  "
                "APIs & Services  ->  Credentials."
            )
        flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
        return flow.run_local_server(port=0)

    # ------------------------------------------------------------------
    # READ — fetching events
    # ------------------------------------------------------------------

    def get_upcoming_events(
        self,
        max_results: int = 10,
        calendar_id: str = "primary",
    ) -> list[EventDict]:
        """
        Return the next ``max_results`` events starting from right now.

        Args:
            max_results: Maximum number of events to return (default 10).
            calendar_id: Calendar to query.  Use ``'primary'`` for the
                         user's main calendar, or pass a calendar ID from
                         :meth:`list_calendars`.

        Returns:
            A list of event dicts, ordered by start time.  Returns ``[]``
            on error or when no upcoming events exist.

        Example:
            events = cal.get_upcoming_events(5)
            for e in events:
                print(e['summary'])
        """
        now = _utc_now_iso()  # UTC timestamp required by the API
        return self._list_events(
            calendar_id=calendar_id,
            time_min=now,
            max_results=max_results,
            label=f"next {max_results} events",
        )

    def get_events_in_range(
        self,
        start: TimeInput,
        end: TimeInput,
        max_results: int = 50,
        calendar_id: str = "primary",
    ) -> list[EventDict]:
        """
        Return all events that fall within a specific date / time window.

        Args:
            start: Window start — datetime, date, or ISO string.
            end:   Window end   — datetime, date, or ISO string.
            max_results: Upper limit on the number of results.
            calendar_id: Calendar to query.

        Returns:
            List of event dicts ordered by start time.

        Example:
            from datetime import date
            events = cal.get_events_in_range(date(2026, 5, 1), date(2026, 5, 31))
        """
        return self._list_events(
            calendar_id=calendar_id,
            time_min=_to_utc_z(start, self.timezone),
            time_max=_to_utc_z(end, self.timezone),
            max_results=max_results,
            label=f"events between {_to_date_string(start)} and {_to_date_string(end)}",
        )

    def search_events(
        self,
        keyword: str,
        max_results: int = 20,
        calendar_id: str = "primary",
    ) -> list[EventDict]:
        """
        Full-text search across all upcoming events.

        Google searches within title, description, location, and attendees.

        Args:
            keyword:     Search term.
            max_results: Maximum results to return.
            calendar_id: Calendar to query.

        Returns:
            List of matching event dicts.

        Example:
            results = cal.search_events("dentist")
        """
        now = _utc_now_iso()
        return self._list_events(
            calendar_id=calendar_id,
            time_min=now,
            max_results=max_results,
            query=keyword,
            label=f"events matching '{keyword}'",
        )

    def get_event_by_id(
        self,
        event_id: str,
        calendar_id: str = "primary",
    ) -> Optional[EventDict]:
        """
        Fetch a single event by its unique Google Calendar event ID.

        Args:
            event_id:    The event's ``id`` field.
            calendar_id: Calendar that owns the event.

        Returns:
            The event dict, or ``None`` if not found.
        """
        try:
            event = (
                self.service.events()
                .get(calendarId=calendar_id, eventId=event_id)
                .execute()
            )
            return event
        except HttpError:
            logger.exception("Could not fetch event '%s'", event_id)
            return None

    def get_event_by_title(
        self,
        title: str,
        calendar_id: str = "primary",
    ) -> Optional[EventDict]:
        """
        Find the first upcoming event whose title matches ``title``.

        The match is handled server-side by Google's full-text search, so
        partial matches are supported (e.g. ``"Meeting"`` finds ``"Team Meeting"``).

        Args:
            title:       Full or partial event title.
            calendar_id: Calendar to search.

        Returns:
            The first matching event dict, or ``None`` if nothing found.

        Example:
            event = cal.get_event_by_title("Team Meeting")
            if event:
                print(event['id'])
        """
        events = self.search_events(title, max_results=50, calendar_id=calendar_id)
        for event in events:
            if title.lower() in event.get("summary", "").lower():
                return event
        logger.info("No upcoming event found with title: '%s'", title)
        return None

    # ------------------------------------------------------------------
    # CREATE — adding new events
    # ------------------------------------------------------------------

    def create_event(
        self,
        title: str,
        start: TimeInput,
        end: Optional[TimeInput] = None,
        location: str = "",
        description: str = "",
        color: str = "",
        reminders: Optional[list[dict]] = None,
        attendees: Optional[list[str]] = None,
        extended_properties: Optional[dict] = None,
        calendar_id: str = "primary",
    ) -> Optional[EventDict]:
        """
        Create a new timed calendar event.

        Args:
            title:       Event title / summary.
            start:       Start time — ISO string ``'2026-04-28T14:00:00'``,
                         a datetime object, or a date object (→ 00:00 local time).
            end:         End time.  If omitted, defaults to 1 hour after ``start``.
            location:    Physical or virtual location string (optional).
            description: Free-text notes visible in the event detail view (optional).
            color:       Color name from the COLORS dict, e.g. ``'tomato'``,
                         ``'blueberry'``, ``'banana'`` (optional).
            reminders:   List of reminder dicts, each with keys ``'method'``
                         (``'popup'`` or ``'email'``) and ``'minutes'`` (int).
                         Example: ``[{'method': 'popup', 'minutes': 15}]``
            attendees:   List of attendee e-mail addresses.  Google will send
                         invitation e-mails to each address (optional).
            extended_properties: Custom metadata stored on the event, e.g.
                         ``{'private': {'source': 'my_tool'}}``.  Useful for
                         tagging events your program created so you can find
                         them again later (optional).
            calendar_id: Target calendar.  Defaults to ``'primary'``.

        Returns:
            The newly created event dict (contains the ``'id'`` field), or
            ``None`` on error.

        Example:
            cal.create_event(
                title='Team Meeting',
                start='2026-04-28T14:00:00',
                end='2026-04-28T15:00:00',
                location='Conference Room A',
                description='Weekly sync — bring your status updates.',
                color='peacock',
                reminders=[
                    {'method': 'popup', 'minutes': 15},
                    {'method': 'email', 'minutes': 60},
                ],
                attendees=['alice@example.com', 'bob@example.com'],
            )
        """
        try:
            start_str = _to_iso_datetime(start)

            # Auto-calculate end time if not provided
            if end is None:
                end_str = (
                    datetime.fromisoformat(start_str) + timedelta(hours=1)
                ).isoformat()
            else:
                end_str = _to_iso_datetime(end)

            body = _build_timed_body(
                title, start_str, end_str, self.timezone,
                location=location, description=description, color=color,
                reminders=reminders, attendees=attendees,
                extended_properties=extended_properties,
            )

            result = (
                self.service.events()
                .insert(calendarId=calendar_id, body=body)
                .execute()
            )

            logger.info("Event created: '%s'", title)
            logger.debug("   ID:    %s", result['id'])
            logger.debug("   Start: %s", result['start'].get('dateTime', result['start'].get('date')))
            logger.debug("   End:   %s", result['end'].get('dateTime', result['end'].get('date')))
            if color:
                logger.debug("   Color: %s", color)
            return result

        except HttpError:
            logger.exception("Failed to create event '%s'", title)
            return None

    def create_all_day_event(
        self,
        title: str,
        day: TimeInput,
        end_day: Optional[TimeInput] = None,
        location: str = "",
        description: str = "",
        color: str = "",
        reminders: Optional[list[dict]] = None,
        extended_properties: Optional[dict] = None,
        calendar_id: str = "primary",
    ) -> Optional[EventDict]:
        """
        Create an all-day event (no time component).

        For multi-day events, supply ``end_day`` as the inclusive last day of
        the event.  Google Calendar stores the end date as *exclusive*, but
        this method hides that detail: it always adds the required +1 day for
        you, so a single day (``end_day=None``) and a range behave the same way.

        Args:
            title:       Event title.
            day:         The event date — ISO string ``'2026-05-01'``, a date
                         object, or a datetime object (time portion is ignored).
            end_day:     Last day of the event (inclusive).  If omitted, the
                         event spans only ``day``.
            location:    Optional location.
            description: Optional description.
            color:       Optional color name.
            reminders:   List of reminder dicts, each with keys ``'method'``
                         (``'popup'`` or ``'email'``) and ``'minutes'``.  For an
                         all-day event the minutes count back from midnight of
                         the first day (e.g. ``420`` = 17:00 the day before).
            extended_properties: Custom metadata stored on the event, e.g.
                         ``{'private': {'source': 'my_tool'}}`` (optional).
            calendar_id: Target calendar.

        Returns:
            The created event dict, or ``None`` on error.

        Example:
            # Single day
            cal.create_all_day_event(title='Public Holiday', day='2026-05-01', color='banana')

            # Multi-day vacation
            cal.create_all_day_event(
                title='Summer Vacation',
                day='2026-07-14',
                end_day='2026-07-21',
                color='sage',
            )
        """
        try:
            start_date = _to_date_string(day)

            # Google's end date is exclusive (the day *after* the last day), so
            # we always add one day to the inclusive last day the caller gives us.
            last_day = start_date if end_day is None else _to_date_string(end_day)
            end_date = (
                datetime.strptime(last_day, "%Y-%m-%d") + timedelta(days=1)
            ).strftime("%Y-%m-%d")

            body = _build_all_day_body(
                title, start_date, end_date,
                location=location, description=description, color=color,
                reminders=reminders, extended_properties=extended_properties,
            )

            result = (
                self.service.events()
                .insert(calendarId=calendar_id, body=body)
                .execute()
            )

            logger.info("All-day event created: '%s'", title)
            logger.debug("   ID:   %s", result['id'])
            logger.debug("   Date: %s", start_date)
            return result

        except HttpError:
            logger.exception("Failed to create all-day event '%s'", title)
            return None

    def create_recurring_event(
        self,
        title: str,
        start: TimeInput,
        end: Optional[TimeInput] = None,
        frequency: str = "WEEKLY",
        count: Optional[int] = None,
        until: Optional[str] = None,
        interval: int = 1,
        days_of_week: Optional[list[str]] = None,
        location: str = "",
        description: str = "",
        color: str = "",
        reminders: Optional[list[dict]] = None,
        calendar_id: str = "primary",
    ) -> Optional[EventDict]:
        """
        Create a recurring event using RRULE syntax.

        Args:
            title:         Event title.
            start:         Start time of the *first* occurrence.
            end:           End time of the first occurrence (default: +1 hour).
            frequency:     Repeat frequency — ``'DAILY'``, ``'WEEKLY'``,
                           ``'MONTHLY'``, or ``'YEARLY'``.
            count:         Total number of occurrences (mutually exclusive
                           with ``until``).
            until:         Repeat until this date, e.g. ``'20261231'``.
                           Format: ``YYYYMMDD``.
            interval:      Repeat every N units.  ``interval=2`` with
                           ``frequency='WEEKLY'`` means every 2 weeks.
            days_of_week:  For WEEKLY recurrence, a list of 2-letter day
                           codes: ``['MO', 'WE', 'FR']``.
            location:      Optional location.
            description:   Optional description.
            color:         Optional color name.
            reminders:     Optional reminders list.
            calendar_id:   Target calendar.

        Returns:
            The created (master) event dict, or ``None`` on error.

        Example:
            # Every Monday at 09:00, 10 times
            cal.create_recurring_event(
                title='Stand-up',
                start='2026-05-04T09:00:00',
                end='2026-05-04T09:15:00',
                frequency='WEEKLY',
                days_of_week=['MO'],
                count=10,
            )
        """
        # Build the RRULE string
        rrule_parts = [f"FREQ={frequency.upper()}", f"INTERVAL={interval}"]
        if days_of_week:
            rrule_parts.append(f"BYDAY={','.join(d.upper() for d in days_of_week)}")
        if count:
            rrule_parts.append(f"COUNT={count}")
        elif until:
            rrule_parts.append(f"UNTIL={until}")

        rrule = "RRULE:" + ";".join(rrule_parts)

        try:
            start_str = _to_iso_datetime(start)
            if end is None:
                end_str = (
                    datetime.fromisoformat(start_str) + timedelta(hours=1)
                ).isoformat()
            else:
                end_str = _to_iso_datetime(end)

            body: EventDict = {
                "summary": title,
                "start":   {"dateTime": start_str, "timeZone": self.timezone},
                "end":     {"dateTime": end_str,   "timeZone": self.timezone},
                "recurrence": [rrule],
            }

            if location:
                body["location"] = location
            if description:
                body["description"] = description
            if color and color.lower() in COLORS:
                body["colorId"] = COLORS[color.lower()]
            if reminders:
                body["reminders"] = {"useDefault": False, "overrides": reminders}

            result = (
                self.service.events()
                .insert(calendarId=calendar_id, body=body)
                .execute()
            )

            logger.info("Recurring event created: '%s' (%s)", title, rrule)
            logger.debug("   ID: %s", result['id'])
            return result

        except HttpError:
            logger.exception("Failed to create recurring event '%s'", title)
            return None

    # ------------------------------------------------------------------
    # BATCH — many creates/updates/deletes in a single HTTP round trip
    # ------------------------------------------------------------------

    def new_batch(self) -> "EventBatch":
        """
        Start a batch of event operations sent to Google in one HTTP request
        instead of one request per call.

        Every create_event / update_event / delete_event above does its own
        network round trip. For many changes at once (e.g. syncing a whole
        month of shifts) that adds up — Google allows batching up to 1000
        calls into a single request.

        Returns:
            An EventBatch — call create_event() / create_all_day_event() /
            update_event() / delete_event() on it exactly like on the
            GoogleCalendar client, then batch.execute() once at the end.

        Example:
            batch = cal.new_batch()
            batch.create_event(title="Shift", start="2026-05-05T08:00:00", end="2026-05-05T16:00:00")
            batch.update_event(event_id="abc123", color="tomato")
            batch.delete_event(event_id="def456")
            results = batch.execute()          # one HTTP round trip
            for r in results:
                if not r.ok:
                    print("failed:", r.error)
        """
        return EventBatch(self)

    # ------------------------------------------------------------------
    # UPDATE — modifying existing events
    # ------------------------------------------------------------------

    def update_event(
        self,
        event_id: str,
        title: Optional[str] = None,
        start: Optional[TimeInput] = None,
        end: Optional[TimeInput] = None,
        location: Optional[str] = None,
        description: Optional[str] = None,
        color: Optional[str] = None,
        reminders: Optional[list[dict]] = None,
        attendees: Optional[list[str]] = None,
        extended_properties: Optional[dict] = None,
        calendar_id: str = "primary",
    ) -> Optional[EventDict]:
        """
        Update any combination of fields on an existing event.

        Only the arguments you pass are changed; all other fields stay as-is.
        To *remove* a field (e.g. clear the location), pass an empty string ``''``.

        Args:
            event_id:    The event's ``id`` field (from :meth:`get_event_by_title`
                         or :meth:`get_upcoming_events`).
            title:       New title / summary (optional).
            start:       New start time (optional).
            end:         New end time (optional).
            location:    New location (optional).  Pass ``''`` to clear.
            description: New description (optional).  Pass ``''`` to clear.
            color:       New color name (optional).
            reminders:   New reminders list (optional).
            attendees:   Replace attendee list with these e-mail addresses (optional).
            extended_properties: Custom metadata to merge into the event's
                         existing private/shared properties (optional).
            calendar_id: Calendar that owns the event.

        Returns:
            The updated event dict, or ``None`` on error.

        Example:
            event = cal.get_event_by_title('Team Meeting')
            cal.update_event(
                event_id=event['id'],
                title='Team Meeting — Cancelled',
                color='graphite',
                description='This meeting has been cancelled.',
            )
        """
        try:
            # Fetch the current state of the event
            event = (
                self.service.events()
                .get(calendarId=calendar_id, eventId=event_id)
                .execute()
            )

            # Apply only the changes that were supplied
            if title is not None:
                event["summary"] = title
            if start is not None:
                event["start"] = {
                    "dateTime": _to_iso_datetime(start),
                    "timeZone": self.timezone,
                }
            if end is not None:
                event["end"] = {
                    "dateTime": _to_iso_datetime(end),
                    "timeZone": self.timezone,
                }
            if location is not None:
                event["location"] = location
            if description is not None:
                event["description"] = description
            if color is not None and color.lower() in COLORS:
                event["colorId"] = COLORS[color.lower()]
            if reminders is not None:
                event["reminders"] = {
                    "useDefault": False,
                    "overrides": reminders,
                }
            if attendees is not None:
                event["attendees"] = [{"email": addr} for addr in attendees]
            if extended_properties is not None:
                # Merge into whatever is already on the event so we never wipe
                # out properties set elsewhere.
                merged = event.get("extendedProperties", {})
                for scope in ("private", "shared"):
                    if scope in extended_properties:
                        merged.setdefault(scope, {}).update(extended_properties[scope])
                event["extendedProperties"] = merged

            result = (
                self.service.events()
                .update(calendarId=calendar_id, eventId=event_id, body=event)
                .execute()
            )

            logger.info("Event updated: '%s'", result['summary'])
            logger.debug("   ID: %s", result['id'])
            return result

        except HttpError:
            logger.exception("Failed to update event '%s'", event_id)
            return None

    def update_event_by_title(
        self,
        title: str,
        calendar_id: str = "primary",
        **kwargs,
    ) -> Optional[EventDict]:
        """
        Convenience wrapper: find an event by title, then update it.

        All keyword arguments are forwarded to :meth:`update_event`.

        Example:
            cal.update_event_by_title(
                'Dentist',
                start='2026-05-10T10:00:00',
                color='blueberry',
            )
        """
        event = self.get_event_by_title(title, calendar_id=calendar_id)
        if event:
            return self.update_event(event["id"], calendar_id=calendar_id, **kwargs)
        return None

    # ------------------------------------------------------------------
    # DELETE — removing events
    # ------------------------------------------------------------------

    def delete_event(
        self,
        event_id: str,
        calendar_id: str = "primary",
    ) -> bool:
        """
        Permanently delete an event by its ID.

        Args:
            event_id:    ID of the event to delete.
            calendar_id: Calendar that owns the event.

        Returns:
            ``True`` on success, ``False`` on error.

        Example:
            event = cal.get_event_by_title('Lunch Break')
            if event:
                cal.delete_event(event['id'])
        """
        try:
            # Fetch the title first so we can show a meaningful message
            event = (
                self.service.events()
                .get(calendarId=calendar_id, eventId=event_id)
                .execute()
            )
            label = event.get("summary", "(no title)")

            self.service.events().delete(
                calendarId=calendar_id, eventId=event_id
            ).execute()

            logger.info("Event deleted: '%s' (ID: %s)", label, event_id)
            return True

        except HttpError:
            logger.exception("Failed to delete event '%s'", event_id)
            return False

    def delete_event_by_title(
        self,
        title: str,
        calendar_id: str = "primary",
    ) -> bool:
        """
        Delete the first upcoming event whose title matches ``title``.

        Example:
            cal.delete_event_by_title('Old Meeting')
        """
        event = self.get_event_by_title(title, calendar_id=calendar_id)
        if event:
            return self.delete_event(event["id"], calendar_id=calendar_id)
        return False

    def delete_all_by_title(
        self,
        title: str,
        max_results: int = 100,
        calendar_id: str = "primary",
    ) -> int:
        """
        Delete *all* upcoming events whose title contains ``title``.

        Useful for cleaning up a series of accidentally created duplicates.

        Args:
            title:       Title substring to match (case-insensitive).
            max_results: Maximum number of events to scan.
            calendar_id: Calendar to search.

        Returns:
            Number of events deleted.

        Example:
            deleted = cal.delete_all_by_title('Test Event')
            print(f"Deleted {deleted} events.")
        """
        events = self.search_events(title, max_results=max_results, calendar_id=calendar_id)
        deleted = 0
        for event in events:
            if title.lower() in event.get("summary", "").lower():
                if self.delete_event(event["id"], calendar_id=calendar_id):
                    deleted += 1
        logger.info("Total deleted: %d event(s) matching '%s'", deleted, title)
        return deleted

    # ------------------------------------------------------------------
    # DUPLICATE MANAGEMENT
    # ------------------------------------------------------------------

    def find_duplicates(
        self,
        max_results: int = 100,
        calendar_id: str = "primary",
    ) -> list[EventDict]:
        """
        Find upcoming events that share the same (title, start-time) pair.

        A common pair is kept; all extra occurrences are returned as duplicates.

        Args:
            max_results: Number of events to scan.
            calendar_id: Calendar to inspect.

        Returns:
            List of duplicate event dicts (the ones that should be removed).
        """
        events = self.get_upcoming_events(max_results=max_results, calendar_id=calendar_id)
        seen: dict[tuple, str] = {}
        duplicates: list[EventDict] = []

        for event in events:
            key = (
                event.get("summary", ""),
                event["start"].get("dateTime", event["start"].get("date", "")),
            )
            if key in seen:
                duplicates.append(event)
            else:
                seen[key] = event["id"]

        logger.info("Found %d duplicate event(s).", len(duplicates))
        return duplicates

    def delete_duplicates(
        self,
        max_results: int = 100,
        calendar_id: str = "primary",
    ) -> int:
        """
        Find and delete all duplicate upcoming events.

        Args:
            max_results: Number of events to scan.
            calendar_id: Calendar to clean.

        Returns:
            Number of events deleted.
        """
        duplicates = self.find_duplicates(max_results=max_results, calendar_id=calendar_id)
        deleted = 0
        for event in duplicates:
            if self.delete_event(event["id"], calendar_id=calendar_id):
                deleted += 1
        logger.info("Cleaned up %d duplicate event(s).", deleted)
        return deleted

    # ------------------------------------------------------------------
    # CALENDAR MANAGEMENT
    # ------------------------------------------------------------------

    def list_calendars(self) -> list[dict]:
        """
        Return all calendars accessible to the authenticated user.

        Each entry contains at least ``'id'``, ``'summary'``, and
        ``'accessRole'``.

        Returns:
            List of calendar metadata dicts.

        Example:
            for cal_info in cal.list_calendars():
                print(cal_info['id'], cal_info['summary'])
        """
        try:
            result = self.service.calendarList().list().execute()
            items = result.get("items", [])
            logger.info("Found %d calendar(s).", len(items))
            for item in items:
                logger.debug("   [%-10s]  %-35s  ID: %s", item.get('accessRole', '?'), item['summary'], item['id'])
            return items
        except HttpError:
            logger.exception("Failed to list calendars")
            return []

    def get_available_colors(self) -> dict:
        """
        Fetch the color definitions directly from the Google Calendar API.

        Returns the raw API response which contains ``'event'`` and
        ``'calendar'`` color palettes with hex codes.

        Returns:
            Dict with ``'event'`` and ``'calendar'`` keys.

        Example:
            colors = cal.get_available_colors()
            for cid, info in colors['event'].items():
                print(cid, info['background'])
        """
        try:
            colors = self.service.colors().get().execute()
            print("[COLOR] Available event colors:")
            print(f"  {'ID':>3}  {'Name':12}  Background   Foreground")
            print("  " + "-" * 42)
            for cid in sorted(colors.get("event", {}).keys(), key=lambda x: int(x) if x.isdigit() else 99):
                info = colors["event"][cid]
                name = COLOR_ID_TO_NAME.get(cid, "?")
                print(f"  {cid:>3}  {name:12}  {info.get('background','?'):12} {info.get('foreground','?')}")
            return colors
        except HttpError:
            logger.exception("Failed to fetch colors")
            return {}

    # ------------------------------------------------------------------
    # DISPLAY HELPERS
    #
    # These intentionally use print(), not logger — they are for a human
    # reading a terminal interactively (see the class docstring), not for
    # the app's own production logging path. Do not convert them to logger.
    # ------------------------------------------------------------------

    def print_events(self, events: list[EventDict], show_id: bool = False) -> None:
        """
        Print a detailed, human-readable view of a list of events.

        Args:
            events:  List of event dicts (from any get_* method).
            show_id: If True, include the Google event ID in the output.

        Example:
            events = cal.get_upcoming_events(5)
            cal.print_events(events)
        """
        if not events:
            print("  (no events to display)")
            return

        for i, event in enumerate(events, 1):
            start, end = _format_event_time(event)
            title       = event.get("summary",     "(no title)")
            location    = event.get("location",    "")
            description = event.get("description", "")
            color_id    = event.get("colorId",     "")
            color_name  = COLOR_ID_TO_NAME.get(color_id, "default") if color_id else "default"

            print(f"\n{'─'*60}")
            print(f"  #{i:02}  {title}")
            print(f"{'─'*60}")
            print(f"  Start:  {start}")
            print(f"  End:    {end}")
            if location:
                print(f"  Location:    {location}")
            if description:
                snippet = description[:120] + ("..." if len(description) > 120 else "")
                print(f"  Description: {snippet}")
            if color_id:
                print(f"  Color:       {color_name} (ID {color_id})")
            if show_id:
                print(f"  Event ID:    {event['id']}")

    def print_summary(self, events: list[EventDict]) -> None:
        """
        Print a compact one-line-per-event overview table.

        Args:
            events: List of event dicts.

        Example:
            cal.print_summary(cal.get_upcoming_events(10))
        """
        if not events:
            print("  (no events)")
            return

        print(f"\n  {'#':>3}  {'Title':<40}  {'Start'}")
        print("  " + "─" * 70)
        for i, event in enumerate(events, 1):
            start, _ = _format_event_time(event)
            title    = event.get("summary", "(no title)")
            print(f"  {i:>3}.  {title:<40}  {start}")
        print()

    def print_colors(self) -> None:
        """
        Print the COLORS constant in a readable table.

        Shows the name you pass to ``color=`` and the corresponding Google ID.
        """
        print("\n  [COLOR] Available color names for events:")
        print(f"  {'Name':12}  Google ID")
        print("  " + "─" * 25)
        for name, cid in COLORS.items():
            print(f"  {name:12}  {cid}")
        print()

    # ------------------------------------------------------------------
    # Internal / private helpers
    # ------------------------------------------------------------------

    def _list_events(
        self,
        calendar_id: str,
        time_min: str,
        max_results: int,
        time_max: Optional[str] = None,
        query: Optional[str] = None,
        label: str = "events",
    ) -> list[EventDict]:
        """
        Shared internal method that calls the Google Calendar events.list() API.

        All public read methods delegate here to avoid code duplication.
        """
        try:
            params: dict = {
                "calendarId":   calendar_id,
                "timeMin":      time_min,
                "maxResults":   max_results,
                "singleEvents": True,       # expand recurring events
                "orderBy":      "startTime",
                "timeZone":     self.timezone,
            }
            if time_max:
                params["timeMax"] = time_max
            if query:
                params["q"] = query

            result = self.service.events().list(**params).execute()
            events = result.get("items", [])

            if not events:
                logger.debug("No %s found.", label)
            else:
                logger.debug("%d %s found.", len(events), label)

            return events

        except HttpError:
            logger.exception("Error fetching %s", label)
            return []


# ---------------------------------------------------------------------------
# Batch operations
# ---------------------------------------------------------------------------

class BatchItemResult:
    """Outcome of one call queued in an EventBatch."""

    __slots__ = ("event", "error")

    def __init__(self, event: Optional[EventDict] = None, error: Optional[Exception] = None) -> None:
        self.event = event
        self.error = error

    @property
    def ok(self) -> bool:
        return self.error is None


class EventBatch:
    """
    Queues create/update/delete event calls and sends them all in a single
    HTTP request via GoogleCalendar.new_batch().

    Results are returned by execute() in the same order the calls were queued.
    """

    def __init__(self, cal: "GoogleCalendar") -> None:
        self._cal = cal
        self._batch = cal.service.new_batch_http_request()
        self._results: list[Optional[BatchItemResult]] = []

    def _queue(self, request) -> None:
        index = len(self._results)
        self._results.append(None)

        def _callback(request_id, response, exception):
            self._results[index] = BatchItemResult(event=response, error=exception)

        self._batch.add(request, callback=_callback)

    def list_events_in_range(
        self,
        start: TimeInput,
        end: TimeInput,
        max_results: int = 200,
        calendar_id: str = "primary",
    ) -> None:
        """
        Queue a read: fetch every event in [start, end).

        Unlike the other queued calls, on success result.event is the raw
        API response — a dict with an ``'items'`` key — not a single event.
        Useful for fetching many date ranges (e.g. many months) in one HTTP
        round trip instead of one events.list() call each.
        """
        self._queue(
            self._cal.service.events().list(
                calendarId=calendar_id,
                timeMin=_to_utc_z(start, self._cal.timezone),
                timeMax=_to_utc_z(end, self._cal.timezone),
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
                timeZone=self._cal.timezone,
            )
        )

    def create_event(
        self,
        title: str,
        start: TimeInput,
        end: Optional[TimeInput] = None,
        location: str = "",
        description: str = "",
        color: str = "",
        reminders: Optional[list[dict]] = None,
        attendees: Optional[list[str]] = None,
        extended_properties: Optional[dict] = None,
        calendar_id: str = "primary",
    ) -> None:
        """Queue a timed event creation. Same arguments as GoogleCalendar.create_event()."""
        start_str = _to_iso_datetime(start)
        end_str = (
            (datetime.fromisoformat(start_str) + timedelta(hours=1)).isoformat()
            if end is None else _to_iso_datetime(end)
        )
        body = _build_timed_body(
            title, start_str, end_str, self._cal.timezone,
            location=location, description=description, color=color,
            reminders=reminders, attendees=attendees,
            extended_properties=extended_properties,
        )
        self._queue(self._cal.service.events().insert(calendarId=calendar_id, body=body))

    def create_all_day_event(
        self,
        title: str,
        day: TimeInput,
        end_day: Optional[TimeInput] = None,
        location: str = "",
        description: str = "",
        color: str = "",
        reminders: Optional[list[dict]] = None,
        extended_properties: Optional[dict] = None,
        calendar_id: str = "primary",
    ) -> None:
        """Queue an all-day event creation. Same arguments as GoogleCalendar.create_all_day_event()."""
        start_date = _to_date_string(day)
        last_day = start_date if end_day is None else _to_date_string(end_day)
        end_date = (
            datetime.strptime(last_day, "%Y-%m-%d") + timedelta(days=1)
        ).strftime("%Y-%m-%d")
        body = _build_all_day_body(
            title, start_date, end_date,
            location=location, description=description, color=color,
            reminders=reminders, extended_properties=extended_properties,
        )
        self._queue(self._cal.service.events().insert(calendarId=calendar_id, body=body))

    def update_event(
        self,
        event_id: str,
        title: Optional[str] = None,
        start: Optional[TimeInput] = None,
        end: Optional[TimeInput] = None,
        location: Optional[str] = None,
        description: Optional[str] = None,
        color: Optional[str] = None,
        reminders: Optional[list[dict]] = None,
        attendees: Optional[list[str]] = None,
        extended_properties: Optional[dict] = None,
        calendar_id: str = "primary",
    ) -> None:
        """
        Queue a partial update (PATCH) — only the fields you pass are changed.

        Unlike GoogleCalendar.update_event(), this never fetches the current
        event first (that would cost a round trip per item, defeating the
        point of batching), so extended_properties REPLACES the event's
        existing extendedProperties instead of merging into it — pass every
        key you want to keep.
        """
        body = _build_patch_body(
            title=title, start=start, end=end, timezone=self._cal.timezone,
            location=location, description=description, color=color,
            reminders=reminders, attendees=attendees,
            extended_properties=extended_properties,
        )
        self._queue(
            self._cal.service.events().patch(calendarId=calendar_id, eventId=event_id, body=body)
        )

    def delete_event(self, event_id: str, calendar_id: str = "primary") -> None:
        """Queue an event deletion."""
        self._queue(self._cal.service.events().delete(calendarId=calendar_id, eventId=event_id))

    def execute(self) -> list[BatchItemResult]:
        """
        Send every queued call in one HTTP request and return one
        BatchItemResult per call, in the order they were queued. A batch
        with nothing queued is a no-op (an empty batch would otherwise raise).
        """
        if self._results:
            self._batch.execute()
        return self._results
