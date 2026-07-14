"""Author-name cleanup (README §17).

Handles the two name defects seen in live data without ever *guessing*:

* trailing ID fragments — ``"Aleea Khan 8aa8977"`` → ``"Aleea Khan"`` (drop
  trailing tokens that contain digits, provided a real name token remains);
* run-on names — ``"Amandaglandon"`` is left untouched but flagged
  ``low_confidence`` (we never invent a first/last split we can't verify).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from leadforge.cleaning.text import clean_text, strip_emoji

_HAS_DIGIT = re.compile(r"\d")
# A single token this long is almost certainly two names run together.
_RUNON_MIN_LEN = 12


@dataclass(frozen=True)
class CleanedName:
    """A cleaned author name plus whether it should be trusted."""

    value: str
    low_confidence: bool


def clean_author_name(name: str | None) -> CleanedName:
    """Clean an author name; emoji removed, ID fragments stripped, doubt flagged."""
    text = " ".join(strip_emoji(clean_text(name)).split())
    if not text:
        return CleanedName("", low_confidence=True)

    tokens = text.split(" ")
    # Drop trailing ID-like tokens (contain a digit) while a name token remains.
    while len(tokens) > 1 and _HAS_DIGIT.search(tokens[-1]):
        tokens.pop()
    cleaned = " ".join(tokens)

    return CleanedName(cleaned, low_confidence=_is_low_confidence(cleaned, tokens))


def _is_low_confidence(cleaned: str, tokens: list[str]) -> bool:
    """A name is low-confidence if empty, still digit-bearing, or a run-on single token."""
    if not cleaned:
        return True
    if _HAS_DIGIT.search(cleaned):  # e.g. an all-ID token we couldn't strip
        return True
    return len(tokens) == 1 and len(cleaned) >= _RUNON_MIN_LEN
