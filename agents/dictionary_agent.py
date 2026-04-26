"""
agents/dictionary_agent.py — Personal dictionary: injection, background updates, CRUD, CLI.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List


# ── sys.path fix MUST be before local imports ────────────────────────────────
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))
# ─────────────────────────────────────────────────────────────────────────────


from connectonion.address import load
from connectonion import Agent, host

from storage import (
    storage_path,
    load_store,
    save_store,
    load_history,
    get_agent_model,
    load_env_into_os,
)


load_env_into_os()

BASE_DIR = Path(__file__).resolve().parent
CO_DIR = BASE_DIR / ".co"

DICTIONARY_FILE = "dictionary.json"
_DICT_TOP_N = 50


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
    lines = []

    for term in load_dictionary().get("terms", []):
        if not term.get("approved", True):
            continue

        phrase = str(term.get("phrase", "")).strip()
        if not phrase:
            continue

        aliases = [
            str(alias).strip()
            for alias in term.get("aliases", [])
            if str(alias).strip()
        ]

        if aliases:
            lines.append(f"{phrase} (also: {', '.join(aliases)})")
        else:
            lines.append(phrase)

        if len(lines) >= _DICT_TOP_N:
            break

    if lines:
        agent.current_session["messages"].append({
            "role": "system",
            "content": (
                "Known dictionary terms. If an alias appears in the input, "
                "replace it with the correct phrase:\n"
                + "\n".join(f"- {line}" for line in lines)
            ),
        })



# =========================================================
# Update scheduling helpers
# =========================================================

def mark_dictionary_updated() -> None:
    storage_path("dictionary_last_update.json").write_text(
        json.dumps({"last_update": time.time()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
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

    if total == 0:
        return 0

    if total < 20:
        return total

    if total < 100:
        return max(20, total // 3)

    return max(40, total // 5)


def deduplicate_items(texts: List[str], threshold: int = 10) -> List[str]:
    seen = set()
    unique = []

    for text in texts:
        fp = " ".join(text.lower().split()[:threshold])
        if fp not in seen:
            seen.add(fp)
            unique.append(text)

    return unique


def prepare_items_for_agent(items: List[Dict[str, Any]]) -> List[str]:
    texts = []

    for item in items:
        raw = str(item.get("raw_text", "")).strip()
        final = str(item.get("final_text", "")).strip()

        if not final:
            continue

        if raw and raw.lower() != final.lower() and len(raw) > 8:
            texts.append(f"[heard: {raw}] → [corrected: {final}]")
        else:
            texts.append(final)

    return deduplicate_items(texts)


# =========================================================
# Agent tool functions
# =========================================================

def get_recent_transcripts(limit: int = 20) -> Dict[str, Any]:
    items = load_history().get("items", [])

    texts = [
        str(item.get("final_text", "")).strip()
        for item in items[-limit:]
        if str(item.get("final_text", "")).strip()
    ]

    return {
        "ok": True,
        "texts": texts,
        "count": len(texts),
    }


def get_dictionary() -> Dict[str, Any]:
    return {
        "ok": True,
        "dictionary": load_dictionary(),
    }


def add_or_update_term(
    phrase: str,
    aliases: List[str] | None = None,
    entry_type: str = "custom",
    confidence: float = 1.0,
) -> Dict[str, Any]:
    phrase = str(phrase or "").strip()

    if not phrase:
        return {"ok": False, "error": "phrase is required"}

    clean_aliases = sorted({
        str(alias).strip()
        for alias in (aliases or [])
        if str(alias).strip()
        and str(alias).strip().lower() != phrase.lower()
    })

    data = load_dictionary()
    terms = data.get("terms", [])

    for item in terms:
        if str(item.get("phrase", "")).lower() == phrase.lower():
            merged_aliases = set(
                str(alias).strip()
                for alias in item.get("aliases", [])
                if str(alias).strip()
            )
            merged_aliases.update(clean_aliases)

            item["aliases"] = sorted(merged_aliases)
            item["type"] = entry_type or item.get("type", "custom")
            item["confidence"] = max(
                float(item.get("confidence", 0.0)),
                float(confidence),
            )
            item["source"] = item.get("source", "agent")
            item["approved"] = True

            if not item.get("added_at"):
                item["added_at"] = time.time()

            save_dictionary(data)

            return {
                "ok": True,
                "updated": True,
                "entry": item,
            }

    entry = {
        "phrase": phrase,
        "aliases": clean_aliases,
        "type": entry_type or "custom",
        "source": "agent",
        "confidence": float(confidence),
        "approved": True,
        "added_at": time.time(),
    }

    terms.append(entry)
    data["terms"] = terms
    save_dictionary(data)

    return {
        "ok": True,
        "updated": False,
        "entry": entry,
    }


def remove_term(phrase: str) -> Dict[str, Any]:
    phrase = str(phrase or "").strip()

    if not phrase:
        return {"ok": False, "error": "phrase is required"}

    data = load_dictionary()
    terms = data.get("terms", [])

    filtered = [
        term for term in terms
        if str(term.get("phrase", "")).lower() != phrase.lower()
    ]

    if len(filtered) == len(terms):
        return {"ok": False, "error": f"term not found: {phrase}"}

    data["terms"] = filtered
    save_dictionary(data)

    return {
        "ok": True,
        "removed": phrase,
        "total_terms": len(filtered),
    }


def approve_term(phrase: str, approved: bool = True) -> Dict[str, Any]:
    phrase = str(phrase or "").strip()

    if not phrase:
        return {"ok": False, "error": "phrase is required"}

    data = load_dictionary()

    for item in data.get("terms", []):
        if str(item.get("phrase", "")).lower() == phrase.lower():
            item["approved"] = bool(approved)
            save_dictionary(data)

            return {
                "ok": True,
                "phrase": phrase,
                "approved": item["approved"],
            }

    return {"ok": False, "error": f"term not found: {phrase}"}


# =========================================================
# Batched update
# =========================================================

def _is_duplicate(phrase: str, existing: dict) -> str | None:
    phrase_key = phrase.lower().strip()

    if phrase_key in existing:
        return phrase_key

    for key, term in existing.items():
        aliases_lower = [
            str(alias).lower()
            for alias in term.get("aliases", [])
        ]

        if phrase_key in aliases_lower:
            return key

        phrase_norm = re.sub(r"[-\s]", "", phrase_key)
        key_norm = re.sub(r"[-\s]", "", key)

        if phrase_norm == key_norm and phrase_norm:
            return key

    return None


def deduplicate_dictionary() -> Dict[str, Any]:
    dictionary = load_dictionary()
    terms = dictionary.get("terms", [])

    merged = {}
    removed = 0

    for term in terms:
        phrase = str(term.get("phrase", "")).strip()
        if not phrase:
            continue

        key = phrase.lower()
        duplicate_key = _is_duplicate(
            phrase,
            {k: v for k, v in merged.items() if k != key},
        )

        if duplicate_key:
            existing_aliases = set(merged[duplicate_key].get("aliases", []))
            new_aliases = set(term.get("aliases", []))

            if phrase.lower() != duplicate_key:
                new_aliases.add(phrase)

            merged[duplicate_key]["aliases"] = sorted(existing_aliases | new_aliases)

            if term.get("confidence", 0) > merged[duplicate_key].get("confidence", 0):
                merged[duplicate_key]["confidence"] = term["confidence"]

            removed += 1

        else:
            merged[key] = term

    dictionary["terms"] = list(merged.values())
    save_dictionary(dictionary)

    return {
        "merged": removed,
        "total_terms": len(dictionary["terms"]),
    }


def _count_term_frequency(texts: List[str]) -> dict:
    freq = {}

    for text in texts:
        tokens = re.findall(
            r"[A-Za-z0-9][A-Za-z0-9\-']*[A-Za-z0-9]|[A-Za-z0-9]",
            text,
        )

        seen_in_this_text = set(token.lower() for token in tokens)

        for token in seen_in_this_text:
            freq[token] = freq.get(token, 0) + 1

    return {
        token: count
        for token, count in freq.items()
        if count >= 2
    }


def prune_stale_terms(all_history_texts: List[str]) -> Dict[str, Any]:
    dictionary = load_dictionary()
    terms = dictionary.get("terms", [])

    if not terms or not all_history_texts:
        return {
            "removed": [],
            "kept": len(terms),
        }

    all_text = " ".join(all_history_texts).lower()
    cutoff = time.time() - (7 * 24 * 3600)

    kept = []
    removed = []

    for term in terms:
        if term.get("source", "agent") != "agent":
            kept.append(term)
            continue

        added_at = term.get("added_at", 0)
        if added_at and added_at > cutoff:
            kept.append(term)
            continue

        phrase = str(term.get("phrase", "")).strip().lower()
        aliases = [
            str(alias).strip().lower()
            for alias in term.get("aliases", [])
            if str(alias).strip()
        ]

        if phrase in all_text or any(alias in all_text for alias in aliases):
            kept.append(term)
        else:
            removed.append(term.get("phrase", ""))

    dictionary["terms"] = kept
    save_dictionary(dictionary)

    return {
        "removed": removed,
        "kept": len(kept),
    }


def run_batched_update(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    texts = prepare_items_for_agent(items)

    if not texts:
        return {
            "added": [],
            "updated": [],
            "total_terms": len(load_dictionary().get("terms", [])),
        }

    freq = _count_term_frequency(texts)

    common_words = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with",
        "is", "was", "are", "were", "be", "been", "i", "you", "he", "she", "we", "they",
        "it", "this", "that", "my", "your", "his", "her", "our", "its", "have", "has",
        "do", "did", "can", "will", "would", "could", "should", "may", "might", "just",
        "so", "then", "also", "about", "from", "into", "up", "out", "if", "not", "as",
        "all", "some", "one", "two", "more", "other", "new", "get", "got", "go", "said",
        "there", "here", "now", "like", "very", "really", "okay", "hi", "hey", "yeah",
        "when", "what", "how", "which", "who", "where", "because", "after", "before",
        "meeting", "email", "message", "need", "want", "make", "let", "know", "think",
        "time", "day", "week", "today", "tomorrow", "back", "right", "good", "great",
    }

    recurring = sorted(
        [
            (token, count)
            for token, count in freq.items()
            if token not in common_words and len(token) >= 3
        ],
        key=lambda item: -item[1],
    )[:40]

    freq_hint = ""
    if recurring:
        freq_hint = (
            "\nRecurring tokens (term: count across transcriptions): "
            + ", ".join(f"{token}({count})" for token, count in recurring)
        )

    existing_terms = load_dictionary().get("terms", [])
    existing_hint = ", ".join(
        f'"{term.get("phrase", "")}"'
        for term in existing_terms[:40]
        if term.get("phrase")
    )

    existing_note = ""
    if existing_hint:
        existing_note = f"\nAlready in dictionary. Do not add these again: {existing_hint}."

    agent = Agent(
        model=get_agent_model(),
        name="whispr_dictionary_batch_updater",
        system_prompt=(
            "You are a dictionary term extractor for Whispr, a voice transcription app.\n"
            "Find words or phrases that a speech model is likely to mis-transcribe.\n\n"

            "Add a term ONLY when it is useful for future transcription correction.\n\n"

            "A good dictionary term is usually one of these:\n"
            "- Proper noun\n"
            "- Person name\n"
            "- Project name\n"
            "- Course code\n"
            "- Brand name\n"
            "- Acronym\n"
            "- Technical, medical, legal, academic, or domain-specific term\n"
            "- Organisation or place name\n"
            "- Non-English term that may be misheard\n\n"

            "Rules for adding:\n"
            "1. It must be specific, not a generic everyday word.\n"
            "2. It should appear in 2+ transcriptions OR appear in a clear heard→corrected pair.\n"
            "3. It should have mis-transcription risk: unusual spelling, abbreviation, mixed letters/numbers, "
            "non-English origin, or sounds like another word.\n"
            "4. Do not add full sentences.\n"
            "5. Do not add filler words, common verbs, common nouns, or general phrases.\n\n"

            "For aliases, include realistic mishearings only. Do not invent many aliases.\n"
            "For type, choose one of:\n"
            "course_code | person_name | project_name | brand | acronym | technical | organisation | place | other\n"

            f"{freq_hint}"
            f"{existing_note}\n\n"

            "Return ONLY valid JSON. No markdown. No explanation.\n"
            "Format:\n"
            "[{\"phrase\":\"<term>\",\"type\":\"<type>\",\"aliases\":[\"<mishearing>\"]}]\n"
            "Return [] if nothing qualifies."
        ),
    )

    try:
        raw = str(agent.input(
            f"{len(texts)} transcriptions:\n\n"
            + "\n---\n".join(texts)
            + "\n\nReturn JSON array only."
        )).strip()

        new_terms = json.loads(raw)

        if not isinstance(new_terms, list):
            new_terms = []

    except Exception:
        new_terms = []

    dictionary = load_dictionary()
    existing = {
        str(term.get("phrase", "")).lower(): term
        for term in dictionary.get("terms", [])
        if str(term.get("phrase", "")).strip()
    }

    added = []
    updated = []

    for term in new_terms:
        if not isinstance(term, dict):
            continue

        phrase = str(term.get("phrase", "")).strip()
        if not phrase:
            continue

        aliases = [
            str(alias).strip()
            for alias in term.get("aliases", [])
            if str(alias).strip()
            and str(alias).strip().lower() != phrase.lower()
        ]

        duplicate_key = _is_duplicate(phrase, existing)

        if duplicate_key:
            existing_item = existing[duplicate_key]
            existing_item["aliases"] = sorted(
                set(existing_item.get("aliases", [])) | set(aliases)
            )
            existing_item["approved"] = True

            if not existing_item.get("added_at"):
                existing_item["added_at"] = time.time()

            updated.append(existing_item)

        else:
            entry = {
                "phrase": phrase,
                "aliases": sorted(set(aliases)),
                "type": str(term.get("type", "other")).strip() or "other",
                "source": "agent",
                "confidence": 1.0,
                "approved": True,
                "added_at": time.time(),
            }

            existing[phrase.lower()] = entry
            added.append(entry)

    dictionary["terms"] = list(existing.values())
    save_dictionary(dictionary)

    deduplicate_dictionary()

    return {
        "added": added,
        "updated": updated,
        "total_terms": len(load_dictionary().get("terms", [])),
    }


# =========================================================
# Agent factory
# =========================================================

def create_agent() -> Agent:
    agent = Agent(
        model=get_agent_model(),
        name="whispr_dictionary_agent",
        system_prompt=(
            "You are Whispr's personal dictionary agent. "
            "Use the dictionary tools to manage terms that improve transcription correction. "
            "Only save proper nouns, project names, course codes, acronyms, technical terms, "
            "and other specific words that are likely to be mis-transcribed. "
            "Do not save common everyday words."
        ),
    )

    for fn in (
        get_recent_transcripts,
        get_dictionary,
        add_or_update_term,
        remove_term,
        approve_term,
    ):
        agent.add_tool(fn)

    return agent


# =========================================================
# CLI
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

    if command == "update":
        all_texts = [
            str(item.get("final_text", "")).strip()
            for item in load_history().get("items", [])[-200:]
            if str(item.get("final_text", "")).strip()
        ]

        prune_result = prune_stale_terms(all_texts)

        new_items = get_new_history_since_last_update()
        limit = get_optimal_sample_size(new_items)

        if limit == 0:
            _exit_json({
                "ok": True,
                "skipped": True,
                "reason": "no new history since last update",
                "added": [],
                "updated": [],
                "total_terms": len(load_dictionary().get("terms", [])),
                "pruned": prune_result.get("removed", []),
            })

        result = run_batched_update(new_items[-limit:])
        mark_dictionary_updated()

        _exit_json({
            "ok": True,
            "skipped": False,
            "new_records_found": len(new_items),
            "records_processed": min(limit, len(new_items)),
            "added": result["added"],
            "updated": result["updated"],
            "pruned": prune_result.get("removed", []),
            "total_terms": result["total_terms"],
        })

    elif command == "list":
        data = load_dictionary()
        terms = data.get("terms", [])
        _exit_json({
            "terms": terms,
            "count": len(terms),
        })

    elif command == "deduplicate":
        result = deduplicate_dictionary()
        _exit_json({
            "ok": True,
            "merged": result["merged"],
            "total_terms": result["total_terms"],
        })

    elif command == "add":
        phrase = sys.argv[3] if len(sys.argv) > 3 else ""
        aliases = sys.argv[4].split(",") if len(sys.argv) > 4 else []
        entry_type = sys.argv[5] if len(sys.argv) > 5 else "custom"

        _exit_json({
            "output": add_or_update_term(phrase, aliases, entry_type, confidence=1.0),
        })

    elif command == "remove":
        phrase = sys.argv[3] if len(sys.argv) > 3 else ""

        _exit_json({
            "output": remove_term(phrase),
        })

    elif command == "approve":
        phrase = sys.argv[3] if len(sys.argv) > 3 else ""

        _exit_json({
            "output": approve_term(phrase, True),
        })

    elif command == "unapprove":
        phrase = sys.argv[3] if len(sys.argv) > 3 else ""

        _exit_json({
            "output": approve_term(phrase, False),
        })

    else:
        _exit_json({
            "output": "",
            "error": f"unknown command: {command}",
        }, 1)