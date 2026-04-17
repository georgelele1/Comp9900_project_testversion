"""
storage.py — Shared storage helpers for Whispr backend.

All modules import from here instead of duplicating load/save logic.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

APP_NAME = "Whispr"

PROFILE_FILE    = "profile.json"
DICTIONARY_FILE = "dictionary.json"
HISTORY_FILE    = "history.json"
ENV_FILE        = ".env"

SUPPORTED_LANGUAGES = [
    "English", "Chinese", "Spanish", "French",
    "Japanese", "Korean", "Arabic", "German", "Portuguese",
]
DEFAULT_LANGUAGE = "English"


# =========================================================
# Model registry
# =========================================================

MODEL_OPTIONS: List[Dict[str, str]] = [
    # ── OpenAI (requires user API key) ───────────────────
    {"id": "gpt-5.4",  "label": "GPT-5.4 (Fast)",    "provider": "OpenAI"},
    {"id": "gpt-5",    "label": "GPT-5 (Powerful)",   "provider": "OpenAI"},
    {"id": "gpt-4o",   "label": "GPT-4o (Efficient)", "provider": "OpenAI"},
    # ── Google Gemini via connectonion (no key needed) ───
    {"id": "co/gemini-3-flash-preview", "label": "Gemini 3 Flash",  "provider": "Google"},
    {"id": "co/gemini-3-pro-preview",   "label": "Gemini 3 Pro",    "provider": "Google"},
    {"id": "co/gemini-2.5-flash",       "label": "Gemini 2.5 Flash","provider": "Google"},
]

SUPPORTED_MODELS: List[str] = [m["id"] for m in MODEL_OPTIONS]
DEFAULT_MODEL  = "co/gemini-3-flash-preview"   # fast, free via connectonion
OPENAI_MODELS: List[str] = [m["id"] for m in MODEL_OPTIONS if m["provider"] == "OpenAI"]


def get_model() -> str:
    model = load_profile().get("preferences", {}).get("model", DEFAULT_MODEL)
    return model if model in SUPPORTED_MODELS else DEFAULT_MODEL


def set_model(model: str) -> bool:
    if model not in SUPPORTED_MODELS:
        return False
    profile = load_profile()
    profile.setdefault("preferences", {})["model"] = model
    save_profile(profile)
    return True


def get_agent_model() -> str:
    """Return the model string for use in Agent(model=...).
    connectonion handles the co/ prefix internally — pass it as-is.
    GPT models use the string directly with the user's OPENAI_API_KEY.
    """
    return get_model()


def requires_api_key(model: str | None = None) -> bool:
    """True only for OpenAI models — co/ models are covered by OPENONION_API_KEY in the bundled .env."""
    return (model or get_model()) in OPENAI_MODELS


# =========================================================
# API key — .env file in app support dir
# =========================================================

def _env_path() -> Path:
    return app_support_dir() / ENV_FILE


def _load_env() -> Dict[str, str]:
    path = _env_path()
    if not path.exists():
        return {}
    result: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        result[key.strip()] = val.strip()
    return result


def _save_env(data: Dict[str, str]) -> None:
    lines = [f"{k}={v}" for k, v in data.items()]
    _env_path().write_text("\n".join(lines) + "\n", encoding="utf-8")


def _bundled_env_path() -> Path:
    """The .env that ships with the backend bundle — contains connectonion keys."""
    return Path(__file__).resolve().parent / ENV_FILE


def load_env_into_os() -> None:
    """Call once at startup — loads env vars in priority order:

    1. Bundled .env  (connectonion keys: AGENT_CONFIG_PATH, OPENONION_API_KEY, etc.)
    2. App-support .env  (user keys: OPENAI_API_KEY written by the frontend)
    3. Real os.environ  (anything already set externally wins over both files)

    Later layers overwrite earlier ones for the same key, but never overwrite
    a value already present in os.environ before this call.
    """
    merged: Dict[str, str] = {}

    # Layer 1 — bundled project .env (connectonion infra keys)
    bundled = _bundled_env_path()
    if bundled.exists():
        for line in bundled.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            merged[k.strip()] = v.strip()

    # Layer 2 — app-support .env (user-supplied OPENAI_API_KEY etc.)
    for k, v in _load_env().items():
        merged[k] = v   # user key overwrites bundled value for the same key name

    # Layer 3 — inject into os.environ, never override pre-existing env vars
    for k, v in merged.items():
        if k not in os.environ:
            os.environ[k] = v


def get_api_key(provider: str = "openai") -> str:
    """Return stored API key for provider, or ''."""
    env_key = f"{provider.upper()}_API_KEY"
    return os.environ.get(env_key) or _load_env().get(env_key, "")


def set_api_key(key: str, provider: str = "openai") -> bool:
    """Persist API key to .env and inject into current process. Returns False if empty."""
    key = key.strip()
    if not key:
        return False
    env_key = f"{provider.upper()}_API_KEY"
    data = _load_env()
    data[env_key] = key
    _save_env(data)
    os.environ[env_key] = key
    return True


def remove_api_key(provider: str = "openai") -> bool:
    env_key = f"{provider.upper()}_API_KEY"
    data = _load_env()
    if env_key not in data:
        return False
    del data[env_key]
    _save_env(data)
    os.environ.pop(env_key, None)
    return True


def has_api_key(provider: str = "openai") -> bool:
    return bool(get_api_key(provider))


# =========================================================
# Paths
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


# =========================================================
# JSON read/write
# =========================================================

def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_store(filename: str, default: Any) -> Any:
    return _read_json(storage_path(filename), default)


def save_store(filename: str, data: Any) -> None:
    _write_json(storage_path(filename), data)


# =========================================================
# Profile
# =========================================================

def _default_profile() -> Dict[str, Any]:
    return {
        "career_area":     "",
        "usage_type":      [],
        "writing_style":   "",
        "onboarding_done": False,
        "text_insertions": [],
        "preferences": {
            "target_language": DEFAULT_LANGUAGE,
            "model":           DEFAULT_MODEL,
        },
        "learned": {
            "description":   "",
            "habits":        [],
            "frequent_apps": [],
            "last_updated":  0,
        },
    }


def load_profile() -> Dict[str, Any]:
    stored   = load_store(PROFILE_FILE, _default_profile())
    defaults = _default_profile()
    changed  = False
    for key, val in defaults.items():
        if key not in stored:
            stored[key] = val
            changed = True
    if "model" not in stored.get("preferences", {}):
        stored.setdefault("preferences", {})["model"] = DEFAULT_MODEL
        changed = True
    if changed:
        save_store(PROFILE_FILE, stored)
    return stored


def save_profile(profile: Dict[str, Any]) -> None:
    save_store(PROFILE_FILE, profile)


def get_target_language() -> str:
    lang = load_profile().get("preferences", {}).get("target_language", DEFAULT_LANGUAGE)
    return lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def set_target_language(language: str) -> bool:
    if language not in SUPPORTED_LANGUAGES:
        return False
    profile = load_profile()
    profile.setdefault("preferences", {})["target_language"] = language
    save_profile(profile)
    return True


# =========================================================
# Dictionary
# =========================================================

def load_dictionary() -> Dict[str, Any]:
    return load_store(DICTIONARY_FILE, {"terms": []})


def apply_dictionary_corrections(text: str) -> str:
    """Regex-based dictionary correction — 0ms, no LLM."""
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
# History
# =========================================================

def load_history() -> Dict[str, Any]:
    return load_store(HISTORY_FILE, {"items": []})


def append_history(item: Dict[str, Any], max_items: int = 200) -> None:
    data  = load_history()
    items = data.get("items", [])
    items.append(item)
    data["items"] = items[-max_items:]
    save_store(HISTORY_FILE, data)


# =========================================================
# Text insertions
# =========================================================

def load_text_insertions() -> list:
    return load_profile().get("text_insertions", [])


def save_text_insertion(label: str, value: str) -> bool:
    label = str(label or "").strip()
    value = str(value or "").strip()
    if not label or not value:
        return False
    profile = load_profile()
    insertions = profile.setdefault("text_insertions", [])
    for item in insertions:
        if item.get("label", "").lower() == label.lower():
            item["value"] = value
            save_profile(profile)
            return True
    insertions.append({"label": label, "value": value})
    save_profile(profile)
    return True


def remove_text_insertion(label: str) -> bool:
    label = str(label or "").strip()
    profile = load_profile()
    before = len(profile.get("text_insertions", []))
    profile["text_insertions"] = [
        i for i in profile.get("text_insertions", [])
        if i.get("label", "").lower() != label.lower()
    ]
    if len(profile["text_insertions"]) < before:
        save_profile(profile)
        return True
    return False