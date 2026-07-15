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


# --- Real production posts: the 7 genuine leads vs. the 8 junk misfires --------
# (author_name, post_text) reconstructed from posts we saw misclassified live.
# GENUINE: a first-person request for outside help → must stay client_lead.
GENUINE_LEADS: list[tuple[str, str]] = [
    (
        "Vedantkantharia",
        "We are looking for a marketing agency to run paid ads for our D2C brand. "
        "Budget is ~$2k/month. DM me if this is your wheelhouse.",
    ),
    (
        "Ehab Kandeel",
        "I'm looking for a freelance video editor for our YouTube channel. "
        "Send me your showreel and rates.",
    ),
    (
        "Tom Payne",
        "We need a social media manager for our SaaS startup — someone to own "
        "content end to end. Message me with your portfolio.",
    ),
    (
        "Beatrice",
        "In need of a branding consultant for our restaurant rebrand. Kindly DM me your portfolio.",
    ),
    (
        "Kartik Kumar",
        "We are seeking an SEO agency to improve our organic traffic. "
        "Happy to share the brief — drop me a message.",
    ),
    (
        "Utsavvijendra",
        "Looking for a PPC expert to manage our Google Ads. "
        "I'm happy to share scope and budget — DM me.",
    ),
    (
        "Taniasawaya",
        "We're looking for a content creator to produce short-form reels for our "
        "restaurant. Send me your portfolio and rates.",
    ),
]

# JUNK: keyword-matches "looking for a marketing agency" etc. but is NOT a lead.
JUNK_POSTS: list[tuple[str, str, PostCategory]] = [
    (
        "Divyankar",
        "One thing I've been thinking about lately: when a business owner looks for "
        "an agency, they rarely know what to ask for.",
        PostCategory.CONTENT_NOISE,
    ),
    (
        "Growthhackers Agency",
        "Why Hire a Marketing Agency? 1. They have experience. 2. They save you time. "
        "3. They bring fresh ideas.",
        PostCategory.COMPETITOR_SELFPROMO,
    ),
    (
        "Pavel",
        "If you're looking for a marketing agency, this article is worth reading — "
        "it breaks down what to watch out for.",
        PostCategory.CONTENT_NOISE,
    ),
    (
        "Nelson",
        "These scammers are getting good. I recently saw one target someone looking "
        "for a marketing agency and nearly pull it off.",
        PostCategory.CONTENT_NOISE,
    ),
    (
        "Zahra",
        "I'm working with an agency looking for a Content Creator to join them on a "
        "3-month contract. Reach out if keen.",
        PostCategory.RECRUITER_STAFFING,
    ),
    (
        "Shauna",
        "We're a boutique creative agency growing our roster of freelance content "
        "creators. If you'd like to be considered, send me a note.",
        PostCategory.RECRUITER_STAFFING,
    ),
    (
        "Randy",
        "We're on the hunt for a content creator to join us at nHabit — freelance "
        "basis, working across a few of our clients.",
        PostCategory.RECRUITER_STAFFING,
    ),
    (
        "Bobgeneraleinteractivemedia",
        "You know those AI-generated posts that flood your feed? Here's why they're "
        "quietly killing your brand.",
        PostCategory.COMPETITOR_SELFPROMO,
    ),
]


class TestClassifyPost:
    @pytest.mark.parametrize("author, post", GENUINE_LEADS)
    def test_genuine_requests_are_client_leads(self, author: str, post: str) -> None:
        result = classify_post(post, author_name=author)
        assert result.category is PostCategory.CLIENT_LEAD, (author, result.signals)

    @pytest.mark.parametrize("author, post, expected", JUNK_POSTS)
    def test_junk_posts_are_not_client_leads(
        self, author: str, post: str, expected: PostCategory
    ) -> None:
        result = classify_post(post, author_name=author)
        assert result.category is not PostCategory.CLIENT_LEAD, (author, result.signals)
        # And it lands in the specific bucket that explains *why* it's junk.
        assert result.category is expected, (author, result.signals)

    def test_seven_genuine_kept_eight_junk_excluded(self) -> None:
        # The headline metric: exactly the 7 real asks survive as client leads.
        kept = [a for a, p in GENUINE_LEADS if classify_post(p, author_name=a).category.is_client]
        dropped = [
            a for a, p, _ in JUNK_POSTS if not classify_post(p, author_name=a).category.is_client
        ]
        assert len(kept) == 7
        assert len(dropped) == 8

    def test_client_lead_seeking_agency(self) -> None:
        result = classify_post(CLIENT_POST)
        assert result.category is PostCategory.CLIENT_LEAD
        assert result.has_request

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
        assert result.lead_score <= CONFIG.non_client_score_cap
        assert result.breakdown["non_client_capped"] is True

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
