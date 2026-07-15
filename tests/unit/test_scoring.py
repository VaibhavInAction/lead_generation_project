"""Offline scoring tests (README §14, §16, §23).

Grounded in the noisy posts we saw live: an "URGENT HIRING | Google Ads Expert"
post must be classified job_posting and forced to the bottom, while "looking for
a marketing agency … can anyone recommend" must be a high-scoring client_lead.
Pure functions, no DB, no network.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from leadforge.models.enums import PostCategory
from leadforge.scoring import (
    classify_post,
    freshness_score,
    need_match_score,
    score_intent_lead,
)
from leadforge.scoring.config import ScoringConfig, load_scoring_config

CONFIG = ScoringConfig()
NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)

# --- Real posts pulled from production data ---------------------------------

CLIENT_POST = (
    "Looking for a marketing agency to help our D2C brand grow. "
    "Anyone recommend a good one in Mumbai?"
)
HIRING_POST = (
    "URGENT HIRING | Google Ads Expert needed to join our team. "
    "Full-time position, apply now! Send your CV."
)
HIRING_POST_2 = (
    "We're hiring! We're looking for a Marketing Manager to join our growing "
    "team in Denver. Apply now!"
)
CLIENT_FREELANCER = "Need someone to run our Google Ads. Looking for a freelancer or consultant."


class TestClassifyPost:
    def test_client_lead_seeking_agency(self) -> None:
        result = classify_post(CLIENT_POST)
        assert result.category is PostCategory.CLIENT_LEAD
        assert result.client_signals  # at least one signal fired

    def test_urgent_hiring_google_ads_is_job_posting(self) -> None:
        # The canonical noise example — must be excluded, not scored as a client.
        assert classify_post(HIRING_POST).category is PostCategory.JOB_POSTING

    def test_were_hiring_marketing_manager_is_job_posting(self) -> None:
        assert classify_post(HIRING_POST_2).category is PostCategory.JOB_POSTING

    def test_freelancer_ask_is_client_lead(self) -> None:
        assert classify_post(CLIENT_FREELANCER).category is PostCategory.CLIENT_LEAD

    def test_empty_or_bland_is_unclear(self) -> None:
        assert classify_post("").category is PostCategory.UNCLEAR
        assert classify_post("Great weather today in Mumbai.").category is PostCategory.UNCLEAR

    def test_none_does_not_crash(self) -> None:
        assert classify_post(None).category is PostCategory.UNCLEAR


class TestFreshness:
    def test_brand_new_scores_near_100(self) -> None:
        result = freshness_score(posted_at=NOW, first_seen=NOW, now=NOW, config=CONFIG)
        assert result.score == 100
        assert not result.used_fallback

    def test_halves_every_half_life(self) -> None:
        four_days_old = NOW - timedelta(days=CONFIG.freshness_half_life_days)
        result = freshness_score(
            posted_at=four_days_old, first_seen=four_days_old, now=NOW, config=CONFIG
        )
        assert result.score == 50  # one half-life -> half the score

    def test_missing_posted_at_falls_back_with_penalty(self) -> None:
        # No posted_at -> use first_seen, discounted by the fallback penalty.
        result = freshness_score(posted_at=None, first_seen=NOW, now=NOW, config=CONFIG)
        assert result.used_fallback
        assert result.score == round(100 * CONFIG.freshness_fallback_penalty)

    def test_both_timestamps_missing_returns_zero_not_crash(self) -> None:
        result = freshness_score(posted_at=None, first_seen=None, now=NOW, config=CONFIG)
        assert result.score == 0

    def test_naive_timestamp_does_not_crash(self) -> None:
        # SQLite hands back naive datetimes; comparing to an aware `now` must work.
        naive = datetime(2026, 7, 15, 12, 0)  # noqa: DTZ001 — intentional naive value
        result = freshness_score(posted_at=naive, first_seen=naive, now=NOW, config=CONFIG)
        assert result.score == 100

    def test_future_dated_post_clamps_to_fresh(self) -> None:
        future = NOW + timedelta(days=5)
        result = freshness_score(posted_at=future, first_seen=future, now=NOW, config=CONFIG)
        assert result.score == 100


class TestNeedMatch:
    def test_full_phrase_plus_solicitation_scores_high(self) -> None:
        result = need_match_score(
            need_category="marketing agency", post_text=CLIENT_POST, config=CONFIG
        )
        assert result.full_phrase
        assert result.solicited
        assert result.score >= 90

    def test_tangential_mention_scores_lower_than_direct_ask(self) -> None:
        direct = need_match_score(
            need_category="marketing agency", post_text=CLIENT_POST, config=CONFIG
        ).score
        tangential = need_match_score(
            need_category="marketing agency",
            post_text="We offer great marketing services to our customers.",
            config=CONFIG,
        ).score
        assert tangential < direct

    def test_unrelated_post_scores_low(self) -> None:
        result = need_match_score(
            need_category="marketing agency",
            post_text="Loving the new coffee shop downtown.",
            config=CONFIG,
        )
        assert result.score <= CONFIG.need_topic_floor

    def test_missing_need_or_text_is_zero(self) -> None:
        assert need_match_score(need_category=None, post_text="x", config=CONFIG).score == 0
        assert need_match_score(need_category="seo", post_text=None, config=CONFIG).score == 0


class TestScoreIntentLead:
    def _score(self, post: str, need: str, posted_at: datetime | None = NOW):
        return score_intent_lead(
            need_category=need,
            post_text=post,
            posted_at=posted_at,
            first_seen=NOW,
            data_quality_score=80,
            now=NOW,
            config=CONFIG,
        )

    def test_client_lead_scores_high(self) -> None:
        result = self._score(CLIENT_POST, "marketing agency")
        assert result.category is PostCategory.CLIENT_LEAD
        assert result.lead_score >= 70

    def test_job_posting_forced_near_zero(self) -> None:
        result = self._score(HIRING_POST, "Google Ads expert")
        assert result.category is PostCategory.JOB_POSTING
        # Hard rule: no matter how fresh/on-topic, a hiring post is capped near 0.
        assert result.lead_score <= CONFIG.job_posting_score_cap
        assert result.breakdown["job_posting_capped"] is True

    def test_client_beats_job_even_when_job_is_fresher(self) -> None:
        client = self._score(CLIENT_POST, "marketing agency", posted_at=NOW - timedelta(days=3))
        job = self._score(HIRING_POST, "Google Ads expert", posted_at=NOW)  # fresher
        assert client.lead_score > job.lead_score

    def test_breakdown_is_transparent(self) -> None:
        result = self._score(CLIENT_POST, "marketing agency")
        assert set(result.breakdown) >= {"freshness", "need_match", "data_quality", "weights"}


class TestLoadScoringConfig:
    def test_missing_file_returns_defaults(self, tmp_path) -> None:
        assert load_scoring_config(tmp_path / "nope.yaml") == ScoringConfig()

    def test_none_path_returns_defaults(self) -> None:
        assert load_scoring_config(None) == ScoringConfig()

    def test_empty_commented_block_returns_defaults(self, tmp_path) -> None:
        # The shipped scoring.yaml has `scoring:` with every key commented out.
        path = tmp_path / "scoring.yaml"
        path.write_text("scoring:\n", encoding="utf-8")
        assert load_scoring_config(path) == ScoringConfig()

    def test_overrides_applied_from_yaml(self, tmp_path) -> None:
        path = tmp_path / "scoring.yaml"
        path.write_text("scoring:\n  freshness_half_life_days: 2\n", encoding="utf-8")
        assert load_scoring_config(path).freshness_half_life_days == 2.0

    def test_bad_type_raises(self, tmp_path) -> None:
        path = tmp_path / "scoring.yaml"
        path.write_text("scoring:\n  freshness_half_life_days: fast\n", encoding="utf-8")
        with pytest.raises(ValueError, match="must be a number"):
            load_scoring_config(path)

    def test_weights_all_zero_falls_back_to_equal(self) -> None:
        config = ScoringConfig(weight_freshness=0, weight_need_match=0, weight_data_quality=0)
        assert config.normalized_weights() == pytest.approx((1 / 3, 1 / 3, 1 / 3))
