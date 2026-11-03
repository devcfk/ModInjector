"""
Translations of the user-facing text.

Texts live in locales/<code>.json (one flat {key: text} object per language) and are looked up with
t("key", **values), which fills the {placeholders} with str.format. English is the reference
language: a key missing from another language falls back to English, then to the key itself.
"""

import ctypes
import json
import locale
import sys
from pathlib import Path

DEFAULT_LANGUAGE = "en"
AUTO = "auto"
# Language code -> name shown in the language selector (always in its own language)
LANGUAGES = {"en": "English", "fr": "Français"}

# Next to this file from source, inside the PyInstaller bundle once frozen
LOCALES_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "locales"

_catalogs: dict[str, dict[str, str]] = {}
_language = DEFAULT_LANGUAGE


def load_catalog(code: str) -> dict[str, str]:
    if code not in _catalogs:
        try:
            with open(LOCALES_DIR / f"{code}.json", encoding="utf-8") as f:
                _catalogs[code] = json.load(f)
        except OSError, ValueError:
            _catalogs[code] = {}
    return _catalogs[code]


def detect_system_language() -> str:
    """Return the code of the Windows display language if it is supported, else English."""
    names = []
    try:
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()  # type: ignore[attr-defined]
        names.append(locale.windows_locale.get(lang_id, ""))
    except AttributeError, OSError:
        pass  # Not on Windows
    names.append(locale.getlocale()[0] or "")
    for name in names:
        code = name[:2].lower()
        if code in LANGUAGES:
            return code
        # Windows may report names such as "French_France"
        for lang_code, lang_name in (("fr", "french"), ("en", "english")):
            if name.lower().startswith(lang_name):
                return lang_code
    return DEFAULT_LANGUAGE


def set_language(code: str) -> None:
    """Select the language ("auto" follows Windows). Unknown codes fall back to English."""
    global _language
    if code == AUTO:
        code = detect_system_language()
    _language = code if code in LANGUAGES else DEFAULT_LANGUAGE


def get_language() -> str:
    return _language


def t(key: str, **values) -> str:
    text = load_catalog(_language).get(key) or load_catalog(DEFAULT_LANGUAGE).get(key) or key
    return text.format(**values) if values else text


set_language(AUTO)
