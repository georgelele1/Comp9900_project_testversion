from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List

from connectonion.address import load
from connectonion import Agent, host, transcribe

BASE_DIR = Path(__file__).resolve().parent
CO_DIR = BASE_DIR / ".co"
APP_NAME = "Whispr"

PROFILE_FILE = "profile.json"
DICTIONARY_FILE = "dictionary.json"
HISTORY_FILE = "history.json"

ALLOWED_MODES = {"off", "clean", "formal", "chat", "concise", "meeting", "email", "code"}
ALLOWED_CONTEXTS = {"generic", "email", "chat", "code"}

# Run dictionary auto-update only once every N transcriptions
DICTIONARY_UPDATE_EVERY = 10

# =========================================================
# Stopwords: NLTK first, fallback second
# =========================================================

FALLBACK_STOPWORDS = {
    "the", "and", "for", "are", "this", "that", "with", "have", "from",
    "you", "your", "was", "were", "will", "can", "not", "but", "they",
    "about", "just", "into", "then", "than", "when", "what", "where",
    "how", "why", "our", "their", "his", "her", "she", "him", "them",
    "hello", "okay", "yeah", "like", "um", "uh", "so", "well", "i",
    "we", "he", "it", "is", "am", "be", "to", "of", "in", "on", "at",
    "a", "an", "or", "if", "as", "by", "do", "did", "does", "done",
    "me", "my", "mine", "ours", "yours", "theirs", "please", "thanks",
    "thank", "today", "tomorrow", "yesterday", "also", "really", "very"
}

try:
    from nltk.corpus import stopwords
    STOPWORDS = set(stopwords.words("english"))
except Exception:
    STOPWORDS = set(FALLBACK_STOPWORDS)

STOPWORDS.update({"um", "uh", "yeah", "okay", "hello", "please", "thanks", "thank"})

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
        "preferences": {
            "default_mode": "formal",
            "default_context": "generic",
        },
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


def save_dictionary(data: Dict[str, Any]) -> None:
    save_store(DICTIONARY_FILE, data)


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

def normalize_mode_context(mode: str = "clean", context: str = "generic") -> tuple[str, str]:
    mode = str(mode or "clean").strip().lower()
    context = str(context or "generic").strip().lower()

    if mode not in ALLOWED_MODES:
        mode = "clean"
    if context not in ALLOWED_CONTEXTS:
        context = "generic"

    implied_context = {
        "email": "email",
        "chat": "chat",
        "code": "code",
    }
    if context == "generic" and mode in implied_context:
        context = implied_context[mode]

    return mode, context


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
# Instructions
# =========================================================

def get_refine_instruction(mode: str) -> str:
    mode = str(mode or "clean").strip().lower()

    instructions = {
        "off": "Do not modify the transcript.",
        "clean": (
            "Remove false starts, repeated fragments, stutters, and obvious spoken disfluencies. "
            "Then improve punctuation, capitalization, grammar, and readability while staying close to the original wording."
        ),
        "formal": (
            "Remove false starts, repeated fragments, self-corrections, and spoken disfluencies. "
            "Then rewrite in a polished, professional, and grammatically correct style."
        ),
        "chat": (
            "Remove obvious false starts and repeated fragments, but keep the text natural and conversational. "
            "Then improve readability lightly without making it sound stiff."
        ),
        "concise": (
            "Remove false starts, repeated fragments, filler, and verbose spoken phrasing. "
            "Then make the text shorter, clearer, and more direct while preserving meaning."
        ),
        "meeting": (
            "Remove spoken disfluencies and improve structure so the text is easier to use for meeting notes or meeting follow-up."
        ),
        "email": (
            "Remove spoken disfluencies and shape the text into a clean, professional email-ready form."
        ),
        "code": (
            "Remove spoken disfluencies, but preserve technical terms, code snippets, commands, file paths, variable names, "
            "product names, and version strings exactly. Improve readability without corrupting technical content."
        ),
    }

    return instructions.get(mode, instructions["clean"])


