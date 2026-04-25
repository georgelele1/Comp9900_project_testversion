"""
agents/dictionary_agent.py — Personal dictionary: injection, background updates, CRUD, CLI.
"""
from __future__ import annotations

import json
import re
import sys
import time
import threading
from pathlib import Path
from typing import Any, Dict, List

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from connectonion.address import load
from connectonion import Agent, host

from storage import (
    storage_path, load_store, save_store,
    load_history, get_agent_model, load_env_into_os,
)

load_env_into_os()

BASE_DIR = Path(__file__).resolve().parent
CO_DIR   = BASE_DIR / ".co"

DICTIONARY_FILE            = "dictionary.json"
DICTIONARY_UPDATE_INTERVAL = 60 * 60 * 24

_DICT_TOP_N     = 50
_UPDATE_EVERY   = 5
_update_counter = 0
_update_running = False
_update_lock    = threading.Lock()

COMMON_WORDS = {
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
    "ideal","stuff","thing","file","folder","report","document","app",
    "install","download","run","build","version","command","update","system",
}

LANGUAGE_WORDS = {
    "english","chinese","spanish","french","japanese","korean","arabic",
    "german","portuguese","italian","russian","hindi","dutch","swedish",
    "mandarin","cantonese",
}

OVEREXPOSED_BRANDS = {
    "zoom","google","apple","microsoft","slack","teams","notion","figma",
    "github","gmail","chrome","safari","youtube","twitter","facebook",
    "instagram","linkedin","whatsapp","telegram","discord",
}

ALLOWED_TYPES = {
    "person_name","project_name","brand","company","domain","package",
    "technical","course_code","acronym","organisation","organization",
    "place","custom","other",
}


# =========================================================
# Storage
# =========================================================

def load_dictionary() -> Dict[str, Any]:
    return load_store(DICTIONARY_FILE, {"terms": []})


def save_dictionary(data: Dict[str, Any]) -> None:
    save_store(DICTIONARY_FILE, data)


# =========================================================
# Validation helpers
# =========================================================

def _looks_like_domain(text: str) -> bool:
    p = text.lower().strip()
    if "://" in p or "@" in p:
        return False
    if not re.fullmatch(r"[a-z0-9][a-z0-9\-]*(\.[a-z0-9][a-z0-9\-]*)+\.[a-z]{2,}", p):
        return False
    root = p.split(".")[0]
    return root not in {"company","website","page","link","mail","info","support","contact"}


def _looks_like_special_term(text: str) -> bool:
    s = text.strip()
    if not s:
        return False
    if re.search(r"[a-z][A-Z]", s): return True
    if re.search(r"\d", s):         return True
    if any(ch in s for ch in [".", "-", "_", "/"]): return True
    if s.isupper() and len(s) >= 2: return True
    return False


def _is_valid_term(phrase: str, term_type: str = "other") -> bool:
    phrase = str(phrase or "").strip()
    p = phrase.lower()
    if not phrase or len(p) < 3:         return False
    if p in COMMON_WORDS:                return False
    if p in LANGUAGE_WORDS:             return False
    if p in OVEREXPOSED_BRANDS:         return False
    if "@" in p or "://" in p:          return False
    if _looks_like_domain(phrase):      return True
    if term_type in {
        "person_name","project_name","brand","company","domain","package",
        "technical","course_code","acronym","organisation","organization",
    }:
        return True
    if _looks_like_special_term(phrase): return True
    if phrase.isalpha() and phrase == p and len(phrase) <= 8: return False
    return True


def _clean_aliases(aliases: List[str], phrase: str) -> List[str]:
    phrase_lower = phrase.lower().strip()
    cleaned = []
    for alias in aliases:
        a = str(alias).strip()
        if not a or a.lower() == phrase_lower or len(a) > 80:
            continue
        if "://" in a or "@" in a:
            continue
        cleaned.append(a)
    return sorted(set(cleaned))


def _is_duplicate(phrase: str, existing: dict) -> str | None:
    p = phrase.lower().strip()
    if p in existing:
        return p
    p_norm = re.sub(r"[-_\s.]", "", p)
    for key, term in existing.items():
        if p in [a.lower() for a in term.get("aliases", [])]:
            return key
        if p_norm and p_norm == re.sub(r"[-_\s.]", "", key.lower()):
            return key
    return None


# =========================================================
# Pipeline event handlers
# =========================================================

