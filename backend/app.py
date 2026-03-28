from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from connectonion.address import load
from connectonion import Agent, host, transcribe

BASE_DIR = Path(__file__).resolve().parent
CO_DIR = BASE_DIR / ".co"
APP_NAME = "Whispr"

PROFILE_FILE = "profile.json"
DICTIONARY_FILE = "dictionary.json"
HISTORY_FILE = "history.json"

# Self-correction settings
SCORE_THRESHOLD = 70
MAX_RETRIES = 3

# Dictionary auto-update settings
DICTIONARY_UPDATE_INTERVAL = 60 * 60 * 24  # 24 hours in seconds


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
        "name": "Yanbo",
        "email": "z5603812@unsw.edu.au",
        "organization": "UNSW",
        "role": "Student",
        "preferences": {},
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
    data = load_history()
    items = data.get("items", [])
    items.append(item)
    data["items"] = items[-max_items:]
    save_store(HISTORY_FILE, data)


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

    raise RuntimeError("Cannot register tool: unknown connectonion tool API in this install.")


# =========================================================
# Dictionary corrections
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
                result = re.sub(rf"\b{re.escape(alias)}\b", phrase, result, flags=re.IGNORECASE)

    return result


# =========================================================
# Dictionary auto-update helpers
# =========================================================

def should_update_dictionary() -> bool:
    """Returns True if enough time has passed since last dictionary update."""
    path = storage_path("dictionary_last_update.json")
    if not path.exists():
        return True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        last = data.get("last_update", 0)
        return (time.time() - last) > DICTIONARY_UPDATE_INTERVAL
    except Exception:
        return True


def mark_dictionary_updated() -> None:
    """Save current timestamp as last dictionary update time."""
    path = storage_path("dictionary_last_update.json")
    path.write_text(
        json.dumps({"last_update": time.time()}),
        encoding="utf-8"
    )


def get_new_history_since_last_update() -> List[Dict[str, Any]]:
    """Return only history items added since the last dictionary update."""
    path = storage_path("dictionary_last_update.json")

    last_update_ts = 0
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            last_update_ts = data.get("last_update", 0)
        except Exception:
            pass

    history = load_history()
    items = history.get("items", [])

    # ts is stored in ms, last_update_ts is in seconds
    new_items = [
        item for item in items
        if item.get("ts", 0) / 1000 > last_update_ts
    ]

    return new_items


