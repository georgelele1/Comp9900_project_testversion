#!/usr/bin/env python3
"""
test_router.py — CLI test for the Whispr router and all plugins.

Drop this file anywhere inside the backend/ directory and run:

    python3 test_router.py

Or run a specific test by number:

    python3 test_router.py 3

Requirements: run from the backend/ directory, or from anywhere as long as
backend/ is on the path (the script self-bootstraps).
"""
from __future__ import annotations

import sys
import os
import time
from pathlib import Path

# ── Bootstrap: find backend root the same way _pathfix.py does ────────────────
def _find_backend_root(start: str) -> str | None:
    current = Path(start).resolve()
    if current.is_file():
        current = current.parent
    for _ in range(6):
        if (current / "app.py").exists() and (current / "storage.py").exists():
            return str(current)
        current = current.parent
    return None

_root = _find_backend_root(__file__)
if not _root:
    print("ERROR: Could not find backend root (app.py + storage.py).")
    print("       Run this script from inside the backend/ directory.")
    sys.exit(1)

if _root not in sys.path:
    sys.path.insert(0, _root)

print(f"[boot] backend root: {_root}")

# ── Now safe to import ─────────────────────────────────────────────────────────
try:
    from storage import get_target_language, load_dictionary, load_profile
    print(f"[boot] storage OK — language: {get_target_language()}")
except Exception as e:
    print(f"ERROR importing storage: {e}")
    sys.exit(1)

try:
    from agents.router import route, _load_snippet_triggers, quick_clean
    print("[boot] router OK")
except Exception as e:
    print(f"ERROR importing router: {e}")
    sys.exit(1)

try:
    from agents.profile import get_user_context
    user_context = get_user_context()
    print(f"[boot] profile OK — context: {user_context[:60]!r}{'...' if len(user_context) > 60 else ''}")
except Exception as e:
    print(f"WARNING: profile failed ({e}) — using empty context")
    user_context = ""

# ── Test cases ─────────────────────────────────────────────────────────────────
# Each entry: (description, input_text, expected_plugin_or_path)
TESTS = [
    # Knowledge plugin
    ("Newton law",            "what is Newton's second law of motion",     "knowledge"),
    ("Formula request",       "give me the formula for kinetic energy",    "knowledge"),
    ("Definition",            "define photosynthesis",                     "knowledge"),
    ("Explain concept",       "explain how TCP/IP works",                  "knowledge"),
    ("Math",                  "what is the Pythagorean theorem",           "knowledge"),

    # Calendar plugin
    ("Calendar today",        "show me my schedule for today",             "calendar"),
    ("Calendar tomorrow",     "what do I have tomorrow",                   "calendar"),
    ("Calendar search",       "when is my COMP9900 exam",                  "calendar"),

    # Refiner path (no plugin match → None from router)
    ("Plain dictation",       "the meeting is at three pm on Friday",      "refiner"),
    ("Short sentence",        "send the report to the team",               "refiner"),

    # Snippets (only works if you have snippets saved)
    ("Snippet trigger",       "give me my zoom link",                      "snippets"),
]

# ── Colour helpers ─────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def ok(msg):  print(f"  {GREEN}✓{RESET} {msg}")
def fail(msg): print(f"  {RED}✗{RESET} {msg}")
def info(msg): print(f"  {CYAN}→{RESET} {msg}")

