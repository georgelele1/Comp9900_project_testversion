from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List

from connectonion.address import load
from connectonion import Agent, host

# Import shared storage helpers from app
import sys as _sys
from pathlib import Path as _Path
_backend_root = str(_Path(__file__).resolve().parent)
if _backend_root not in _sys.path:
    _sys.path.insert(0, _backend_root)

from storage import (
    app_support_dir, storage_path, load_store, save_store, load_history,
)

def register_tool(agent, fn):
    for attr in ("add_tools", "add_tool"):
        if hasattr(agent, attr) and callable(getattr(agent, attr)):
            getattr(agent, attr)(fn)
            return
    reg = getattr(agent, "tools", None)
    if reg is not None:
        for meth in ("register", "add", "add_tool", "add_function", "append"):
            m = getattr(reg, meth, None)
            if callable(m):
                m(fn)
                return

BASE_DIR = Path(__file__).resolve().parent
CO_DIR   = BASE_DIR / ".co"

DICTIONARY_FILE              = "dictionary.json"
DICTIONARY_UPDATE_INTERVAL   = 60 * 60 * 24  # 24 hours


# =========================================================
# Dictionary storage
# =========================================================

def load_dictionary() -> Dict[str, Any]:
    return load_store(DICTIONARY_FILE, {"terms": []})


def save_dictionary(data: Dict[str, Any]) -> None:
    save_store(DICTIONARY_FILE, data)


# =========================================================
# Dictionary auto-update helpers
# (live here — not in app.py which has no update logic)
# =========================================================

def should_update_dictionary() -> bool:
    """True if update should run.

    Always runs if:
    - No timestamp exists (first run)
    - Dictionary has no terms yet
    - New history items exist AND 1h has passed (not 24h) when dictionary is small
    - 24h have passed regardless
    """
    path = storage_path("dictionary_last_update.json")
    if not path.exists():
        return True

    # Always update if dictionary is empty
    if not load_dictionary().get("terms"):
        return True

    try:
        data     = json.loads(path.read_text(encoding="utf-8"))
        elapsed  = time.time() - data.get("last_update", 0)
        # Check if there are new history items since last update
        new_items = get_new_history_since_last_update()
        # Update if 1h passed and there are new items, or 24h passed regardless
        if new_items and elapsed > 3600:
            return True
        return elapsed > DICTIONARY_UPDATE_INTERVAL
    except Exception:
        return True


def mark_dictionary_updated() -> None:
    storage_path("dictionary_last_update.json").write_text(
        json.dumps({"last_update": time.time()}), encoding="utf-8"
    )