def get_optimal_sample_size(items: List[Any]) -> int:
    """Dynamically decide how many new items to sample to minimise token usage."""
    total = len(items)

    if total == 0:
        return 0
    elif total < 20:
        return total                    # use all if small
    elif total < 100:
        return max(20, total // 3)      # 33% sample
    else:
        return max(40, total // 5)      # 20% sample


def deduplicate_items(texts: List[str], threshold: int = 10) -> List[str]:
    """Remove near-duplicate texts using a word fingerprint to save tokens."""
    seen = set()
    unique = []

    for text in texts:
        fingerprint = " ".join(text.lower().split()[:threshold])
        if fingerprint not in seen:
            seen.add(fingerprint)
            unique.append(text)

    return unique


def prepare_items_for_agent(items: List[Dict[str, Any]]) -> List[str]:
    """Strip unnecessary fields and deduplicate before sending to agent.

    Only sends final_text — skips raw_text, audio_path, ts, app_name
    to minimise token usage by ~60%.
    """
    texts = [
        str(item.get("final_text", "")).strip()
        for item in items
        if str(item.get("final_text", "")).strip()
    ]
    return deduplicate_items(texts)


# =========================================================
# AI refine
# =========================================================

def ai_refine_text(text: str, app_name: str = "") -> str:
    if not text.strip():
        return text

    app_hint = f"The user is currently using {app_name.strip()}." if app_name.strip() else ""

    agent = Agent(
        model="gpt-5",
        name="whispr_text_refiner",
        system_prompt=(
            "You are Whispr's text refinement agent.\n"
            "You will be told which application the user is currently using. "
            "Use that to infer the appropriate tone, formality, and context for the output "
            "(e.g. code-safe for an IDE, professional for email, casual for chat).\n"
            "Your job is to remove false starts, repeated fragments, self-corrections, "
            "stutters, and spoken disfluencies, then improve punctuation, capitalization, "
            "grammar, clarity, and readability to match that context.\n"
            "Rules:\n"
            "- Do NOT add new facts.\n"
            "- Do NOT change meaning.\n"
            "- Output ONLY the final refined text.\n"
        )
    )

    instruction = f"""
{app_hint}

Input text:
{text}

Infer the appropriate tone and context from the application, then refine the text accordingly.
Output only the final refined text.
""".strip()

    return clean_agent_output(agent.input(instruction))


# =========================================================
# Self-correction
# =========================================================

def self_correct_text(
    raw_text: str,
    initial_refined: str,
    app_name: str = "",
) -> str:
    """Evaluate refined text and retry with eval feedback if score is too low.

    Uses the eval runner to score the refinement. If below SCORE_THRESHOLD,
    feeds the reason back into a correction agent and retries up to MAX_RETRIES.
    Always returns the best scoring attempt.
    """
    try:
        from Eval_run import run_refinement_eval, score_evaluation
    except ImportError:
        # Eval runner not available — return as-is
        return initial_refined

    current = initial_refined
    best_text = initial_refined
    best_score = 0

    for attempt in range(MAX_RETRIES):
        results = run_refinement_eval([{
            "raw_text": raw_text,
            "final_text": current,
            "app_name": app_name,
        }], verbose=False)

        if not results:
            break

        passed = results[0]["passed"]
        score = results[0]["score"]
        reason = results[0]["reason"]

        # Track best attempt
        if score > best_score:
            best_score = score
            best_text = current

        print(f"[self-correct] attempt {attempt + 1} score={score}/100", file=sys.stderr)

        # Pass threshold — done
        if score >= SCORE_THRESHOLD:
            break

        # Fail — retry with reason fed back into corrector agent
        print(f"[self-correct] score below {SCORE_THRESHOLD}, retrying...", file=sys.stderr)

        agent = Agent(
            model="gpt-5",
            name="whispr_self_corrector",
            system_prompt=(
                "You are Whispr's self-correction agent. "
                "You will receive a previous refinement attempt and the reason it failed evaluation. "
                "Fix only the issues identified and output ONLY the corrected text. "
                "Do NOT add new facts or change the core meaning."
            )
        )

        current = clean_agent_output(agent.input(
            f"App context: {app_name or 'unknown'}\n\n"
            f"Original raw text:\n{raw_text}\n\n"
            f"Previous refinement attempt:\n{current}\n\n"
            f"Evaluation feedback:\n{reason}\n\n"
            f"Output only the corrected text."
        ))

    return best_text


# =========================================================
# Transcribe helper
# =========================================================

def transcribe_audio(audio_path: str) -> str:
    """Transcribe an audio file to text."""
    return str(transcribe(audio_path)).strip()


# =========================================================
# Core
# =========================================================

def transcribe_and_enhance_impl(
    audio_path: str,
    app_name: str = "",
) -> Dict[str, Any]:
    audio_path = str(Path(audio_path).expanduser())

    if not Path(audio_path).exists():
        return {
            "ok": False,
            "error": f"audio file not found: {audio_path}",
            "ts": now_ms(),
        }

    raw_text = transcribe_audio(audio_path)

    try:
        # Step 1: AI refine
        initial_refined = ai_refine_text(text=raw_text, app_name=app_name)

        # Step 2: Self-correct based on eval score
        corrected_text = self_correct_text(raw_text, initial_refined, app_name)

        # Step 3: Apply dictionary corrections
        refined_text = apply_dictionary_corrections(corrected_text)

        # Step 4: Apply snippets
        from snippets import apply_snippets
        final_text = apply_snippets(refined_text)

    except Exception:
        final_text = apply_dictionary_corrections(raw_text)

    append_history({
        "ts": now_ms(),
        "audio_path": audio_path,
        "raw_text": raw_text,
        "final_text": final_text,
        "app_name": app_name,
    })

    return {
        "ok": True,
        "raw_text": raw_text,
        "final_text": final_text,
        "ts": now_ms(),
    }


# =========================================================
# Tool functions
# =========================================================

def create_or_update_profile(
    name: str = "",
    email: str = "",
    organization: str = "",
    role: str = "",
) -> Dict[str, Any]:
    profile = load_profile()

    for key, value in {
        "name": name,
        "email": email,
        "organization": organization,
        "role": role,
    }.items():
        if str(value).strip():
            profile[key] = str(value).strip()

    save_profile(profile)
    return {"ok": True, "profile": profile}


def get_profile() -> Dict[str, Any]:
    return {"ok": True, "profile": load_profile()}


def transcribe_and_enhance(
    audio_path: str,
    app_name: str = "",
) -> Dict[str, Any]:
    return transcribe_and_enhance_impl(
        audio_path=audio_path,
        app_name=app_name,
    )


# =========================================================
# Agent factory
# =========================================================

def create_agent() -> Agent:
    agent = Agent(
        model="gpt-5",
        name="whispr_orchestrator",
        system_prompt=(
            "You are Whispr. You orchestrate audio transcription and text refinement."
        ),
    )

    for fn in (
        create_or_update_profile,
        get_profile,
        transcribe_and_enhance,
    ):
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

        # ── transcribe command ──
        if command == "transcribe":
            audio_path = sys.argv[3] if len(sys.argv) > 3 else ""
            app_name   = sys.argv[4] if len(sys.argv) > 4 else ""

            print(f"PYTHON RECEIVED PATH: {audio_path}", file=sys.stderr)
            print(f"FILE EXISTS: {os.path.exists(audio_path)}", file=sys.stderr)

            try:
                result = transcribe_and_enhance_impl(
                    audio_path=audio_path,
                    app_name=app_name,
                )
                print(json.dumps({
                    "output": result.get("final_text", "")
                }, ensure_ascii=False))
                sys.exit(0)

            except Exception as e:
                print(json.dumps({"output": ""}))
                print(f"ERROR: {str(e)}", file=sys.stderr)
                sys.exit(1)

        # ── calendar command ──
        elif command == "calendar":
            text    = sys.argv[3] if len(sys.argv) > 3 else "today"
            user_id = sys.argv[4] if len(sys.argv) > 4 else None

            try:
                from gcalendar import get_schedule, extract_date_from_text
                from auth import get_credentials
                import getpass
                uid = user_id or getpass.getuser()
                date = extract_date_from_text(text)
                schedule = get_schedule(date=date, user_id=uid)
                print(json.dumps({"output": schedule}, ensure_ascii=False))
                sys.exit(0)

            except Exception as e:
                print(json.dumps({"output": ""}))
                print(f"ERROR: {str(e)}", file=sys.stderr)
                sys.exit(1)

        # ── legacy: direct audio path as argv[2] (backwards compat) ──
        else:
            audio_path = sys.argv[2]
            app_name   = sys.argv[3] if len(sys.argv) > 3 else ""

            print(f"PYTHON RECEIVED PATH: {audio_path}", file=sys.stderr)
            print(f"FILE EXISTS: {os.path.exists(audio_path)}", file=sys.stderr)

            try:
                result = transcribe_and_enhance_impl(
                    audio_path=audio_path,
                    app_name=app_name,
                )
                print(json.dumps({
                    "output": result.get("final_text", "")
                }, ensure_ascii=False))
                sys.exit(0)

            except Exception as e:
                print(json.dumps({"output": ""}))
                print(f"ERROR: {str(e)}", file=sys.stderr)
                sys.exit(1)

    else:
        addr = load(CO_DIR)
        my_agent_address = addr["address"]

        host(
            create_agent,
            relay_url=None,
            whitelist=[my_agent_address],
            blacklist=[],
        )