# ── Runner ─────────────────────────────────────────────────────────────────────
def run_test(idx: int, description: str, text: str, expected: str) -> bool:
    print(f"\n{BOLD}[{idx+1}] {description}{RESET}")
    print(f"  Input : {text!r}")

    snippet_triggers = _load_snippet_triggers()
    clean            = quick_clean(text)
    lang             = get_target_language()

    print(f"  Clean : {clean!r}")
    print(f"  Lang  : {lang}")
    if snippet_triggers:
        print(f"  Snippets loaded: {snippet_triggers}")

    t0 = time.perf_counter()
    try:
        result = route(
            raw_text         = text,
            clean_text       = clean,
            snippet_triggers = snippet_triggers,
            app_name         = "Terminal",
            target_language  = lang,
            user_context     = user_context,
            effective_app    = "Terminal",
        )
    except Exception as e:
        fail(f"route() raised: {e}")
        import traceback; traceback.print_exc()
        return False

    elapsed = (time.perf_counter() - t0) * 1000

    if result is None:
        routed_to = "refiner"
        info(f"Router returned None → falls through to refiner  ({elapsed:.0f}ms)")
    else:
        routed_to = "plugin"
        info(f"Output ({elapsed:.0f}ms):\n\n{result}\n")

    # Check expected path
    if expected == "refiner":
        if result is None:
            ok("Correctly fell through to refiner")
            return True
        else:
            fail(f"Expected refiner fallthrough, but a plugin returned output")
            return False
    else:
        if result is not None:
            ok(f"Plugin returned output (expected: {expected})")
            return True
        else:
            fail(f"Expected plugin '{expected}' to handle this, but got refiner fallthrough")
            return False


def run_path_check():
    """Diagnose whether _pathfix works correctly on this machine."""
    print(f"\n{BOLD}=== Path & import diagnostics ==={RESET}")
    print(f"  Python      : {sys.executable}")
    print(f"  sys.path[0] : {sys.path[0]}")
    print(f"  backend root: {_root}")

    checks = [
        ("storage",                  "from storage import load_profile"),
        ("agents.router",            "from agents.router import route"),
        ("agents._pathfix",          "from agents._pathfix import ensure_backend_on_path"),
        ("agents.plugins.knowledge", "from agents.plugins.knowledge import plugin"),
        ("agents.plugins.calendar",  "from agents.plugins.calendar import plugin"),
        ("agents.plugins.snippets",  "from agents.plugins.snippets_plugin import plugin"),
        ("connectonion",             "from connectonion import Agent"),
    ]

    all_ok = True
    for name, stmt in checks:
        try:
            exec(stmt)
            ok(name)
        except Exception as e:
            fail(f"{name}  →  {e}")
            all_ok = False

    # Dictionary and profile summary
    terms = load_dictionary().get("terms", [])
    prof  = load_profile()
    print(f"\n  Dictionary terms : {len(terms)}")
    print(f"  Profile name     : {prof.get('name') or '(not set)'}")
    print(f"  Target language  : {get_target_language()}")
    print(f"  Snippets loaded  : {_load_snippet_triggers()}")
    return all_ok


# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    specific = int(sys.argv[1]) - 1 if len(sys.argv) > 1 and sys.argv[1].isdigit() else None

    print(f"\n{BOLD}{'='*55}{RESET}")
    print(f"{BOLD}  Whispr Router Test{RESET}")
    print(f"{BOLD}{'='*55}{RESET}")

    # Always run path diagnostics first
    imports_ok = run_path_check()
    if not imports_ok:
        print(f"\n{RED}Import errors detected above. Fix these before running route tests.{RESET}")
        sys.exit(1)

    print(f"\n{BOLD}=== Route tests ==={RESET}")

    tests_to_run = [TESTS[specific]] if specific is not None else TESTS
    offset       = specific if specific is not None else 0

    passed = failed = 0
    for i, (desc, text, expected) in enumerate(tests_to_run):
        success = run_test(offset + i, desc, text, expected)
        if success: passed += 1
        else:       failed += 1

    print(f"\n{BOLD}{'='*55}{RESET}")
    total = passed + failed
    colour = GREEN if failed == 0 else RED
    print(f"{colour}{BOLD}  {passed}/{total} passed{RESET}")
    if failed:
        print(f"  {YELLOW}Run a failing test alone:  python3 test_router.py <number>{RESET}")
    print(f"{BOLD}{'='*55}{RESET}\n")
    sys.exit(0 if failed == 0 else 1)