def get_context_instruction(context: str) -> str:
    context = str(context or "generic").strip().lower()

    instructions = {
        "generic": "Use a neutral style suitable for general everyday text.",
        "email": "Make the text suitable for email communication.",
        "chat": "Make the text suitable for instant messaging or casual chat.",
        "code": "Be careful with technical terms, code syntax, commands, file paths, and variable names.",
    }

    return instructions.get(context, instructions["generic"])

# =========================================================
# Dictionary utilities
# =========================================================

def add_or_update_dictionary_entry(
    phrase: str,
    aliases: List[str] | None = None,
    entry_type: str = "custom",
    source: str = "user",
    confidence: float = 1.0,
    approved: bool = True,
) -> Dict[str, Any]:
    phrase = str(phrase or "").strip()
    if not phrase:
        return {"ok": False, "error": "phrase is required"}

    clean_aliases = sorted({
        str(a).strip()
        for a in (aliases or [])
        if str(a).strip() and str(a).strip().lower() != phrase.lower()
    })

    data = load_dictionary()
    terms = data.get("terms", [])

    for item in terms:
        if str(item.get("phrase", "")).lower() == phrase.lower():
            merged = set(str(x).strip() for x in item.get("aliases", []) if str(x).strip())
            merged.update(clean_aliases)
            item["aliases"] = sorted(merged)
            item["type"] = entry_type or item.get("type", "custom")
            item["source"] = source or item.get("source", "user")
            item["confidence"] = max(float(item.get("confidence", 0.0)), float(confidence))
            item["approved"] = bool(approved)
            save_dictionary(data)
            return {"ok": True, "updated": True, "entry": item}

    entry = {
        "phrase": phrase,
        "aliases": clean_aliases,
        "type": entry_type or "custom",
        "source": source or "user",
        "confidence": float(confidence),
        "approved": bool(approved),
    }
    terms.append(entry)
    data["terms"] = terms
    save_dictionary(data)
    return {"ok": True, "updated": False, "entry": entry}


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


def build_dictionary_prompt(user_prompt: str = "", max_terms: int = 50) -> str:
    profile = load_profile()
    dictionary = load_dictionary()

    hints: List[str] = []
    for key in ("name", "organization", "role"):
        value = str(profile.get(key, "")).strip()
        if value:
            hints.append(value)

    for item in dictionary.get("terms", []):
        if item.get("approved", True):
            phrase = str(item.get("phrase", "")).strip()
            if phrase:
                hints.append(phrase)

    deduped = list(dict.fromkeys(hints))[:max_terms]

    parts: List[str] = []
    if deduped:
        parts.append("Please pay attention to these names and domain-specific terms:")
        parts.append(", ".join(deduped))
    if str(user_prompt).strip():
        parts.append(str(user_prompt).strip())

    return "\n".join(parts).strip()


def build_dictionary_context(max_terms: int = 50) -> str:
    lines: List[str] = []
    for item in load_dictionary().get("terms", [])[:max_terms]:
        if not item.get("approved", True):
            continue

        phrase = str(item.get("phrase", "")).strip()
        aliases = [str(a).strip() for a in item.get("aliases", []) if str(a).strip()]
        entry_type = str(item.get("type", "custom")).strip()

        if not phrase:
            continue

        suffix = f" (type: {entry_type}" + (f"; aliases: {', '.join(aliases)}" if aliases else "") + ")"
        lines.append(f"- {phrase}{suffix}")

    return "Personal dictionary: none" if not lines else "Personal dictionary:\n" + "\n".join(lines)

# =========================================================
# Candidate extraction
# =========================================================

def get_recent_texts(limit: int = 10) -> List[str]:
    return [
        str(item.get("final_text", "")).strip()
        for item in load_history().get("items", [])[-limit:]
        if str(item.get("final_text", "")).strip()
    ]


def get_candidate_source_texts(current_raw_text: str, limit: int = 10) -> List[str]:
    texts = get_recent_texts(limit=max(0, limit - 1))
    current_raw_text = str(current_raw_text or "").strip()
    if current_raw_text:
        texts.append(current_raw_text)
    return texts[-limit:]


