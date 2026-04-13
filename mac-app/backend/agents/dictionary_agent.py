"""
dictionary_agent.py — Personal dictionary learning for Whispr.

Pipeline roles:
  inject_dictionary()             → after_user_input on refiner subagent only
                                    pure disk read, 0ms, no LLM
  update_dictionary_background()  → on_complete on refiner subagent only
                                    debounced every 20, daemon thread

Knowledge and calendar subagents do NOT use dictionary events.
"""
from __future__ import annotations

import json
import re
import sys
import time
import threading
from pathlib import Path
from typing import Any, Dict, List

from connectonion.address import load
from connectonion import Agent, host

import sys as _sys
from pathlib import Path as _Path
_backend_root = str(_Path(__file__).resolve().parent)
if _backend_root not in _sys.path:
    _sys.path.insert(0, _backend_root)

from storage import storage_path, load_store, save_store, load_history

BASE_DIR = Path(__file__).resolve().parent
CO_DIR   = BASE_DIR / ".co"

DICTIONARY_FILE  = "dictionary.json"
_DICT_TOP_N      = 50
_UPDATE_EVERY    = 20
_update_counter  = 0
_update_running  = False
_update_lock     = threading.Lock()

_COMMON = {
    "the","a","an","and","or","but","in","on","at","to","for","of","with",
    "is","was","are","were","be","been","i","you","he","she","we","they",
    "it","this","that","my","your","his","her","our","its","have","has",
    "do","did","can","will","would","could","should","may","might","just",
    "so","then","also","about","from","into","up","out","if","not","as",
    "all","some","one","two","more","other","new","get","got","go","said",
    "there","here","now","like","very","really","okay","hi","hey","yeah",
    "when","what","how","which","who","where","because","after","before",
    "meeting","email","message","need","want","make","let","know","think",
    "time","day","week","today","tomorrow","back","right","good","great",
}


# =========================================================
# Storage
# =========================================================

def load_dictionary() -> Dict[str, Any]:
    return load_store(DICTIONARY_FILE, {"terms": []})


def save_dictionary(data: Dict[str, Any]) -> None:
    save_store(DICTIONARY_FILE, data)


# =========================================================
# Pipeline event handlers
# =========================================================

def inject_dictionary(agent) -> None:
    """after_user_input — inject top-N approved terms. 0ms, no LLM."""
    terms = [
        t["phrase"] for t in load_dictionary().get("terms", [])
        if t.get("approved", True) and t.get("phrase", "").strip()
    ][:_DICT_TOP_N]
    if terms:
        agent.current_session["messages"].append({
            "role":    "system",
            "content": f"Known terms (fix if misheard): {', '.join(terms)}.",
        })


def update_dictionary_background(agent) -> None:
    """on_complete — debounced background update. Daemon thread."""
    global _update_counter, _update_running
    _update_counter += 1
    if _update_counter % _UPDATE_EVERY != 0:
        return
    with _update_lock:
        if _update_running:
            return
        _update_running = True
    threading.Thread(target=_background_update, daemon=True).start()


def _background_update() -> None:
    global _update_running
    all_texts = [
        str(i.get("final_text", "")).strip()
        for i in load_history().get("items", [])[-200:]
        if str(i.get("final_text", "")).strip()
    ]
    prune_stale_terms(all_texts)
    new_items = _get_new_since_last_update()
    limit     = _optimal_sample_size(new_items)
    if limit > 0:
        run_batched_update(new_items[-limit:])
        _mark_updated()
    with _update_lock:
        _update_running = False


# =========================================================
# Update helpers
# =========================================================

def _mark_updated() -> None:
    storage_path("dictionary_last_update.json").write_text(
        json.dumps({"last_update": time.time()}), encoding="utf-8"
    )


def _get_new_since_last_update() -> List[Dict[str, Any]]:
    path    = storage_path("dictionary_last_update.json")
    last_ts = 0.0
    if path.exists():
        last_ts = json.loads(path.read_text(encoding="utf-8")).get("last_update", 0.0)
    return [
        item for item in load_history().get("items", [])
        if item.get("ts", 0) / 1000 > last_ts
    ]


