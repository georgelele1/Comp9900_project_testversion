from __future__ import annotations

import concurrent.futures
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from connectonion.address import load
from connectonion import Agent, host, transcribe

BASE_DIR = Path(__file__).resolve().parent
CO_DIR   = BASE_DIR / ".co"
APP_NAME = "Whispr"

PROFILE_FILE    = "profile.json"
DICTIONARY_FILE = "dictionary.json"
HISTORY_FILE    = "history.json"

# ── Self-correction ───────────────────────────────────────
SCORE_THRESHOLD = 70
MAX_RETRIES     = 3

# ── Dictionary auto-update ────────────────────────────────
DICTIONARY_UPDATE_INTERVAL = 60 * 60 * 24  # 24 hours

# ── Supported output languages ────────────────────────────
SUPPORTED_LANGUAGES = [
    "English", "Chinese", "Spanish", "French",
    "Japanese", "Korean", "Arabic", "German", "Portuguese",
]
DEFAULT_LANGUAGE = "English"

# ── Intent types ─────────────────────────────────────────
# "text"     → normal transcription, run full refine pipeline
# "calendar" → user wants their schedule, skip refine
# "snippet"  → user wants a static snippet, skip refine
INTENT_TYPES = {"text", "calendar", "snippet"}


# =========================================================
# Paths / storage
# =========================================================

def app_support_dir() -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support" / APP_NAME
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(home))) / APP_NAME
    else:
        base = home / ".local" / "share" / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def storage_path(filename: str) -> Path:
    return app_support_dir() / filename


def now_ms() -> int:
    return int(time.time() * 1000)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_store(filename: str, default: Any) -> Any:
    return read_json(storage_path(filename), default)


def save_store(filename: str, data: Any) -> None:
    write_json(storage_path(filename), data)


# =========================================================
# Defaults
# =========================================================

def default_profile() -> Dict[str, Any]:
    return {
        "name": "", "email": "", "organization": "", "role": "",
        "preferences": {"target_language": DEFAULT_LANGUAGE},
    }


def default_dictionary() -> Dict[str, Any]:
    return {"terms": []}


def default_history() -> Dict[str, Any]:
    return {"items": []}


def load_profile() -> Dict[str, Any]:
    return load_store(PROFILE_FILE, default_profile())


def save_profile(profile: Dict[str, Any]) -> None:
    save_store(PROFILE_FILE, profile)


def load_dictionary() -> Dict[str, Any]:
    return load_store(DICTIONARY_FILE, default_dictionary())


def load_history() -> Dict[str, Any]:
    return load_store(HISTORY_FILE, default_history())


def append_history(item: Dict[str, Any], max_items: int = 200) -> None:
    data  = load_history()
    items = data.get("items", [])
    items.append(item)
    data["items"] = items[-max_items:]
    save_store(HISTORY_FILE, data)


def get_target_language() -> str:
    profile = load_profile()
    lang = profile.get("preferences", {}).get("target_language", DEFAULT_LANGUAGE)
    return lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def set_target_language(language: str) -> bool:
    if language not in SUPPORTED_LANGUAGES:
        return False
    profile = load_profile()
    profile.setdefault("preferences", {})["target_language"] = language
    save_profile(profile)
    return True


# =========================================================
# Common helpers
# =========================================================

def clean_agent_output(result: Any) -> str:
    return str(result).strip().strip('"').strip("'").strip()


def register_tool(agent: Agent, fn: Callable[..., Any]) -> None:
    if hasattr(agent, "add_tools") and callable(getattr(agent, "add_tools")):
        agent.add_tools(fn)
        return
    if hasattr(agent, "add_tool") and callable(getattr(agent, "add_tool")):
        agent.add_tool(fn)
        return
    reg = getattr(agent, "tools", None)
    if reg is not None:
        for meth in ("register", "add", "add_tool", "add_function", "append"):
            m = getattr(reg, meth, None)
            if callable(m):
                m(fn)
                return
    raise RuntimeError("Cannot register tool: unknown connectonion tool API.")


# =========================================================
# Dictionary corrections  (pure regex — 0ms)
# =========================================================

