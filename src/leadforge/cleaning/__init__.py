"""leadforge.cleaning — text/name normalization (README §9, §17).

Pure functions that turn messy raw strings into clean ones; they know nothing
about where the data came from or where it goes.
"""

from __future__ import annotations

from leadforge.cleaning.names import CleanedName, clean_author_name
from leadforge.cleaning.text import (
    clean_text,
    collapse_whitespace,
    decode_entities,
    normalize_unicode,
    strip_control_chars,
    strip_emoji,
)

__all__ = [
    "CleanedName",
    "clean_author_name",
    "clean_text",
    "collapse_whitespace",
    "decode_entities",
    "normalize_unicode",
    "strip_control_chars",
    "strip_emoji",
]
