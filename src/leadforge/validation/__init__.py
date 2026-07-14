"""leadforge.validation — RawLead → clean, scored record (README §9, §17).

Turns messy extracted fields into validated ones: field normalizers, a
data-quality score, and the intent-lead assessment the pipeline wires in. Knows
nothing about scraping, sessions, or export formats.
"""

from __future__ import annotations

from leadforge.validation.intent import IntentAssessment, ValidationError, assess_intent_lead
from leadforge.validation.normalizers import (
    is_valid_url,
    normalize_email,
    normalize_phone,
    normalize_url,
    registered_domain,
)
from leadforge.validation.quality import QualityResult, score_intent_lead

__all__ = [
    "IntentAssessment",
    "QualityResult",
    "ValidationError",
    "assess_intent_lead",
    "is_valid_url",
    "normalize_email",
    "normalize_phone",
    "normalize_url",
    "registered_domain",
    "score_intent_lead",
]