def get_new_history_since_last_update() -> List[Dict[str, Any]]:
    """Return only history items recorded after the last dictionary update."""
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
    """Scale sample size relative to number of new items."""
    total = len(items)
    if total == 0:  return 0
    if total < 20:  return total
    if total < 100: return max(20, total // 3)
    return max(40, total // 5)


def deduplicate_items(texts: List[str], threshold: int = 10) -> List[str]:
    """Remove near-duplicate texts using a word fingerprint."""
    seen, unique = set(), []
    for text in texts:
        fp = " ".join(text.lower().split()[:threshold])
        if fp not in seen:
            seen.add(fp)
            unique.append(text)
    return unique


def prepare_items_for_agent(items: List[Dict[str, Any]]) -> List[str]:
    """Strip all fields except final_text and deduplicate — saves ~60% tokens."""
    texts = [
        str(item.get("final_text", "")).strip()
        for item in items
        if str(item.get("final_text", "")).strip()
    ]
    return deduplicate_items(texts)


# =========================================================
# Agent tool functions
# =========================================================

def get_recent_transcripts(limit: int = 20) -> Dict[str, Any]:
    """Return the most recent transcript texts for analysis."""
    items = load_history().get("items", [])
    texts = [
        str(item.get("final_text", "")).strip()
        for item in items[-limit:]
        if str(item.get("final_text", "")).strip()
    ]
    return {"ok": True, "texts": texts, "count": len(texts)}


def get_dictionary() -> Dict[str, Any]:
    """Return the current personal dictionary."""
    return {"ok": True, "dictionary": load_dictionary()}


def add_or_update_term(
    phrase: str,
    aliases: List[str] | None = None,
    entry_type: str = "custom",
    confidence: float = 1.0,
) -> Dict[str, Any]:
    """Add a new term or merge aliases into an existing one."""
    phrase = str(phrase or "").strip()
    if not phrase:
        return {"ok": False, "error": "phrase is required"}

    clean_aliases = sorted({
        str(a).strip()
        for a in (aliases or [])
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

    entry = {
        "phrase":     phrase,
        "aliases":    clean_aliases,
        "type":       entry_type or "custom",
        "source":     "agent",
        "confidence": float(confidence),
        "approved":   True,
    }
    terms.append(entry)
    data["terms"] = terms
    save_dictionary(data)
    return {"ok": True, "updated": False, "entry": entry}


def remove_term(phrase: str) -> Dict[str, Any]:
    """Remove a term from the dictionary."""
    phrase = str(phrase or "").strip()
    if not phrase:
        return {"ok": False, "error": "phrase is required"}

    data     = load_dictionary()
    terms    = data.get("terms", [])
    filtered = [t for t in terms if str(t.get("phrase", "")).lower() != phrase.lower()]

    if len(filtered) == len(terms):
        return {"ok": False, "error": f"term not found: {phrase}"}

    data["terms"] = filtered
    save_dictionary(data)
    return {"ok": True, "removed": phrase, "total_terms": len(filtered)}


def approve_term(phrase: str, approved: bool = True) -> Dict[str, Any]:
    """Approve or disable a dictionary term."""
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


# =========================================================
# Token-efficient batched update
# Single agent call for all new items — avoids one call per item
# =========================================================

def _is_duplicate(phrase: str, existing: dict) -> str | None:
    """Return existing key if phrase is a duplicate or variant, else None."""
    p = phrase.lower().strip()
    if p in existing:
        return p
    for key, term in existing.items():
        aliases_lower = [a.lower() for a in term.get("aliases", [])]
        if p in aliases_lower:
            return key
        # Normalised match — strip spaces/hyphens e.g. "front end" == "frontend"
        p_norm   = re.sub(r"[-\s]", "", p)
        key_norm = re.sub(r"[-\s]", "", key)
        if p_norm == key_norm and p_norm:
            return key
    return None


def deduplicate_dictionary() -> Dict[str, Any]:
    """Scan dictionary for duplicates and merge them."""
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
            existing_aliases = set(merged[dup].get("aliases", []))
            new_aliases      = set(term.get("aliases", []))
            if phrase.lower() != dup:
                new_aliases.add(phrase)
            merged[dup]["aliases"] = sorted(existing_aliases | new_aliases)
            if term.get("confidence", 0) > merged[dup].get("confidence", 0):
                merged[dup]["confidence"] = term["confidence"]
            removed += 1
        else:
            merged[key] = term

    dictionary["terms"] = list(merged.values())
    save_dictionary(dictionary)
    print(f"[dictionary] deduplication: {removed} duplicates merged", file=sys.stderr)
    return {"merged": removed, "total_terms": len(dictionary["terms"])}


def run_batched_update(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    texts = prepare_items_for_agent(items)
    if not texts:
        return {"added": [], "updated": [], "total_terms": len(load_dictionary().get("terms", []))}

    existing_terms = load_dictionary().get("terms", [])
    existing_hint  = ", ".join('"' + t["phrase"] + '"' for t in existing_terms[:30])
    existing_note  = (
        f"\nExisting terms (do NOT re-add these): {existing_hint}."
        if existing_hint else ""
    )

    agent = Agent(
        model="gpt-5",
        name="whispr_dictionary_batch_updater",
        system_prompt=(
            "You are a dictionary term extractor for a voice transcription app. "
            "Given transcribed texts separated by '---', identify domain-specific terms, "
            "proper nouns, technical words, or project names that would benefit from a "
            "correction dictionary. Skip common everyday words."
            + existing_note +
            " If a term is a variant of an existing one (e.g. 'frontend' vs 'front end'), "
            "add it as an alias to the existing term instead of a new entry. "
            "Return ONLY a JSON array: [{\"phrase\": \"...\", \"aliases\": [...]}]. "
            "No explanation, no markdown."
        ),
    )

    try:
        new_terms = json.loads(str(agent.input(
            f"Batch of {len(texts)} texts:\n\n" + "\n---\n".join(texts) +
            "\n\nReturn JSON array only."
        )).strip())
        if not isinstance(new_terms, list):
            new_terms = []
    except Exception:
        new_terms = []

    dictionary = load_dictionary()
    existing   = {str(t.get("phrase", "")).lower(): t for t in dictionary.get("terms", [])}
    added, updated = [], []

    for term in new_terms:
        phrase  = str(term.get("phrase", "")).strip()
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
                "phrase": phrase, "aliases": sorted(aliases),
                "type": "custom", "source": "agent",
                "confidence": 1.0, "approved": True,
            }
            existing[phrase.lower()] = entry
            added.append(entry)

    dictionary["terms"] = list(existing.values())
    save_dictionary(dictionary)
    deduplicate_dictionary()
    return {"added": added, "updated": updated, "total_terms": len(load_dictionary().get("terms", []))}


# =========================================================
# Agent factory
# =========================================================

def create_agent() -> Agent:
    agent = Agent(
        model="gpt-5",
        name="whispr_dictionary_agent",
        system_prompt=(
            "You are Whispr's personal dictionary agent. "
            "When asked to update, use get_recent_transcripts to fetch history, "
            "then find recurring proper nouns, technical terms, and domain-specific phrases. "
            "Prioritise terms that are NOT common everyday words and are likely mis-transcribed. "
            "Use add_or_update_term to save each. Include mishearing aliases where evident."
        ),
    )
    for fn in (get_recent_transcripts, get_dictionary, add_or_update_term, remove_term, approve_term):
        register_tool(agent, fn)
    return agent


# =========================================================
# CLI / host
# =========================================================

def _exit_json(data: Dict[str, Any], code: int = 0) -> None:
    print(json.dumps(data, ensure_ascii=False))
    sys.exit(code)


if __name__ == "__main__":
    if not (len(sys.argv) > 1 and sys.argv[1] == "cli"):
        addr = load(CO_DIR)
        host(create_agent, relay_url=None, whitelist=[addr["address"]], blacklist=[])
        sys.exit(0)

    command = sys.argv[2] if len(sys.argv) > 2 else "update"
    print(f"DICTIONARY AGENT CLI: {command}", file=sys.stderr)

    try:
        if command == "update":
            if not should_update_dictionary():
                _exit_json({
                    "ok": True, "skipped": True, "reason": "updated recently",
                    "added": [], "updated": [],
                    "total_terms": len(load_dictionary().get("terms", [])),
                })

            new_items = get_new_history_since_last_update()
            limit     = get_optimal_sample_size(new_items)
            print(f"New records: {len(new_items)}, sampling: {limit}", file=sys.stderr)

            if limit == 0:
                _exit_json({
                    "ok": True, "skipped": True, "reason": "no new history since last update",
                    "added": [], "updated": [],
                    "total_terms": len(load_dictionary().get("terms", [])),
                })

            result = run_batched_update(new_items[-limit:])
            mark_dictionary_updated()
            _exit_json({
                "ok": True, "skipped": False,
                "new_records_found": len(new_items),
                "records_processed": min(limit, len(new_items)),
                "added":       result["added"],
                "updated":     result["updated"],
                "total_terms": result["total_terms"],
            })

        elif command == "list":
            data = load_dictionary()
            _exit_json({"terms": data.get("terms", []), "count": len(data.get("terms", []))})

        elif command == "deduplicate":
            result = deduplicate_dictionary()
            _exit_json({"ok": True, "merged": result["merged"], "total_terms": result["total_terms"]})

        elif command == "add":
            phrase     = sys.argv[3] if len(sys.argv) > 3 else ""
            aliases    = sys.argv[4].split(",") if len(sys.argv) > 4 else []
            entry_type = sys.argv[5] if len(sys.argv) > 5 else "custom"
            _exit_json({"output": add_or_update_term(phrase, aliases, entry_type)})

        elif command == "remove":
            phrase = sys.argv[3] if len(sys.argv) > 3 else ""
            _exit_json({"output": remove_term(phrase)})

        else:
            _exit_json({"output": "", "error": f"unknown command: {command}"}, 1)

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        _exit_json({"output": "", "error": str(e)}, 1)