def inject_dictionary(agent) -> None:
    """after_user_input — inject approved terms with aliases. 0ms, no LLM."""
    lines = []
    for t in load_dictionary().get("terms", []):
        if not t.get("approved", True) or not t.get("phrase", "").strip():
            continue
        phrase  = t["phrase"].strip()
        aliases = [str(a).strip() for a in t.get("aliases", []) if str(a).strip()]
        lines.append(f"{phrase} (also: {', '.join(aliases)})" if aliases else phrase)
        if len(lines) >= _DICT_TOP_N:
            break
    if lines:
        agent.current_session["messages"].append({
            "role":    "system",
            "content": (
                "Known terms — if any alias appears in the input, replace it with the correct phrase:\n"
                + "\n".join(f"  - {l}" for l in lines)
            ),
        })


def update_dictionary_background(agent) -> None:
    """on_complete — trigger background update every _UPDATE_EVERY runs."""
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
    try:
        history   = load_history().get("items", [])[-200:]
        all_texts = [str(i.get("final_text", "")).strip() for i in history if str(i.get("final_text", "")).strip()]
        prune_stale_terms(all_texts)
        new_items = get_new_history_since_last_update()
        limit     = get_optimal_sample_size(new_items)
        if limit > 0:
            run_batched_update(new_items[-limit:])
            mark_dictionary_updated()
    finally:
        with _update_lock:
            _update_running = False


# =========================================================
# Scheduling helpers
# =========================================================

def should_update_dictionary() -> bool:
    path = storage_path("dictionary_last_update.json")
    if not path.exists():
        return True
    try:
        elapsed   = time.time() - json.loads(path.read_text(encoding="utf-8")).get("last_update", 0)
        new_items = get_new_history_since_last_update()
        return bool(new_items and elapsed > 3600) or elapsed > DICTIONARY_UPDATE_INTERVAL
    except Exception:
        return True


def mark_dictionary_updated() -> None:
    storage_path("dictionary_last_update.json").write_text(
        json.dumps({"last_update": time.time()}), encoding="utf-8"
    )


def get_new_history_since_last_update() -> List[Dict[str, Any]]:
    path    = storage_path("dictionary_last_update.json")
    last_ts = 0.0
    if path.exists():
        try:
            last_ts = json.loads(path.read_text(encoding="utf-8")).get("last_update", 0.0)
        except Exception:
            pass
    return [i for i in load_history().get("items", []) if i.get("ts", 0) / 1000 > last_ts]


