"""Text normalization and cleaning (README §17).

Pure functions targeting the messiness seen in live LinkedIn data: stylized
"math" Unicode, HTML entities, control characters, and emoji. Order matters —
:func:`clean_text` decodes entities, then NFKC-normalizes, then strips control
chars, then collapses whitespace. Emoji are *kept* by ``clean_text`` (post bodies
use them meaningfully) and removed only where a caller asks (e.g. author names).
"""

from __future__ import annotations

import html
import re
import unicodedata

# Control chars except the ordinary whitespace we normalize separately (\t\n\r).
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE_RE = re.compile(r"\s+")

# Emoji, pictographs, symbols, flags, and the joiners/selectors that glue them.
_EMOJI_RE = re.compile(
    "["
    "\U0001f300-\U0001faff"  # symbols, pictographs, emoji, supplemental
    "\U00002600-\U000027bf"  # miscellaneous symbols + dingbats
    "\U0001f1e6-\U0001f1ff"  # regional indicators (flag pairs)
    "\U00002190-\U000021ff"  # arrows
    "\U00002b00-\U00002bff"  # miscellaneous symbols and arrows
    "\U0000fe00-\U0000fe0f"  # variation selectors
    "\U0000200d"  # zero-width joiner
    "\U0000fe0f"  # emoji variation selector
    "]+",
    flags=re.UNICODE,
)


def normalize_unicode(text: str) -> str:
    """NFKC-normalize so stylized letters fold to ASCII (``𝐋𝐨𝐨𝐤𝐢𝐧𝐠`` → ``Looking``)."""
    return unicodedata.normalize("NFKC", text)


def decode_entities(text: str) -> str:
    """Decode HTML entities (``We&#39;re`` → ``We're``, ``&amp;`` → ``&``)."""
    return html.unescape(text)


def strip_control_chars(text: str) -> str:
    """Remove non-printable control characters (keeps ``\\t``/``\\n``/``\\r``)."""
    return _CONTROL_RE.sub("", text)


def collapse_whitespace(text: str) -> str:
    """Collapse runs of whitespace to single spaces and trim the ends."""
    return _WHITESPACE_RE.sub(" ", text).strip()


def strip_emoji(text: str) -> str:
    """Remove emoji / pictographs / flag characters, leaving surrounding text."""
    return _EMOJI_RE.sub("", text)


def clean_text(text: str | None) -> str:
    """Full text-cleaning pipeline; ``None``/empty → ``""``. Emoji are preserved."""
    if not text:
        return ""
    text = decode_entities(text)
    text = normalize_unicode(text)
    text = strip_control_chars(text)
    return collapse_whitespace(text)
