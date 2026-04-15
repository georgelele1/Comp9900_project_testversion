"""
gcalendar.py — Mac Calendar (EventKit) backend for Whispr.

Replaces the Google OAuth backend. Reads events directly from the
Mac Calendar app via EventKit (pyobjc) — no API keys, no tokens,
no browser OAuth. Just a one-time macOS permission prompt.

Public interface is identical to the old Google version so
cal_agent.py and app.py need zero changes:
    load_current_email()   → returns system username (used as identity)
    get_schedule(...)      → fetch events on a date
    search_events(...)     → search events by keyword

Install dependency:
    pip install pyobjc-framework-EventKit

Permission:
    macOS will prompt "Whispr wants to access your calendars" on first run.
    Grant access once — it persists. Works with any calendar synced to
    Mac Calendar (Google, iCloud, Exchange, etc.)

CLI:
    python gcalendar.py today
    python gcalendar.py tomorrow
    python gcalendar.py search <query>
    python gcalendar.py get-email
"""
from __future__ import annotations

import getpass
import json
import sys
from datetime import datetime, timedelta
from typing import Any

import pytz

DEFAULT_TZ = "Australia/Sydney"
APP_NAME   = "Whispr"

# =========================================================
# EventKit bridge
# =========================================================

def _get_event_store():
    """Return an authorised EKEventStore, requesting access if needed."""
    try:
        import EventKit
    except ImportError:
        raise RuntimeError(
            "pyobjc-framework-EventKit is not installed.\n"
            "Run: pip install pyobjc-framework-EventKit"
        )

    store = EventKit.EKEventStore.alloc().init()

    # Request calendar access (no-op if already granted)
    granted = {"value": False}
    done    = __import__("threading").Event()

    def _handler(ok, _err):
        granted["value"] = bool(ok)
        done.set()

    # macOS 17+ / EventKit newer API
    if hasattr(store, "requestFullAccessToEventsWithCompletion_"):
        store.requestFullAccessToEventsWithCompletion_(_handler)
    else:
        store.requestAccessToEntityType_completion_(0, _handler)  # 0 = EKEntityTypeEvent

    done.wait(timeout=10)

    if not granted["value"]:
        raise PermissionError(
            "Calendar access denied. "
            "Go to System Settings → Privacy & Security → Calendars and enable Whispr."
        )

    return store


# =========================================================
# Identity  (mirrors load_current_email / save_current_email)
# No email needed — we use the system username as the identity token
# so cal_agent.py's  `if not email: return "No calendar connected"` passes.
# =========================================================

def load_current_email() -> str | None:
    """Return a non-None identity string so cal_agent knows we're connected."""
    return getpass.getuser()          # e.g. "yanbo"


def save_current_email(email: str) -> None:
    pass                              # not needed for Mac Calendar


# =========================================================
# Shared helpers
# =========================================================

def _resolve_date(date: str, tz) -> datetime:
    """Convert date string → aware datetime at midnight in tz."""
    now = datetime.now(tz)
    if date == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if date == "tomorrow":
        return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    if date in ("this week", "next week"):
        # Return start of the relevant week (Monday)
        offset = 7 if date == "next week" else 0
        monday = now - timedelta(days=now.weekday()) + timedelta(days=offset)
        return monday.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        naive = datetime.strptime(date, "%Y-%m-%d")
        return tz.localize(naive)
    except ValueError:
        return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _date_range(date: str, tz) -> tuple[datetime, datetime]:
    """Return (start, end) for the requested date string."""
    start = _resolve_date(date, tz)
    if date in ("this week", "next week"):
        end = start + timedelta(days=7) - timedelta(seconds=1)
    else:
        end = start.replace(hour=23, minute=59, second=59)
    return start, end


def _ns_date(dt: datetime):
    """Convert aware Python datetime → NSDate for EventKit queries."""
    import Foundation
    return Foundation.NSDate.dateWithTimeIntervalSince1970_(dt.timestamp())


def _fmt_event(ek_event: Any, include_date: bool = False) -> str:
    """Format a single EKEvent for display."""
    title    = str(ek_event.title() or "Untitled event")
    cal_name = str(ek_event.calendar().title() or "")

    start_date = ek_event.startDate()
    # NSDate → Python datetime
    ts = start_date.timeIntervalSince1970()
    dt = datetime.fromtimestamp(ts, tz=pytz.timezone(DEFAULT_TZ))

    is_all_day = bool(ek_event.isAllDay())
    if is_all_day:
        time_str = "All day"
    else:
        time_str = dt.strftime("%I:%M %p").lstrip("0")

    if include_date:
        prefix = f"{dt.strftime('%a %d %b')} {time_str}"
    else:
        prefix = time_str

    return f"  - {prefix}: {title} [{cal_name}]"


