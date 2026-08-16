"""
Minimal translation loader. Deliberately NOT using Python's gettext (.po/.mo
compilation step) -- plain JSON files are trivial for a non-developer, or a
translator with no dev tools, to open and edit directly.

Usage:
    from app.i18n import t, set_language
    set_language("en")
    label.setText(t("products.add_button"))
"""

from __future__ import annotations

import json
from pathlib import Path

LOCALES_DIR = Path(__file__).parent / "locales"

_strings: dict[str, str] = {}
_current_language = "en"


def available_languages() -> list[str]:
    return sorted(p.stem for p in LOCALES_DIR.glob("*.json"))


def set_language(code: str) -> None:
    global _strings, _current_language
    path = LOCALES_DIR / f"{code}.json"
    if not path.exists():
        raise FileNotFoundError(f"No locale file for '{code}' at {path}")
    with open(path, "r", encoding="utf-8") as f:
        _strings = json.load(f)
    _current_language = code


def current_language() -> str:
    return _current_language


def t(key: str, **kwargs) -> str:
    """Look up `key` (dot-notation, e.g. 'products.add_button') and format
    with any kwargs. Falls back to the key itself if missing, so a missing
    translation is obviously visible during development rather than
    crashing or silently showing blank text."""
    value = _strings.get(key, key)
    if kwargs:
        try:
            return value.format(**kwargs)
        except (KeyError, IndexError):
            return value
    return value


# Load English by default so `t()` works immediately without requiring
# every entry point to remember to call set_language() first.
set_language("en")
