"""
Google Calendar integration for Whispr.

Per-user OAuth2 — each Google account gets its own token stored locally,
keyed by the user's actual Google email address.

First run opens a browser for one-time Google approval.
Subsequent runs refresh silently using the stored token.

Usage:
    python gcalendar.py today
    python gcalendar.py tomorrow
    python gcalendar.py get-email
    python gcalendar.py connect
"""
from __future__ import annotations

import getpass
import json
import os
import sys
import threading
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytz
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from connectonion import Agent

APP_NAME         = "Whispr"
SCOPES           = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]
REDIRECT_URI     = "http://localhost:8765/callback"
CREDENTIALS_FILE = Path(__file__).resolve().parent / "credentials.json"


# =========================================================
# Per-user token storage (keyed by Google email)
# =========================================================

def _tokens_dir() -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support" / APP_NAME / "tokens"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(home))) / APP_NAME / "tokens"
    else:
        base = home / ".local" / "share" / APP_NAME / "tokens"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _token_path(email: str) -> Path:
    safe = email.replace("@", "_at_").replace(".", "_")
    return _tokens_dir() / f"{safe}.json"


def _current_email_file() -> Path:
    return _tokens_dir() / f"{getpass.getuser()}_current_email.txt"


def save_current_email(email: str) -> None:
    _current_email_file().write_text(email, encoding="utf-8")


def load_current_email() -> str | None:
    path = _current_email_file()
    return path.read_text(encoding="utf-8").strip() or None if path.exists() else None


# =========================================================
# OAuth flow (browser-based, one-time per Google account)
# =========================================================

def run_oauth_flow() -> tuple[Credentials, str]:
    """Open browser for Google login, return (credentials, email)."""
    flow = Flow.from_client_secrets_file(
        str(CREDENTIALS_FILE), scopes=SCOPES, redirect_uri=REDIRECT_URI,
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent",
    )

    auth_code   = {"value": None}
    server_done = threading.Event()

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if urlparse(self.path).path == "/callback":
                params = parse_qs(urlparse(self.path).query)
                auth_code["value"] = params.get("code", [None])[0]
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"""
                    <html><body style='font-family:sans-serif;text-align:center;padding:60px'>
                    <h2>Whispr connected to Google Calendar</h2>
                    <p>You can close this tab.</p>
                    </body></html>
                """)
                server_done.set()
        def log_message(self, *_): pass

    threading.Thread(
        target=lambda: HTTPServer(("localhost", 8765), _Handler).handle_request(),
        daemon=True,
    ).start()

    print("Opening browser for Google login...", file=sys.stderr)
    webbrowser.open(auth_url)
    server_done.wait(timeout=120)

    if not auth_code["value"]:
        raise RuntimeError("Google login timed out or was cancelled.")

    flow.fetch_token(code=auth_code["value"])
    creds = flow.credentials

    import google.auth.transport.requests as _gtr
    email = _gtr.AuthorizedSession(creds).get(
        "https://www.googleapis.com/oauth2/v3/userinfo"
    ).json().get("email", getpass.getuser())

    _token_path(email).write_text(creds.to_json(), encoding="utf-8")
    save_current_email(email)
    print(f"Token saved for: {email}", file=sys.stderr)
    return creds, email


# =========================================================
# Auth
# =========================================================

def get_credentials(user_id: str | None = None) -> tuple[Credentials, str]:
    """Return (valid_credentials, google_email), triggering OAuth if needed."""
    email = user_id or load_current_email()

    if email:
        path  = _token_path(email)
        creds = None

        if path.exists():
            creds = Credentials.from_authorized_user_file(str(path), SCOPES)

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            path.write_text(creds.to_json(), encoding="utf-8")
            return creds, email

        if creds and creds.valid:
            return creds, email

    return run_oauth_flow()


# =========================================================
# Intent extraction
# =========================================================

def extract_calendar_intent(text: str) -> dict:
    """Extract date and calendar name from transcribed speech in one LLM call.

    Returns {"date": "today|tomorrow|YYYY-MM-DD", "calendar": "name|all"}.
    """
    agent = Agent(
        model="gpt-5",
        name="whispr_calendar_intent",
        system_prompt=(
            "Extract date and calendar from speech. "
            'Reply ONLY with JSON: {"date":"today|tomorrow|YYYY-MM-DD","calendar":"name|all"}. '
            "Default date=today, calendar=all if not mentioned. No explanation."
        ),
    )
    try:
        return json.loads(str(agent.input(text)).strip())
    except Exception:
        return {"date": "today", "calendar": "all"}


# =========================================================
# Schedule fetcher
# =========================================================

def get_schedule(
    date: str = "today",
    timezone: str = "Australia/Sydney",
    user_id: str | None = None,
    calendar_filter: str = "all",
) -> str:
    """Fetch and format Google Calendar events for a given date.

    Args:
        date:            'today', 'tomorrow', or YYYY-MM-DD.
        timezone:        IANA timezone string.
        user_id:         Google email — defaults to last logged-in account.
        calendar_filter: Calendar name substring, or 'all'.
    """
    try:
        creds, email = get_credentials(user_id)
        service = build("calendar", "v3", credentials=creds)

        tz  = pytz.timezone(timezone)
        now = datetime.now(tz)

        if date == "today":
            target = now
        elif date == "tomorrow":
            target = now + timedelta(days=1)
        else:
            try:
                target = tz.localize(datetime.strptime(date, "%Y-%m-%d"))
            except ValueError:
                target = now

        start = target.replace(hour=0,  minute=0,  second=0,  microsecond=0).isoformat()
        end   = target.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()

        all_cals  = service.calendarList().list().execute().get("items", [])
        calendars = (
            all_cals if calendar_filter == "all"
            else [c for c in all_cals if calendar_filter.lower() in c.get("summary", "").lower()]
        )

        all_events = []
        for cal in calendars:
            for event in service.events().list(
                calendarId=cal["id"], timeMin=start, timeMax=end,
                singleEvents=True, orderBy="startTime",
            ).execute().get("items", []):
                event["_cal"] = cal.get("summary", cal["id"])
                all_events.append(event)

        all_events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date", "")))

        if not all_events:
            return f"No events found for {date} ({email})."

        lines = [f"Schedule for {date} ({email}):"]
        for event in all_events:
            raw     = event["start"].get("dateTime", event["start"].get("date", ""))
            summary = event.get("summary", "Untitled event")
            cal     = event.get("_cal", "")
            try:
                time_str = datetime.fromisoformat(raw).strftime("%I:%M %p")
            except Exception:
                time_str = raw
            lines.append(f"  - {time_str}: {summary} [{cal}]")

        return "\n".join(lines)

    except Exception as e:
        return f"Could not fetch calendar: {e}"


# =========================================================
# CLI
# =========================================================

if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "today"

    if command == "get-email":
        email = load_current_email()
        print(json.dumps({"ok": email is not None, "email": email}, ensure_ascii=False))

    elif command == "connect":
        try:
            _, email = run_oauth_flow()
            print(json.dumps({"ok": True, "email": email}, ensure_ascii=False))
        except Exception as e:
            print(json.dumps({"ok": False, "email": None, "error": str(e)}, ensure_ascii=False))

    else:
        print(get_schedule(date=command))