def tokenize_candidate_words(text: str) -> List[str]:
    return re.findall(r"[A-Za-z][A-Za-z0-9\-_]{2,}", text)


def looks_like_domain_term(word: str) -> bool:
    return (
        any(c.isdigit() for c in word)
        or "-" in word
        or "_" in word
        or word[:1].isupper()
        or sum(1 for c in word if c.isupper()) >= 2
    )


def collect_candidate_terms_from_recent_texts(texts: List[str], min_count: int = 2) -> List[Dict[str, Any]]:
    dictionary = load_dictionary()

    existing_phrases = {str(item.get("phrase", "")).lower() for item in dictionary.get("terms", [])}
    existing_aliases = {
        str(alias).lower()
        for item in dictionary.get("terms", [])
        for alias in item.get("aliases", [])
    }

    counter = Counter()
    original_forms: Dict[str, str] = {}
    support_score: Dict[str, int] = {}

    for text in texts:
        seen = set()
        for word in tokenize_candidate_words(text):
            lw = word.lower()
            if (
                lw in STOPWORDS
                or lw in existing_phrases
                or lw in existing_aliases
                or len(word) < 3
                or word.isdigit()
            ):
                continue

            counter[lw] += 1
            original_forms.setdefault(lw, word)

            if lw not in seen:
                support_score[lw] = support_score.get(lw, 0) + 1
                seen.add(lw)

    candidates = []
    for lw, count in counter.items():
        if count >= min_count:
            phrase = original_forms[lw]
            candidates.append({
                "phrase": phrase,
                "count": count,
                "support_texts": support_score.get(lw, 1),
                "domain_like": looks_like_domain_term(phrase),
            })

    candidates.sort(key=lambda x: (not x["domain_like"], -x["support_texts"], -x["count"], x["phrase"].lower()))
    return candidates