def get_optimal_sample_size(items: List[Any]) -> int:
    n = len(items)
    if n == 0:   return 0
    if n < 20:   return n
    if n < 100:  return max(20, n // 3)
    return max(40, n // 5)


def deduplicate_items(texts: List[str], threshold: int = 10) -> List[str]:
    seen, unique = set(), []
    for text in texts:
        fp = " ".join(text.lower().split()[:threshold])
        if fp not in seen:
            seen.add(fp)
            unique.append(text)
    return unique


def prepare_items_for_agent(items: List[Dict[str, Any]]) -> List[str]:
    texts = []
    for item in items:
        raw   = str(item.get("raw_text",   "")).strip()
        final = str(item.get("final_text", "")).strip()
        if not final:
            continue
        if raw and raw.lower() != final.lower() and len(raw) > 8:
            texts.append(f"[heard: {raw}] → [corrected: {final}]")
        else:
            texts.append(final)
    return deduplicate_items(texts)


# =========================================================
# Entity extraction (WHO / WHAT from sentence structure)
# =========================================================

def extract_key_entities(texts: List[str]) -> List[Dict[str, Any]]:
    """LLM-based dependency-style extraction: pull subject/object proper nouns."""
    if not texts:
        return []
    sample = texts[-20:]
    agent = Agent(
        model=get_agent_model(),
        name="whispr_entity_extractor",
        system_prompt=(
            "You extract key entities from voice transcription sentences.\n\n"
            "Focus on sentence structure:\n"
            "- WHO: person being asked to do something\n"
            "- WHAT: specific product, package, project, or named thing\n\n"
            "Input may be multilingual or contain [heard: X] → [corrected: Y] pairs.\n"
            "For diff pairs, focus on the corrected Y side.\n\n"
            "INCLUDE: person names, package names, product names, project names,\n"
            "  course codes, API names, brand names, technical terms, acronyms, domains.\n"
            "EXCLUDE: verbs, generic nouns (report, meeting, email, file), common words,\n"
            "  pronouns, prepositions, filler words, full sentences, URLs, language names.\n\n"
            "For each entity:\n"
            "  - phrase: correct form\n"
            "  - type: person_name | package | brand | project_name | acronym |\n"
            "          technical | course_code | organisation | other\n"
            "  - aliases: realistic phonetic mishearings\n"
            "  - confidence: 0.9 if from diff pair, 0.85 if specific technical term\n\n"
            "Return ONLY a JSON array. No markdown.\n"
            "[{\"phrase\":\"Rezene\",\"type\":\"person_name\","
            "\"aliases\":[\"rezone\",\"rezean\"],\"confidence\":0.9}]\n"
            "Return [] if nothing qualifies."
        ),
    )
    try:
        raw = str(agent.input(
            "Extract key entities (WHO and WHAT) from these transcriptions:\n\n"
            + "\n---\n".join(sample)
            + "\n\nReturn JSON array only."
        )).strip()
        result = json.loads(raw)
        if not isinstance(result, list):
            return []
        return [
            e for e in result
            if isinstance(e, dict)
            and float(e.get("confidence", 0)) >= 0.85
            and _is_valid_term(str(e.get("phrase", "")), str(e.get("type", "other")))
        ]
    except Exception:
        return []


# =========================================================
# Dictionary CRUD (agent tools + user CLI)
# =========================================================

def get_recent_transcripts(limit: int = 20) -> Dict[str, Any]:
    items = load_history().get("items", [])
    texts = [str(i.get("final_text", "")).strip() for i in items[-limit:] if str(i.get("final_text", "")).strip()]
    return {"ok": True, "texts": texts, "count": len(texts)}


def get_dictionary() -> Dict[str, Any]:
    return {"ok": True, "dictionary": load_dictionary()}


def add_or_update_term(
    phrase     : str,
    aliases    : List[str] | None = None,
    entry_type : str   = "custom",
    confidence : float = 1.0,
    source     : str   = "user",
    approved   : bool  = True,
) -> Dict[str, Any]:
    phrase = str(phrase or "").strip()
    if not phrase:
        return {"ok": False, "error": "phrase is required"}

    clean_aliases = sorted({
        str(a).strip() for a in (aliases or [])
        if str(a).strip() and str(a).strip().lower() != phrase.lower()
    })

    data  = load_dictionary()
    terms = data.get("terms", [])
    now   = time.time()

    for item in terms:
        if str(item.get("phrase", "")).lower() == phrase.lower():
            merged = set(str(x).strip() for x in item.get("aliases", []) if str(x).strip())
            merged.update(clean_aliases)
            item["aliases"]    = sorted(merged)
            item["type"]       = entry_type or item.get("type", "custom")
            item["confidence"] = max(float(item.get("confidence", 0.0)), float(confidence))
            if item.get("source") != "user":
                item["source"] = source
            item["approved"]   = bool(approved or item.get("source") == "user")
            item["updated_at"] = now
            save_dictionary(data)
            return {"ok": True, "updated": True, "entry": item}

    entry = {
        "phrase":     phrase,
        "aliases":    clean_aliases,
        "type":       entry_type or "custom",
        "source":     source,
        "confidence": float(confidence),
        "approved":   bool(approved),
        "added_at":   now,
        "updated_at": now,
    }
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
    return {"ok": True, "removed": phrase, "total_terms": len(filtered)}


def approve_term(phrase: str, approved: bool = True) -> Dict[str, Any]:
    phrase = str(phrase or "").strip()
    if not phrase:
        return {"ok": False, "error": "phrase is required"}
    data = load_dictionary()
    for item in data.get("terms", []):
        if str(item.get("phrase", "")).lower() == phrase.lower():
            item["approved"]   = bool(approved)
            item["updated_at"] = time.time()
            save_dictionary(data)
            return {"ok": True, "phrase": phrase, "approved": item["approved"]}
    return {"ok": False, "error": f"term not found: {phrase}"}


# =========================================================
# Deduplication + pruning
# =========================================================

def deduplicate_dictionary() -> Dict[str, Any]:
    dictionary = load_dictionary()
    terms      = dictionary.get("terms", [])
    merged_map: Dict[str, Any] = {}
    removed = 0

    for term in terms:
        phrase = str(term.get("phrase", "")).strip()
        if not phrase:
            continue
        key = phrase.lower()
        dup = _is_duplicate(phrase, {k: v for k, v in merged_map.items() if k != key})
        if dup:
            e = merged_map[dup]
            new_aliases = set(term.get("aliases", []))
            if phrase.lower() != dup:
                new_aliases.add(phrase)
            e["aliases"]    = sorted(set(e.get("aliases", [])) | new_aliases)
            e["confidence"] = max(float(e.get("confidence", 0) or 0), float(term.get("confidence", 0) or 0))
            if term.get("source") == "user" or e.get("source") == "user":
                e["source"]   = "user"
                e["approved"] = True
            removed += 1
        else:
            merged_map[key] = term

    dictionary["terms"] = list(merged_map.values())
    save_dictionary(dictionary)
    return {"merged": removed, "total_terms": len(dictionary["terms"])}


def prune_stale_terms(all_history_texts: List[str]) -> Dict[str, Any]:
    dictionary = load_dictionary()
    terms      = dictionary.get("terms", [])
    if not terms or not all_history_texts:
        return {"removed": [], "kept": len(terms)}

    all_text = " ".join(all_history_texts).lower()
    cutoff   = time.time() - (7 * 24 * 3600)
    kept, removed = [], []

    for term in terms:
        if term.get("source", "agent") != "agent":
            kept.append(term)
            continue
        added_at   = float(term.get("added_at", 0) or 0)
        confidence = float(term.get("confidence", 0) or 0)
        if (added_at and added_at > cutoff) or confidence >= 0.9:
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
    return {"removed": removed, "kept": len(kept)}


# =========================================================
# Batched update
# =========================================================

def _count_term_frequency(texts: List[str]) -> dict:
    freq: dict = {}
    for text in texts:
        tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-']*[A-Za-z0-9]|[A-Za-z0-9]", text)
        for tok in set(t.lower() for t in tokens):
            freq[tok] = freq.get(tok, 0) + 1
    return {k: v for k, v in freq.items() if v >= 1}


def run_batched_update(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    texts = prepare_items_for_agent(items)
    if not texts:
        return {"added": [], "updated": [], "total_terms": len(load_dictionary().get("terms", []))}

    entity_results = extract_key_entities(texts)
    entity_hint = (
        "\nHigh-confidence entities from sentence structure (WHO and WHAT — prioritise): "
        + ", ".join(e.get("phrase", "") for e in entity_results if e.get("phrase"))
        if entity_results else ""
    )

    freq      = _count_term_frequency(texts)
    recurring = sorted(
        [(k, v) for k, v in freq.items() if k not in COMMON_WORDS and k not in LANGUAGE_WORDS and len(k) >= 3],
        key=lambda x: -x[1],
    )[:40]
    freq_hint = (
        "\nRecurring tokens: " + ", ".join(f"{k}({v})" for k, v in recurring)
        if recurring else ""
    )

    existing_terms = load_dictionary().get("terms", [])
    existing_hint  = ", ".join(f'"{t["phrase"]}"' for t in existing_terms[:40] if t.get("phrase"))
    existing_note  = f"\nAlready in dictionary (skip): {existing_hint}." if existing_hint else ""

    agent = Agent(
        model=get_agent_model(),
        name="whispr_dictionary_batch_updater",
        system_prompt=(
            "You are a dictionary term extractor for Whispr, a voice transcription app.\n"
            "Primary input: [heard: X] → [corrected: Y] diff pairs.\n"
            "Extract Y as the term, X as its alias.\n\n"
            "ADD only when ALL true:\n"
            "1. SPECIFIC — proper noun, package, course code, brand, acronym, technical term, person/org name.\n"
            "2. NOT COMMON — not a standard English word. Never add language names, nationalities,\n"
            "   common verbs (install, update, run), generic nouns, or overexposed brands (Zoom, Google).\n"
            "3. MIS-TRANSCRIPTION RISK — unusual spelling, camelCase, sounds like another word.\n"
            "4. NOT A URL — never add domains, emails, or snippet expansion values.\n\n"
            "Aliases: only realistic phonetic mishearings actually seen in diff pairs.\n"
            "Confidence: 0.95+ for clear diff pair, 0.85–0.94 for strong technical term, else omit.\n"
            f"Allowed types: {' | '.join(sorted(ALLOWED_TYPES))}\n"
            f"{entity_hint}"
            f"{freq_hint}"
            f"{existing_note}\n\n"
            "Return ONLY a JSON array. No markdown.\n"
            "[{\"phrase\":\"connectonion\",\"type\":\"package\","
            "\"aliases\":[\"connector onion\",\"connect onion\"],\"confidence\":0.95}]\n"
            "Return [] if nothing qualifies."
        ),
    )

    try:
        raw = str(agent.input(
            f"{len(texts)} transcriptions:\n\n" + "\n---\n".join(texts) + "\n\nReturn JSON array only."
        )).strip()
        new_terms = json.loads(raw)
        if not isinstance(new_terms, list):
            new_terms = []
    except Exception:
        new_terms = []

    dictionary = load_dictionary()
    existing   = {str(t.get("phrase", "")).lower(): t for t in dictionary.get("terms", []) if t.get("phrase")}
    added, updated = [], []

    for term in new_terms:
        if not isinstance(term, dict):
            continue
        phrase     = str(term.get("phrase", "")).strip()
        term_type  = str(term.get("type", "other")).strip() or "other"
        if term_type not in ALLOWED_TYPES:
            term_type = "other"
        try:
            confidence = float(term.get("confidence", 0.85))
        except Exception:
            confidence = 0.85
        if confidence < 0.85 or not _is_valid_term(phrase, term_type):
            continue
        aliases = _clean_aliases([str(a) for a in term.get("aliases", [])], phrase)
        dup_key = _is_duplicate(phrase, existing)
        if dup_key:
            e = existing[dup_key]
            e["aliases"]    = sorted(set(e.get("aliases", [])) | set(aliases))
            e["confidence"] = max(float(e.get("confidence", 0) or 0), confidence)
            e["updated_at"] = time.time()
            if e.get("source") != "user":
                e["approved"] = e["confidence"] >= 0.9
            updated.append(e)
        else:
            entry = {
                "phrase":     phrase,
                "aliases":    aliases,
                "type":       term_type,
                "source":     "agent",
                "confidence": confidence,
                "approved":   confidence >= 0.9,
                "added_at":   time.time(),
                "updated_at": time.time(),
            }
            existing[phrase.lower()] = entry
            added.append(entry)

    # Merge high-confidence entities directly
    for entity in entity_results:
        phrase     = str(entity.get("phrase", "")).strip()
        if not phrase:
            continue
        aliases    = _clean_aliases([str(a) for a in entity.get("aliases", [])], phrase)
        term_type  = str(entity.get("type", "other")).strip() or "other"
        confidence = float(entity.get("confidence", 0.9))
        dup_key    = _is_duplicate(phrase, existing)
        if dup_key:
            e = existing[dup_key]
            e["aliases"]    = sorted(set(e.get("aliases", [])) | set(aliases))
            e["confidence"] = max(float(e.get("confidence", 0) or 0), confidence)
            e["updated_at"] = time.time()
            if e.get("source") != "user":
                e["approved"] = e["confidence"] >= 0.85
            updated.append(e)
        else:
            entry = {
                "phrase":     phrase,
                "aliases":    aliases,
                "type":       term_type,
                "source":     "agent",
                "confidence": confidence,
                "approved":   confidence >= 0.85,
                "added_at":   time.time(),
                "updated_at": time.time(),
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
        model=get_agent_model(),
        name="whispr_dictionary_agent",
        system_prompt=(
            "You are Whispr's personal dictionary manager. "
            "Use get_recent_transcripts and get_dictionary when needed. "
            "Only save terms that improve speech transcription accuracy: names, "
            "project names, technical terms, package names, APIs, domains, acronyms. "
            "Do not save common words, full sentences, or snippet expansion values. "
            "Use add_or_update_term to save valid terms with realistic aliases."
        ),
    )
    for fn in (get_recent_transcripts, get_dictionary, add_or_update_term, remove_term, approve_term):
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
        force      = "--force" in sys.argv
        all_texts  = [str(i.get("final_text", "")).strip() for i in load_history().get("items", [])[-200:] if str(i.get("final_text", "")).strip()]
        prune_result = prune_stale_terms(all_texts)

        if not force and not should_update_dictionary():
            _exit_json({
                "ok": True, "skipped": True, "reason": "updated recently",
                "added": [], "updated": [],
                "pruned":      prune_result.get("removed", []),
                "total_terms": len(load_dictionary().get("terms", [])),
            })

        new_items = get_new_history_since_last_update()
        limit     = get_optimal_sample_size(new_items)
        if limit == 0:
            _exit_json({
                "ok": True, "skipped": True, "reason": "no new history",
                "added": [], "updated": [],
                "total_terms": len(load_dictionary().get("terms", [])),
            })

        result = run_batched_update(new_items[-limit:])
        mark_dictionary_updated()
        _exit_json({
            "ok": True, "skipped": False,
            "new_records_found": len(new_items),
            "records_processed": min(limit, len(new_items)),
            "added":             result["added"],
            "updated":           result["updated"],
            "pruned":            prune_result.get("removed", []),
            "total_terms":       result["total_terms"],
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
        _exit_json({"output": add_or_update_term(phrase, aliases, entry_type, source="user")})

    elif command == "remove":
        phrase = sys.argv[3] if len(sys.argv) > 3 else ""
        _exit_json({"output": remove_term(phrase)})

    else:
        _exit_json({"output": "", "error": f"unknown command: {command}"}, 1)