def apply_dictionary_corrections(text: str) -> str:
    if not text.strip():
        return text
    result = text
    for item in load_dictionary().get("terms", []):
        if not item.get("approved", True):
            continue
        phrase = str(item.get("phrase", "")).strip()
        if not phrase:
            continue
        for alias in item.get("aliases", []):
            alias = str(alias).strip()
            if alias:
                result = re.sub(
                    rf"\b{re.escape(alias)}\b", phrase, result, flags=re.IGNORECASE
                )
    return result


# =========================================================
# Dictionary auto-update helpers
# =========================================================

def should_update_dictionary() -> bool:
    path = storage_path("dictionary_last_update.json")
    if not path.exists():
        return True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return (time.time() - data.get("last_update", 0)) > DICTIONARY_UPDATE_INTERVAL
    except Exception:
        return True


def mark_dictionary_updated() -> None:
    storage_path("dictionary_last_update.json").write_text(
        json.dumps({"last_update": time.time()}), encoding="utf-8"
    )


def get_new_history_since_last_update() -> List[Dict[str, Any]]:
    path = storage_path("dictionary_last_update.json")
    last_ts = 0.0
    if path.exists():
        try:
            last_ts = json.loads(path.read_text(encoding="utf-8")).get("last_update", 0.0)
        except Exception:
            pass
    return [
        item for item in load_history().get("items", [])
        if item.get("ts", 0) / 1000 > last_ts
    ]