def extract_dictionary_candidates_with_agent(
    texts: List[str],
    pre_candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not texts:
        return []

    dictionary_agent = Agent(
        model="gpt-5",
        name="whispr_dictionary_builder",
        system_prompt=(
            "You extract personal dictionary candidates from recent transcripts.\n"
            "Return ONLY valid JSON in this format:\n"
            "{\"terms\": [{\"phrase\": \"...\", \"aliases\": [\"...\"], \"type\": \"technical\", \"confidence\": 0.9}]}\n"
            "Rules:\n"
            "- Do not invent facts.\n"
            "- Use only evidence from the transcript texts.\n"
            "- Prefer terms supported by repeated usage across recent texts.\n"
            "- Avoid common English words.\n"
            "- Prefer names, products, project names, organizations, and technical terms.\n"
            "- Output valid JSON only."
        )
    )

    prompt = f"""
Recent transcript texts:
{chr(10).join(texts[-10:])}

Pre-filtered repeated candidate words:
{", ".join(item["phrase"] for item in pre_candidates[:50])}

Extract only useful personal dictionary terms.
""".strip()

    try:
        data = json.loads(str(dictionary_agent.input(prompt)).strip())
        terms = data.get("terms", [])
        return terms if isinstance(terms, list) else []
    except Exception:
        return []


def normalize_candidate_term(item: Dict[str, Any]) -> Dict[str, Any] | None:
    phrase = str(item.get("phrase", "")).strip()
    confidence = float(item.get("confidence", 0.0))
    if not phrase or len(phrase) < 3 or confidence < 0.75 or phrase.lower() in STOPWORDS:
        return None

    aliases = sorted({
        str(a).strip()
        for a in (item.get("aliases", []) if isinstance(item.get("aliases", []), list) else [])
        if str(a).strip() and str(a).strip().lower() != phrase.lower()
    })

    return {
        "phrase": phrase,
        "aliases": aliases,
        "type": str(item.get("type", "custom")).strip().lower() or "custom",
        "source": "agent",
        "confidence": confidence,
        "approved": True,
    }


def merge_agent_terms_into_dictionary(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    data = load_dictionary()
    terms = data.get("terms", [])
    existing = {str(t.get("phrase", "")).lower(): t for t in terms}

    added: List[str] = []
    updated: List[str] = []

    for raw in candidates:
        item = normalize_candidate_term(raw)
        if not item:
            continue

        key = item["phrase"].lower()
        if key in existing:
            old = existing[key]
            merged_aliases = set(str(x).strip() for x in old.get("aliases", []) if str(x).strip())
            merged_aliases.update(item.get("aliases", []))
            old["aliases"] = sorted(merged_aliases)
            old["confidence"] = max(float(old.get("confidence", 0.0)), float(item["confidence"]))
            if old.get("type") in {"", "custom"} and item.get("type"):
                old["type"] = item["type"]
            old["approved"] = True
            updated.append(old["phrase"])
        else:
            terms.append(item)
            existing[key] = item
            added.append(item["phrase"])

    data["terms"] = terms
    save_dictionary(data)

    return {
        "ok": True,
        "added": added,
        "updated": updated,
        "total_terms": len(terms),
    }


def auto_update_dictionary_from_recent_texts(current_raw_text: str) -> Dict[str, Any]:
    texts = get_candidate_source_texts(current_raw_text=current_raw_text, limit=10)
    pre_candidates = collect_candidate_terms_from_recent_texts(texts=texts, min_count=2)
    agent_candidates = extract_dictionary_candidates_with_agent(texts=texts, pre_candidates=pre_candidates)
    merged = merge_agent_terms_into_dictionary(agent_candidates)

    return {
        "ok": True,
        "source_text_count": len(texts),
        "pre_candidates": pre_candidates[:20],
        "dictionary_update": merged,
    }

# =========================================================
# Merged AI refine stage
# =========================================================

def ai_refine_text(text: str, context: str = "generic", mode: str = "clean") -> str:
    if not text.strip():
        return text

    dictionary_context = build_dictionary_context()
    refine_instruction = get_refine_instruction(mode)
    context_instruction = get_context_instruction(context)

    agent = Agent(
        model="gpt-5",
        name="whispr_text_refiner",
        system_prompt=(
            "You are Whispr's text refinement agent.\n"
            "Your job is to first correct false starts, repeated fragments, self-corrections, "
            "stutters, filler-like spoken artifacts, and broken spoken structures.\n"
            "Then improve punctuation, capitalization, grammar, clarity, and readability.\n"
            "Rules:\n"
            "- Do NOT add new facts.\n"
            "- Do NOT change meaning.\n"
            "- Preserve personal dictionary terms exactly.\n"
            "- Preserve technical tokens exactly when relevant.\n"
            "- For code mode, preserve commands, code snippets, file paths, variable names, versions, and product names exactly.\n"
            "- Output ONLY the final refined text.\n"
        )
    )

    instruction = f"""
Context: {context}
Mode: {mode}

Context instruction:
{context_instruction}

Refinement instruction:
{refine_instruction}

{dictionary_context}

Input text:
{text}

Task:
First remove backtracking, false starts, repeated fragments, self-corrections, stutters, and spoken disfluencies where appropriate.
Then refine the text according to the requested mode and context.
Keep dictionary phrases exactly as specified.
Do not add new facts.
Output only the final refined text.
""".strip()

    result = str(agent.input(instruction)).strip()
    return clean_agent_output(result)

# =========================================================
# Core
# =========================================================

def transcribe_and_enhance_impl(
    audio_path: str,
    mode: str = "clean",
    context: str = "generic",
    prompt: str = "",
) -> Dict[str, Any]:
    mode, context = normalize_mode_context(mode, context)
    audio_path = str(Path(audio_path).expanduser())

    if not Path(audio_path).exists():
        return {
            "ok": False,
            "error": f"audio file not found: {audio_path}",
            "ts": now_ms(),
        }

    stt_prompt = build_dictionary_prompt(prompt)
    raw = transcribe(audio_path, prompt=stt_prompt) if stt_prompt else transcribe(audio_path)
    raw_text = str(raw).strip()

    transcript_count = len(load_history().get("items", [])) + 1
    if transcript_count % DICTIONARY_UPDATE_EVERY == 0:
        dict_update_result = auto_update_dictionary_from_recent_texts(raw_text)
    else:
        dict_update_result = {
            "ok": True,
            "skipped": True,
            "reason": f"dictionary auto-update runs every {DICTIONARY_UPDATE_EVERY} transcripts",
            "current_transcript_index": transcript_count,
            "next_run_in": DICTIONARY_UPDATE_EVERY - (transcript_count % DICTIONARY_UPDATE_EVERY),
        }

    normalized_text = apply_dictionary_corrections(raw_text)

    if mode == "off":
        refined_text = normalized_text
    else:
        try:
            refined_text = ai_refine_text(
                text=normalized_text,
                context=context,
                mode=mode,
            )
        except Exception:
            refined_text = normalized_text

        refined_text = apply_dictionary_corrections(refined_text)

    append_history({
        "ts": now_ms(),
        "audio_path": audio_path,
        "raw_text": raw_text,
        "normalized_text": normalized_text,
        "refined_text": refined_text,
        "final_text": refined_text,
        "context": context,
        "mode": mode,
    })

    return {
        "ok": True,
        "raw_text": raw_text,
        "normalized_text": normalized_text,
        "refined_text": refined_text,
        "final_text": refined_text,
        "dictionary_update": dict_update_result,
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
    default_mode: str = "clean",
    default_context: str = "generic",
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

    mode, context = normalize_mode_context(default_mode, default_context)
    profile["preferences"] = {
        "default_mode": mode,
        "default_context": context,
    }

    save_profile(profile)
    return {"ok": True, "profile": profile}


def get_profile() -> Dict[str, Any]:
    return {"ok": True, "profile": load_profile()}


def get_supported_options() -> Dict[str, Any]:
    return {
        "ok": True,
        "modes": sorted(ALLOWED_MODES),
        "contexts": sorted(ALLOWED_CONTEXTS),
    }


def add_dictionary_word(
    phrase: str,
    aliases: List[str] | None = None,
    entry_type: str = "custom",
) -> Dict[str, Any]:
    return add_or_update_dictionary_entry(
        phrase=phrase,
        aliases=aliases,
        entry_type=entry_type,
        source="user",
        confidence=1.0,
        approved=True,
    )


def list_dictionary_words() -> Dict[str, Any]:
    return {"ok": True, "dictionary": load_dictionary()}


def scan_dictionary_candidates(current_text: str = "") -> Dict[str, Any]:
    return auto_update_dictionary_from_recent_texts(current_text)


def transcribe_and_enhance(
    audio_path: str,
    mode: str = "clean",
    context: str = "generic",
    prompt: str = "",
) -> Dict[str, Any]:
    return transcribe_and_enhance_impl(
        audio_path=audio_path,
        mode=mode,
        context=context,
        prompt=prompt,
    )

# =========================================================
# Agent factory
# =========================================================

def create_agent() -> Agent:
    agent = Agent(
        model="gpt-5",
        name="whispr_orchestrator",
        system_prompt=(
            "You are Whispr. You orchestrate audio transcription, adaptive personal dictionary "
            "updates, and text refinement."
        ),
    )

    for fn in (
        create_or_update_profile,
        get_profile,
        add_dictionary_word,
        list_dictionary_words,
        scan_dictionary_candidates,
        transcribe_and_enhance,
        get_supported_options,
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

        audio_path = sys.argv[2]
        mode = sys.argv[3] if len(sys.argv) > 3 else "clean"
        context = sys.argv[4] if len(sys.argv) > 4 else "generic"
        prompt = sys.argv[5] if len(sys.argv) > 5 else ""

        print(f"PYTHON RECEIVED PATH: {audio_path}", file=sys.stderr)
        print(f"FILE EXISTS: {os.path.exists(audio_path)}", file=sys.stderr)

        try:
            result = transcribe_and_enhance_impl(
                audio_path=audio_path,
                mode=mode,
                context=context,
                prompt=prompt,
            )

            print(json.dumps({
                "output": result.get("final_text", "")
            }, ensure_ascii=False))
            sys.exit(0)

        except Exception as e:
            print(json.dumps({
                "output": ""
            }, ensure_ascii=False))
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