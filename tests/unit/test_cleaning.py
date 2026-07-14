"""Text + author-name cleaning against real live-data messiness (README §17, §23)."""

from __future__ import annotations

import pytest

from leadforge.cleaning.names import clean_author_name
from leadforge.cleaning.text import (
    clean_text,
    collapse_whitespace,
    decode_entities,
    normalize_unicode,
    strip_control_chars,
    strip_emoji,
)


class TestText:
    def test_normalize_stylized_math_unicode(self) -> None:
        assert normalize_unicode("𝐋𝐨𝐨𝐤𝐢𝐧𝐠") == "Looking"

    def test_decode_html_entities(self) -> None:
        assert decode_entities("We&#39;re hiring &amp; growing") == "We're hiring & growing"

    def test_collapse_whitespace(self) -> None:
        assert collapse_whitespace("  a\n\t  b   c ") == "a b c"

    def test_strip_control_chars(self) -> None:
        assert strip_control_chars("a\x00b\x07c") == "abc"

    def test_strip_emoji(self) -> None:
        assert strip_emoji("💡 We're hiring 🚀").strip() == "We're hiring"

    def test_clean_text_pipeline_keeps_emoji(self) -> None:
        # Entities decoded, math letters folded, whitespace collapsed — emoji KEPT.
        raw = "💡 We&#39;re looking for a 𝐦𝐚𝐫𝐤𝐞𝐭𝐢𝐧𝐠   manager"
        assert clean_text(raw) == "💡 We're looking for a marketing manager"

    def test_clean_text_none_is_empty(self) -> None:
        assert clean_text(None) == ""


class TestAuthorName:
    def test_strips_trailing_id_fragment(self) -> None:
        name = clean_author_name("Aleea Khan 8aa8977")
        assert name.value == "Aleea Khan"
        assert name.low_confidence is False

    def test_strips_trailing_numeric_id(self) -> None:
        assert clean_author_name("Paul Mccarron 79785053").value == "Paul Mccarron"

    def test_runon_name_kept_but_flagged(self) -> None:
        name = clean_author_name("Amandaglandon")
        assert name.value == "Amandaglandon"  # never guess a split
        assert name.low_confidence is True

    def test_normalizes_and_strips_emoji_from_name(self) -> None:
        name = clean_author_name("🙋‍♀️ 𝐒𝐚𝐫𝐚𝐡 Udaipurwala")
        assert name.value == "Sarah Udaipurwala"
        assert name.low_confidence is False

    def test_plain_name_high_confidence(self) -> None:
        name = clean_author_name("Casey Lee")
        assert name.value == "Casey Lee"
        assert name.low_confidence is False

    def test_emoji_only_name_is_empty_low_confidence(self) -> None:
        name = clean_author_name("🚀🚀")
        assert name.value == ""
        assert name.low_confidence is True

    def test_all_id_token_flagged(self) -> None:
        # No name token remains to anchor a strip; keep but flag.
        name = clean_author_name("8aa8977")
        assert name.value == "8aa8977"
        assert name.low_confidence is True

    @pytest.mark.parametrize("value", ["", "   ", None])
    def test_blank_inputs(self, value: str | None) -> None:
        assert clean_author_name(value).value == ""