def _filter_calendars(store: Any, calendar_filter: str) -> list:
    """Return list of EKCalendar objects matching the filter."""
    import EventKit
    all_cals = list(store.calendarsForEntityType_(0))  # 0 = EKEntityTypeEvent
    if calendar_filter == "all":
        return all_cals
    return [
        c for c in all_cals
        if calendar_filter.lower() in str(c.title() or "").lower()
    ]


# =========================================================
# get_schedule — fetch events on a specific date/range
# =========================================================

def get_schedule(
    date            : str = "today",
    timezone        : str = DEFAULT_TZ,
    user_id         : str | None = None,   # ignored — kept for interface compat
    calendar_filter : str = "all",
) -> str:
    """Fetch and format all events on a given date.

    Args:
        date:            'today', 'tomorrow', 'this week', 'next week', or YYYY-MM-DD.
        timezone:        IANA timezone string.
        user_id:         Ignored (Mac Calendar has no per-user concept).
        calendar_filter: Calendar name substring, or 'all'.
    """
    try:
        store = _get_event_store()
        import EventKit

        tz    = pytz.timezone(timezone)
        start, end = _date_range(date, tz)

        predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
            _ns_date(start),
            _ns_date(end),
            _filter_calendars(store, calendar_filter) or None,
        )
        raw_events = list(store.eventsMatchingPredicate_(predicate) or [])

        # Sort by start time
        raw_events.sort(key=lambda e: e.startDate().timeIntervalSince1970())

        if not raw_events:
            return f"No events found for {date}."

        include_date = date in ("this week", "next week")
        lines = [f"Schedule for {date}:"] + [
            _fmt_event(e, include_date=include_date) for e in raw_events
        ]
        return "\n".join(lines)

    except Exception as exc:
        return f"Could not fetch calendar: {exc}"


# =========================================================
# search_events — keyword search across the next 365 days
# =========================================================

def search_events(
    query           : str,
    timezone        : str = DEFAULT_TZ,
    user_id         : str | None = None,   # ignored
    calendar_filter : str = "all",
    max_results     : int = 10,
) -> str:
    """Search for events matching a keyword across the next 365 days.

    Args:
        query:           Search term e.g. 'exam', 'COMP9900', 'dentist'.
        timezone:        IANA timezone string.
        user_id:         Ignored.
        calendar_filter: Calendar name substring, or 'all'.
        max_results:     Max events to return.
    """
    try:
        store = _get_event_store()

        tz       = pytz.timezone(timezone)
        now      = datetime.now(tz)
        time_min = now
        time_max = now + timedelta(days=365)

        predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
            _ns_date(time_min),
            _ns_date(time_max),
            _filter_calendars(store, calendar_filter) or None,
        )
        raw_events = list(store.eventsMatchingPredicate_(predicate) or [])

        # Filter by query (EventKit has no server-side text search for local store)
        q_lower = query.lower()
        matched = [
            e for e in raw_events
            if q_lower in str(e.title() or "").lower()
            or q_lower in str(e.notes() or "").lower()
            or q_lower in str(e.location() or "").lower()
        ]

        # Sort by start time, cap results
        matched.sort(key=lambda e: e.startDate().timeIntervalSince1970())
        matched = matched[:max_results]

        if not matched:
            return f"No events found matching '{query}'."

        lines = [f"Events matching '{query}':"] + [
            _fmt_event(e, include_date=True) for e in matched
        ]
        return "\n".join(lines)

    except Exception as exc:
        return f"Could not search calendar: {exc}"


# =========================================================
# CLI  (mirrors old gcalendar.py CLI for easy testing)
# =========================================================

if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "today"

    if command == "get-email":
        print(json.dumps({"ok": True, "email": load_current_email()}, ensure_ascii=False))

    elif command == "search":
        query = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
        if not query:
            print("usage: python gcalendar.py search <query>")
            sys.exit(1)
        print(search_events(query))

    elif command in ("today", "tomorrow", "this week", "next week"):
        print(get_schedule(date=command))

    else:
        # Treat as a date string YYYY-MM-DD
        print(get_schedule(date=command))