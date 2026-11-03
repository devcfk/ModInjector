import string

import i18n
import pytest
from i18n import t


def placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


@pytest.mark.parametrize("code", [c for c in i18n.LANGUAGES if c != i18n.DEFAULT_LANGUAGE])
def test_every_language_matches_english(code):
    """Same keys as English, and the same {placeholders} in every text."""
    english, other = i18n.load_catalog(i18n.DEFAULT_LANGUAGE), i18n.load_catalog(code)
    assert english, "English catalog not found"
    assert set(other) == set(english)
    for key, text in english.items():
        assert placeholders(other[key]) == placeholders(text), key


def test_translation_and_placeholders():
    i18n.set_language("fr")
    assert t("tab.settings") == "Paramètres"
    assert t("status.up_to_date", count=3) == "✔ À jour : 3 mod(s) déployé(s)."
    i18n.set_language("en")
    assert t("status.up_to_date", count=3) == "✔ Up to date: 3 mod(s) deployed."


def test_fallbacks(monkeypatch):
    i18n.set_language("xx")  # Unknown language -> English
    assert i18n.get_language() == "en"
    monkeypatch.setitem(i18n._catalogs, "fr", {})
    i18n.set_language("fr")
    assert t("tab.settings") == "Settings"  # Missing in French -> English
    assert t("no.such.key") == "no.such.key"


def test_auto_follows_system_language(monkeypatch):
    monkeypatch.setattr(i18n, "detect_system_language", lambda: "fr")
    i18n.set_language(i18n.AUTO)
    assert i18n.get_language() == "fr"


def test_build_bundles_the_locales():
    """The executable reads the texts from locales/: PyInstaller must ship that folder."""
    build_script = (i18n.LOCALES_DIR.parents[2] / "scripts" / "build.py").read_text(encoding="utf-8")
    assert "'locales'};locales" in build_script