def _optimal_sample_size(items: List[Any]) -> int:
    total = len(items)
    if total == 0:  return 0
    if total < 20:  return total
    if total < 100: return max(20, total // 3)
    return max(40, total // 5)


def _deduplicate_texts(texts: List[str]) -> List[str]:
    seen, unique = set(), []
    for text in texts:
        fp = " ".join(text.lower().split()[:10])
        if fp not in seen:
            seen.add(fp)
            unique.append(text)
    return unique


def _count_frequency(texts: List[str]) -> List[tuple]:
    freq: dict = {}
    for text in texts:
        tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-']*[A-Za-z0-9]|[A-Za-z0-9]", text)
        for tok in set(t.lower() for t in tokens):
            freq[tok] = freq.get(tok, 0) + 1
    return sorted(
        [(k, v) for k, v in freq.items() if v >= 2 and k not in _COMMON and len(k) >= 2],
        key=lambda x: -x[1],
    )[:40]


def _is_duplicate(phrase: str, existing: dict) -> str | None:
    p = phrase.lower().strip()
    if p in existing:
        return p
    for key, term in existing.items():
        if p in [a.lower() for a in term.get("aliases", [])]:
            return key
        if re.sub(r"[-\s]", "", p) == re.sub(r"[-\s]", "", key):
            return key
    return None


def deduplicate_dictionary() -> Dict[str, Any]:
    dictionary = load_dictionary()
    terms      = dictionary.get("terms", [])
    merged     = {}
    removed    = 0
    for term in terms:
        phrase = str(term.get("phrase", "")).strip()
        if not phrase:
            continue
        key = phrase.lower()
        dup = _is_duplicate(phrase, {k: v for k, v in merged.items() if k != key})
        if dup:
            merged[dup]["aliases"] = sorted(
                set(merged[dup].get("aliases", [])) | set(term.get("aliases", []))
            )
            removed += 1
        else:
            merged[key] = term
    dictionary["terms"] = list(merged.values())
    save_dictionary(dictionary)
    return {"merged": removed, "total_terms": len(dictionary["terms"])}


def prune_stale_terms(all_history_texts: List[str]) -> None:
    dictionary = load_dictionary()
    terms      = dictionary.get("terms", [])
    if not terms or not all_history_texts:
        return
    all_text      = " ".join(all_history_texts).lower()
    kept, removed = [], []
    for term in terms:
        if term.get("source") == "user":
            kept.append(term)
            continue
        phrase  = str(term.get("phrase", "")).strip().lower()
        aliases = [str(a).strip().lower() for a in term.get("aliases", []) if str(a).strip()]
        if phrase in all_text or any(a in all_text for a in aliases):
            kept.append(term)
        else:
            removed.append(term.get("phrase", ""))
    dictionary["terms"] = kept
    save_dictionary(dictionary)
    if removed:
        print(f"[dictionary] pruned {len(removed)} stale", file=sys.stderr)


# =========================================================
# Batched update — profile-aware
# =========================================================

def run_batched_update(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    texts = _deduplicate_texts([
        str(item.get("final_text", "")).strip()
        for item in items
        if str(item.get("final_text", "")).strip()
    ])
    if not texts:
        return {"added": [], "updated": [], "total_terms": len(load_dictionary().get("terms", []))}

    from agents.profile import get_user_context
    profile_ctx = get_user_context()
    profile_hint = f"User profile: {profile_ctx}\n\n" if profile_ctx else ""

    recurring  = _count_frequency(texts)
    freq_hint  = (
        "Recurring tokens from this user's transcriptions (term: count):\n"
        + ", ".join(f"{k}({v})" for k, v in recurring) + "\n\n"
    ) if recurring else ""

    existing_terms = load_dictionary().get("terms", [])
    skip_hint = (
        "Already in dictionary — skip: "
        + ", ".join(f'"{t["phrase"]}"' for t in existing_terms[:40]) + "\n\n"
    ) if existing_terms else ""

    agent = Agent(
        model="gpt-5.4",
        name="whispr_dictionary_updater",
        system_prompt=(
            "You are a dictionary term extractor for a voice transcription app.\n"
            "Find words this specific user says that a speech model will mis-transcribe.\n\n"
            f"{profile_hint}"
            f"{freq_hint}"
            f"{skip_hint}"
            "ADD a term ONLY when ALL criteria are met:\n"
            "1. SPECIFIC — proper noun, course code, project, brand, acronym, "
            "technical/medical/legal term, person name, or organisation.\n"
            "2. RECURRING — appears in 2+ transcriptions.\n"
            "3. NOT COMMON — not a standard English dictionary word.\n"
            "4. MIS-TRANSCRIPTION RISK — unusual spelling, sounds like another word, "
            "abbreviation, number+letter mix, or non-English origin.\n\n"
            "For aliases: list every realistic way a speech model might mishear this term.\n"
            "For type pick one: course_code | person_name | project_name | "
            "brand | acronym | technical | organisation | place | other\n\n"
            "Return ONLY a JSON array — no markdown:\n"
            '[{"phrase":"Term","type":"technical","aliases":["mishearing"]}]\n'
            "Return [] if nothing qualifies."
        ),
    )

    raw = str(agent.input(
        f"{len(texts)} transcriptions:\n\n" + "\n---\n".join(texts) +
        "\n\nReturn JSON array only."
    )).strip()

    new_terms = json.loads(raw) if raw.startswith("[") else []
    if not isinstance(new_terms, list):
        new_terms = []

    dictionary = load_dictionary()
    existing   = {str(t.get("phrase", "")).lower(): t for t in dictionary.get("terms", [])}
    added, updated = [], []

    for term in new_terms:
        phrase = str(term.get("phrase", "")).strip()
        if not phrase:
            continue
        aliases = [str(a).strip() for a in term.get("aliases", []) if str(a).strip()]
        dup_key = _is_duplicate(phrase, existing)
        if dup_key:
            e = existing[dup_key]
            e["aliases"]  = sorted(set(e.get("aliases", [])) | set(aliases))
            e["approved"] = True
            updated.append(e)
        else:
            entry = {
                "phrase":     phrase,
                "aliases":    sorted(aliases),
                "type":       str(term.get("type", "other")).strip() or "other",
                "source":     "agent",
                "confidence": 1.0,
                "approved":   True,
            }
            existing[phrase.lower()] = entry
            added.append(entry)

    dictionary["terms"] = list(existing.values())
    save_dictionary(dictionary)
    deduplicate_dictionary()
    print(f"[dictionary] +{len(added)} added, {len(updated)} updated", file=sys.stderr)
    return {"added": added, "updated": updated, "total_terms": len(load_dictionary().get("terms", []))}


# =========================================================
# CRUD tools
# =========================================================

def add_or_update_term(phrase: str, aliases: List[str] | None = None,
                       entry_type: str = "custom", confidence: float = 1.0) -> Dict[str, Any]:
    phrase = str(phrase or "").strip()
    if not phrase:
        return {"ok": False, "error": "phrase is required"}
    clean_aliases = sorted({
        str(a).strip() for a in (aliases or [])
        if str(a).strip() and str(a).strip().lower() != phrase.lower()
    })
    data  = load_dictionary()
    terms = data.get("terms", [])
    for item in terms:
        if str(item.get("phrase", "")).lower() == phrase.lower():
            merged = set(str(x).strip() for x in item.get("aliases", []) if str(x).strip())
            merged.update(clean_aliases)
            item["aliases"]    = sorted(merged)
            item["type"]       = entry_type or item.get("type", "custom")
            item["confidence"] = max(float(item.get("confidence", 0.0)), float(confidence))
            item["source"]     = "agent"
            item["approved"]   = True
            save_dictionary(data)
            return {"ok": True, "updated": True, "entry": item}
    entry = {"phrase": phrase, "aliases": clean_aliases, "type": entry_type or "custom",
             "source": "agent", "confidence": float(confidence), "approved": True}
    terms.append(entry)
    data["terms"] = terms
    save_dictionary(data)
    return {"ok": True, "updated": False, "entry": entry}


def remove_term(phrase: str) -> Dict[str, Any]:
    phrase = str(phrase or "").strip()
    if not phrase:
        return {"ok": False, "error": "phrase is required"}
    data     = load_dictionary()
    filtered = [t for t in data.get("terms", []) if str(t.get("phrase", "")).lower() != phrase.lower()]
    if len(filtered) == len(data.get("terms", [])):
        return {"ok": False, "error": f"term not found: {phrase}"}
    data["terms"] = filtered
    save_dictionary(data)
    return {"ok": True, "removed": phrase}


def approve_term(phrase: str, approved: bool = True) -> Dict[str, Any]:
    phrase = str(phrase or "").strip()
    if not phrase:
        return {"ok": False, "error": "phrase is required"}
    data = load_dictionary()
    for item in data.get("terms", []):
        if str(item.get("phrase", "")).lower() == phrase.lower():
            item["approved"] = bool(approved)
            save_dictionary(data)
            return {"ok": True, "phrase": phrase, "approved": item["approved"]}
    return {"ok": False, "error": f"term not found: {phrase}"}


def get_recent_transcripts(limit: int = 20) -> Dict[str, Any]:
    items = load_history().get("items", [])
    texts = [str(item.get("final_text", "")).strip() for item in items[-limit:]
             if str(item.get("final_text", "")).strip()]
    return {"ok": True, "texts": texts, "count": len(texts)}


# =========================================================
# Interactive agent + CLI
# =========================================================

def create_agent() -> Agent:
    agent = Agent(
        model="gpt-5",
        name="whispr_dictionary_agent",
        system_prompt=(
            "You are Whispr's personal dictionary agent. "
            "Find recurring proper nouns, technical terms, and domain-specific phrases "
            "from transcription history that are likely to be mis-transcribed. "
            "Use add_or_update_term to save each with mishearing aliases."
        ),
    )
    for fn in (get_recent_transcripts, add_or_update_term, remove_term, approve_term):
        for attr in ("add_tools", "add_tool"):
            if hasattr(agent, attr):
                getattr(agent, attr)(fn)
                break
    return agent


def _exit_json(data: Dict[str, Any], code: int = 0) -> None:
    print(json.dumps(data, ensure_ascii=False))
    sys.exit(code)


if __name__ == "__main__":
    if not (len(sys.argv) > 1 and sys.argv[1] == "cli"):
        addr = load(CO_DIR)
        host(create_agent, relay_url=None, whitelist=[addr["address"]], blacklist=[])
        sys.exit(0)

    command = sys.argv[2] if len(sys.argv) > 2 else "update"

    if command == "update":
        all_texts = [str(i.get("final_text", "")).strip()
                     for i in load_history().get("items", [])[-200:]
                     if str(i.get("final_text", "")).strip()]
        prune_stale_terms(all_texts)
        new_items = _get_new_since_last_update()
        limit     = _optimal_sample_size(new_items)
        if limit == 0:
            _exit_json({"ok": True, "skipped": True, "reason": "no new history"})
        result = run_batched_update(new_items[-limit:])
        _mark_updated()
        _exit_json({"ok": True, **result})

    elif command == "list":
        data = load_dictionary()
        _exit_json({"terms": data.get("terms", []), "count": len(data.get("terms", []))})

    elif command == "deduplicate":
        _exit_json({"ok": True, **deduplicate_dictionary()})

    elif command == "add":
        phrase     = sys.argv[3] if len(sys.argv) > 3 else ""
        aliases    = sys.argv[4].split(",") if len(sys.argv) > 4 else []
        entry_type = sys.argv[5] if len(sys.argv) > 5 else "custom"
        _exit_json(add_or_update_term(phrase, aliases, entry_type))

    elif command == "remove":
        _exit_json(remove_term(sys.argv[3] if len(sys.argv) > 3 else ""))

    else:
        _exit_json({"error": f"unknown command: {command}"}, 1)