def get_optimal_sample_size(items: List[Any]) -> int:
    total = len(items)
    if total == 0:   return 0
    if total < 20:   return total
    if total < 100:  return max(20, total // 3)
    return max(40, total // 5)


def deduplicate_items(texts: List[str], threshold: int = 10) -> List[str]:
    seen, unique = set(), []
    for text in texts:
        fp = " ".join(text.lower().split()[:threshold])
        if fp not in seen:
            seen.add(fp)
            unique.append(text)
    return unique


def prepare_items_for_agent(items: List[Dict[str, Any]]) -> List[str]:
    texts = [
        str(item.get("final_text", "")).strip()
        for item in items
        if str(item.get("final_text", "")).strip()
    ]
    return deduplicate_items(texts)


# =========================================================
# FAST PATH: Intent detection  (~1.5s, runs in parallel)
#
# Detects early whether the raw transcribed text is:
#   "text"     → normal dictation, needs refine
#   "calendar" → user wants schedule, skip refine
#   "snippet"  → user wants a snippet, skip refine
#
# Uses a minimal prompt to keep latency low.
# Runs concurrently with ai_refine_text so neither blocks the other.
# =========================================================

def detect_intent(raw_text: str, snippet_triggers: List[str]) -> Dict[str, Any]:
    """Detect whether the text is a command or normal dictation.

    Returns:
        {
            "type":     "text" | "calendar" | "snippet",
            "trigger":  str | None,   # matched snippet trigger if type=snippet
            "date":     str | None,   # extracted date if type=calendar
            "calendar": str | None,   # calendar name if type=calendar
        }
    """
    triggers_hint = (
        f"Known snippet triggers: {json.dumps(snippet_triggers)}. "
        if snippet_triggers else ""
    )

    agent = Agent(
        model="gpt-5",
        name="whispr_intent_detector",
        system_prompt=(
            "You are a fast intent classifier for a voice transcription app. "
            "Classify the input as ONE of: 'text', 'calendar', or 'snippet'. "
            "'calendar' = user asks for schedule/events/calendar. "
            "'snippet' = user requests a known shortcut/snippet by name. "
            "'text' = everything else (normal dictation). "
            f"{triggers_hint}"
            "Reply ONLY with compact JSON — no explanation:\n"
            '{"type":"text|calendar|snippet",'
            '"trigger":null_or_trigger_name,'
            '"date":"today|tomorrow|YYYY-MM-DD|null",'
            '"calendar":"name|all|null"}'
        ),
    )

    try:
        result = json.loads(str(agent.input(raw_text)).strip())
        if result.get("type") not in INTENT_TYPES:
            result["type"] = "text"
        return result
    except Exception:
        return {"type": "text", "trigger": None, "date": None, "calendar": None}


# =========================================================
# AI refine  (runs in parallel with intent detection)
# =========================================================

def ai_refine_text(
    text: str,
    app_name: str = "",
    target_language: str = "",
) -> str:
    """Refine + translate transcribed text.

    Always pass app_name (even 'unknown') — halves latency vs empty string.
    """
    if not text.strip():
        return text

    lang = target_language.strip()
    if not lang or lang not in SUPPORTED_LANGUAGES:
        lang = get_target_language()

    app_hint = (
        f"The user is currently using {app_name.strip()}."
        if app_name.strip()
        else "The active application is unknown."
    )

    agent = Agent(
        model="gpt-5",
        name="whispr_text_refiner",
        system_prompt=(
            "You are Whispr's text refinement agent.\n"
            f"{app_hint} "
            "Use that to infer appropriate tone and context.\n\n"
            "Steps:\n"
            f"1. If input is NOT {lang}, translate it to {lang}.\n"
            "2. Remove stutters, false starts, repeated words, disfluencies.\n"
            "3. Fix punctuation, capitalisation, grammar.\n"
            "4. Match tone to the application context.\n\n"
            "Output ONLY the final refined text — nothing else."
        ),
    )

    return clean_agent_output(agent.input(
        f"Input text:\n{text}\n\nOutput only the final refined {lang} text."
    ))


# =========================================================
# Self-correction
# =========================================================

def self_correct_text(
    raw_text: str,
    initial_refined: str,
    app_name: str = "",
    target_language: str = "",
) -> str:
    try:
        from Eval_run import run_refinement_eval
    except ImportError:
        return initial_refined

    current    = initial_refined
    best_text  = initial_refined
    best_score = 0

    for attempt in range(MAX_RETRIES):
        results = run_refinement_eval([{
            "raw_text": raw_text, "final_text": current, "app_name": app_name,
        }], verbose=False)

        if not results:
            break

        score  = results[0]["score"]
        reason = results[0]["reason"]

        if score > best_score:
            best_score = score
            best_text  = current

        print(f"[self-correct] attempt {attempt + 1}  score={score}/100", file=sys.stderr)

        if score >= SCORE_THRESHOLD:
            break

        lang  = target_language.strip() or get_target_language()
        agent = Agent(
            model="gpt-5",
            name="whispr_self_corrector",
            system_prompt=(
                "Fix the issues in the previous refinement attempt. "
                f"Output ONLY the corrected {lang} text. "
                "Do NOT add facts or change meaning."
            ),
        )
        current = clean_agent_output(agent.input(
            f"App: {app_name or 'unknown'}\n"
            f"Raw:\n{raw_text}\n\n"
            f"Previous attempt:\n{current}\n\n"
            f"Feedback:\n{reason}\n\n"
            "Output corrected text only."
        ))

    return best_text


# =========================================================
# Transcribe helper
# =========================================================

def transcribe_audio(audio_path: str) -> str:
    return str(transcribe(audio_path)).strip()


# =========================================================
# Core pipeline  — optimised with parallel intent detection
#
# Flow:
#   1. transcribe (blocking — must finish first)
#   2. load snippet triggers (instant — local file read)
#   3. PARALLEL:
#        a. detect_intent(raw_text)      ~1.5s
#        b. ai_refine_text(raw_text)     ~4s
#   4. Route on intent result:
#        - "calendar" → fetch schedule (skip refine output)
#        - "snippet"  → expand snippet  (skip refine output)
#        - "text"     → use refine output → dictionary corrections
#
# Because intent detection (~1.5s) finishes before refine (~4s),
# we can cancel or ignore refine early for command intents.
# =========================================================

def _load_snippet_triggers() -> List[str]:
    """Load enabled snippet triggers — instant local read."""
    try:
        from snippets import load_snippets
        data = load_snippets()
        return [
            item["trigger"]
            for item in data.get("snippets", [])
            if item.get("enabled", True) and str(item.get("trigger", "")).strip()
        ]
    except Exception:
        return []


def transcribe_and_enhance_impl(
    audio_path: str,
    app_name: str = "",
    target_language: str = "",
) -> Dict[str, Any]:
    """Optimised pipeline with parallel intent detection."""

    audio_path = str(Path(audio_path).expanduser())
    if not Path(audio_path).exists():
        return {"ok": False, "error": f"audio file not found: {audio_path}", "ts": now_ms()}

    # Step 1 — transcribe (must complete before anything else)
    t0 = time.perf_counter()
    raw_text = transcribe_audio(audio_path)
    print(f"[pipeline] transcribe: {(time.perf_counter()-t0)*1000:.0f}ms", file=sys.stderr)

    if not raw_text.strip():
        return {"ok": False, "error": "transcription returned empty text", "ts": now_ms()}

    effective_app = app_name.strip() or "unknown"

    # Step 2 — load snippet triggers (instant)
    snippet_triggers = _load_snippet_triggers()

    # Step 3 — run intent detection AND refine IN PARALLEL
    # Both start at the same time. Intent (~1.5s) finishes first.
    # If intent is a command we use its result and discard refine.
    # If intent is "text" we wait for refine to finish (~4s total, not 5.5s).
    final_text = raw_text  # safe fallback

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            intent_future = executor.submit(detect_intent, raw_text, snippet_triggers)
            refine_future = executor.submit(
                ai_refine_text, raw_text, effective_app, target_language
            )

            # Intent finishes first (~1.5s) — route immediately
            intent = intent_future.result()
            intent_type = intent.get("type", "text")

            print(f"[pipeline] intent={intent_type}", file=sys.stderr)

            if intent_type == "calendar":
                # Skip refine — fetch calendar directly
                refine_future.cancel()
                try:
                    from gcalendar import get_schedule
                    import getpass
                    date     = intent.get("date") or "today"
                    cal_filt = intent.get("calendar") or "all"
                    final_text = get_schedule(
                        date=date,
                        user_id=getpass.getuser(),
                        calendar_filter=cal_filt,
                    )
                except Exception as e:
                    final_text = f"Could not fetch calendar: {e}"

            elif intent_type == "snippet":
                # Skip refine — expand snippet directly
                refine_future.cancel()
                trigger = intent.get("trigger")
                try:
                    from snippets import load_snippets, handle_dynamic_trigger
                    from snippets import DYNAMIC_TRIGGERS
                    data     = load_snippets()
                    snippets = {
                        item["trigger"]: item["expansion"]
                        for item in data.get("snippets", [])
                        if item.get("enabled", True)
                    }
                    if trigger and trigger in snippets:
                        if trigger.lower() in DYNAMIC_TRIGGERS:
                            final_text = handle_dynamic_trigger(trigger, raw_text)
                        else:
                            final_text = snippets[trigger]
                    else:
                        # Trigger not found — fall back to refine
                        final_text = apply_dictionary_corrections(refine_future.result())
                except Exception:
                    final_text = apply_dictionary_corrections(refine_future.result())

            else:
                # Normal text — wait for refine (already running in parallel)
                refined    = refine_future.result()
                corrected  = self_correct_text(raw_text, refined, effective_app, target_language)
                final_text = apply_dictionary_corrections(corrected)

    except Exception as exc:
        print(f"[pipeline] error — falling back to raw: {exc}", file=sys.stderr)
        final_text = apply_dictionary_corrections(raw_text)

    append_history({
        "ts":              now_ms(),
        "audio_path":      audio_path,
        "raw_text":        raw_text,
        "final_text":      final_text,
        "app_name":        effective_app,
        "target_language": target_language or get_target_language(),
    })

    return {"ok": True, "raw_text": raw_text, "final_text": final_text, "ts": now_ms()}


# =========================================================
# Tool functions
# =========================================================

def create_or_update_profile(
    name: str = "", email: str = "",
    organization: str = "", role: str = "",
    target_language: str = "",
) -> Dict[str, Any]:
    profile = load_profile()
    for key, value in {
        "name": name, "email": email,
        "organization": organization, "role": role,
    }.items():
        if str(value).strip():
            profile[key] = str(value).strip()
    if target_language.strip() in SUPPORTED_LANGUAGES:
        profile.setdefault("preferences", {})["target_language"] = target_language.strip()
    save_profile(profile)
    return {"ok": True, "profile": profile}


def get_profile() -> Dict[str, Any]:
    return {"ok": True, "profile": load_profile()}


def transcribe_and_enhance(
    audio_path: str,
    app_name: str = "",
    target_language: str = "",
) -> Dict[str, Any]:
    return transcribe_and_enhance_impl(
        audio_path=audio_path,
        app_name=app_name,
        target_language=target_language,
    )


# =========================================================
# Agent factory
# =========================================================

def create_agent() -> Agent:
    agent = Agent(
        model="gpt-5",
        name="whispr_orchestrator",
        system_prompt=(
            "You are Whispr. You orchestrate audio transcription, "
            "text refinement, and translation."
        ),
    )
    for fn in (create_or_update_profile, get_profile, transcribe_and_enhance):
        register_tool(agent, fn)
    return agent


# =========================================================
# CLI / host
# =========================================================

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "cli":

        if len(sys.argv) < 3:
            print(json.dumps({"output": ""}, ensure_ascii=False))
            sys.exit(1)

        command = sys.argv[2]

        # ── transcribe ──────────────────────────────────
        if command == "transcribe":
            audio_path      = sys.argv[3] if len(sys.argv) > 3 else ""
            app_name        = sys.argv[4] if len(sys.argv) > 4 else "unknown"
            target_language = sys.argv[5] if len(sys.argv) > 5 else ""

            print(f"PYTHON RECEIVED PATH: {audio_path}", file=sys.stderr)
            print(f"FILE EXISTS: {os.path.exists(audio_path)}", file=sys.stderr)
            print(f"TARGET LANGUAGE: {target_language or get_target_language()}", file=sys.stderr)

            try:
                result = transcribe_and_enhance_impl(
                    audio_path=audio_path,
                    app_name=app_name,
                    target_language=target_language,
                )
                print(json.dumps({"output": result.get("final_text", "")}, ensure_ascii=False))
                sys.exit(0)
            except Exception as e:
                print(json.dumps({"output": ""}))
                print(f"ERROR: {str(e)}", file=sys.stderr)
                sys.exit(1)

        # ── calendar ────────────────────────────────────
        elif command == "calendar":
            import getpass
            text    = sys.argv[3] if len(sys.argv) > 3 else "today"
            user_id = sys.argv[4] if len(sys.argv) > 4 else getpass.getuser()
            try:
                from gcalendar import get_schedule, extract_calendar_intent
                intent   = extract_calendar_intent(text)
                schedule = get_schedule(
                    date=intent.get("date", "today"),
                    user_id=user_id,
                    calendar_filter=intent.get("calendar", "all"),
                )
                print(json.dumps({"output": schedule}, ensure_ascii=False))
                sys.exit(0)
            except Exception as e:
                print(json.dumps({"output": ""}))
                print(f"ERROR: {str(e)}", file=sys.stderr)
                sys.exit(1)

        # ── set-language ─────────────────────────────────
        elif command == "set-language":
            language = sys.argv[3] if len(sys.argv) > 3 else ""
            ok = set_target_language(language)
            print(json.dumps({
                "ok": ok,
                "language": language,
                "error": f"unsupported: {language}" if not ok else None,
                "supported": SUPPORTED_LANGUAGES,
            }, ensure_ascii=False))
            sys.exit(0 if ok else 1)

        # ── get-language ─────────────────────────────────
        elif command == "get-language":
            print(json.dumps({
                "ok": True,
                "language": get_target_language(),
                "supported": SUPPORTED_LANGUAGES,
            }, ensure_ascii=False))
            sys.exit(0)

        # ── legacy: direct audio path as argv[2] ─────────
        else:
            audio_path      = sys.argv[2]
            app_name        = sys.argv[3] if len(sys.argv) > 3 else "unknown"
            target_language = sys.argv[4] if len(sys.argv) > 4 else ""

            print(f"PYTHON RECEIVED PATH: {audio_path}", file=sys.stderr)
            print(f"FILE EXISTS: {os.path.exists(audio_path)}", file=sys.stderr)

            try:
                result = transcribe_and_enhance_impl(
                    audio_path=audio_path,
                    app_name=app_name,
                    target_language=target_language,
                )
                print(json.dumps({"output": result.get("final_text", "")}, ensure_ascii=False))
                sys.exit(0)
            except Exception as e:
                print(json.dumps({"output": ""}))
                print(f"ERROR: {str(e)}", file=sys.stderr)
                sys.exit(1)

    else:
        addr = load(CO_DIR)
        host(
            create_agent,
            relay_url=None,
            whitelist=[addr["address"]],
            blacklist=[],
        )