"""leadforge.scoring — intent-lead scoring (README §14, §16, Phase 9).

Rule-based, transparent, configurable. The pipeline calls :func:`score_intent_lead`
to classify a post (client lead vs. job posting) and blend freshness, need-match,
and data-quality into a single ``lead_score``. Every knob lives in
:class:`ScoringConfig`; nothing here talks to the database.
"""

from __future__ import annotations

from leadforge.scoring.classify import ClassifyResult, classify_post
from leadforge.scoring.config import ScoringConfig, load_scoring_config
from leadforge.scoring.freshness import FreshnessResult, freshness_score
from leadforge.scoring.lead_score import LeadScoreResult, score_intent_lead
from leadforge.scoring.need_match import NeedMatchResult, need_match_score

__all__ = [
    "ClassifyResult",
    "FreshnessResult",
    "LeadScoreResult",
    "NeedMatchResult",
    "ScoringConfig",
    "classify_post",
    "freshness_score",
    "load_scoring_config",
    "need_match_score",
    "score_intent_lead",
]
