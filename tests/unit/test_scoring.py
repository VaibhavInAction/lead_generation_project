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
# "Join our <anything> Team" — a role to join, not a client asking for help.
JOIN_TEAM_POST = (
    "Join our Marketing Team! We're looking for a Social Media Manager to help "
    "scale our brand."
)
# Advice *about* job postings — commentary, not a request for an agency.
ADVICE_POST = (
    "Watch out for this BIG red flag in job postings. Seen a manager role reposted "
    "5x? DM me your worst examples."
)
# Testimonial — the author already hired someone and is praising them.
TESTIMONIAL_POST = (
    "I love working with value-aligned people. So when I met Shena, I instantly "
    "knew that I wanted to work with her. Shena is so special because she gets it."
)
# Personal journey narrative — a life story, not a request for help.
STORY_POST = (
    "I survived a trauma that almost took my life.. Yesterday I sat down reflecting "
    "on my journey. 2022: I came to the online space. I was into affiliate marketing."
)


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


# --- The 19 gold-standard leads (docs/example_leads.md) -----------------------
# Real posts Digital Nil collected by hand: businesses publicly looking to hire or
# partner with an *agency*. Every one MUST classify as client_lead — this list is
# the product's acceptance bar, so a regression here is a regression in the tool.
GOLD_STANDARD_LEADS: list[tuple[str, str]] = [
    (
        "Zoya Irfan",
        "We're Hiring: Performance Marketing Agency\n\n"
        "We're looking to partner with an experienced Performance Marketing Agency "
        "for the digital launch of an upcoming residential real estate project in "
        "Gurugram. Requirements: Google Ads, Meta Ads, Lead Generation, Performance "
        "Campaign Management, Proven Real Estate Experience.\n"
        "Interested agencies, please share your company profile, real estate "
        "portfolio, case studies, and commercials via DM or email.\n"
        "#PerformanceMarketing #RealEstateMarketing #AgencyHiring #Gurugram",
    ),
    (
        "Vivek P. Bajaj",
        "We are currently looking to partner with top-tier agencies to drive the next "
        "phase of growth and brand visibility for Clover Builders.\n"
        "I am looking out for agencies that specialize in: 1. Performance Marketing: "
        "ROI-driven campaigns 2. Creative & Media\n"
        "Mandatory Requirement: Proven, prior experience in the real estate sector.\n"
        "You can mail me at vivek.bajaj@cloverbuilders.com with your portfolio and "
        "relevant case studies.",
    ),
    (
        "Isaac Andrew",
        "Calling All Digital Marketing Agencies | Immediate Onboarding for F&B Brand\n\n"
        "We're scaling up and looking for a powerhouse Digital Marketing Agency ready "
        "to hit the ground running. If your agency knows how to make F&B brands go "
        "viral, we want to partner with you.\n"
        "How to Apply / Pitch: Tag your agency in the comments below. DM us directly "
        "with a brief portfolio or your top 3 F&B case studies.\n"
        "#HiringAnAgency #AgencyPitch",
    ),
    (
        "Rhea Guliani",
        "Looking for branding agencies specialising in B2B and industrial sectors, "
        "with experience in creating scalable, standardised visual systems.\n"
        "Please email your portfolio to rheag@aehrmediahouse.com",
    ),
    (
        "Vani Dhaka",
        "We're looking for a marketing agency to partner with us for the launch and "
        "growth of CalmForge. We're looking for an agency with proven expertise in: "
        "Performance Marketing (Meta & Google Ads), Brand Strategy & Positioning.\n"
        "Please send your pitch deck, relevant case studies, client portfolio, and "
        "proposed approach to: calmforge.wellness@gmail.com\n"
        "#Hiring #MarketingAgency #PerformanceMarketing #D2C",
    ),
    (
        "Inderpreet Kaur",
        "Looking for a Retail Digital Growth Partner\n"
        "DRYCO is looking for a results-driven agency to help grow sales across our "
        "retail stores. We're looking for expertise in: Google Business Profile "
        "optimization, Local SEO, Google & Meta Ads, Instagram/Facebook content.\n"
        "If you have proven experience scaling multi-location retail brands, please "
        "DM me your case studies.\n"
        "Fellow LinkedIn connections: If you know a great agency or consultant, "
        "please tag them in the comments.",
    ),
    (
        "Atharva Patil",
        "We're looking for agency partners as Malgudi scales up across Mumbai and the "
        "UAE. We're on the lookout for the right partners. We're looking for an agency "
        "that can own a campaign end to end.\n"
        "If this sounds like your agency, or you know one that fits the bill, send me "
        "a DM. #AgencySearch #MarketingPartnership",
    ),
    (
        "Heena Hariawala",
        "Looking for a Performance Marketing Agency\n"
        "We're looking for a results-driven performance marketing agency with a proven "
        "track record of scaling D2C/e-commerce brands. Expertise required: Meta Ads, "
        "Google Ads, Creative strategy & CRO, ROAS-focused growth.\n"
        "We're looking for a long-term growth partner, not just an agency that manages "
        "campaigns. Please DM me or share your agency profile and case studies.",
    ),
    (
        "Rushil Bhardwaj",
        "I am looking for a Goa-based social media agency with proven expertise in "
        "marketing F&B brands, restaurants, bars or microbreweries.\n"
        "If your agency has a strong portfolio or you know someone who does, please "
        "tag them in the comments or send me a DM.",
    ),
    (
        "Aman raj chaurasiya",
        "Looking for a Creative Social Media & Digital Marketing Agency!\n"
        "As Growbro.ai continues to scale, we're looking for a long-term agency partner "
        "that can help us build one of the strongest AI brands in India.\n"
        "Please email your company profile, portfolio, case studies, pricing, and "
        "previous work to partnership@growbro.ai",
    ),
    (
        "Dhanushka Fernando",
        "FINEZ is planning to appoint a top-tier Performance Marketing Agency to lead "
        "our digital growth strategy for our furniture and interiors range.\n"
        "If you've worked with an agency that consistently delivers outstanding "
        "results, please tag them in the comments.",
    ),
    (
        "Naren Kholiya",
        "We at Pristyn Care are looking to partner with the best AEO/GEO experts & "
        "agencies. We're open to multiple engagement models, including pilot, "
        "project-based, retainer, fractional, contractual, or performance-linked.\n"
        "If this sounds like you, drop a comment or DM me with relevant case studies.",
    ),
    (
        "Sibbi Vinod Nair",
        "Looking for a Social Media Marketing Agency\n"
        "We're looking for a B2B-focused Social Media Marketing Agency to partner with "
        "us at Credeksa. If your agency has experience working with B2B, HR, "
        "Recruitment or SaaS brands, email: vendors@credeksa.com",
    ),
    (
        "Karthik Maragalale",
        "I am looking for an experienced SEO agency to help improve our organic "
        "visibility, search rankings, and generate qualified B2B leads for Desapex.\n"
        "Share your company profile and case studies via email at marketing@desapex.com",
    ),
    (
        "Saiteja Girnala",
        "We're looking for a #digitalmarketingagency in #Hyderabad. We're looking for "
        "the right agency partner to work alongside our existing in-house digital team.\n"
        "Think your agency is the right fit? Mail us at marketing@dakshinstories.com\n"
        "Or tag an agency you'd recommend!",
    ),
    (
        "Ankita Jain",
        "Looking for Performance-Based Influencer Agencies!\n"
        "We're scaling GoPaisa Instant Money and want to partner with influencer "
        "marketing agencies who are ready to work on a performance model.",
    ),
    (
        "Ramadhan Eka Putra",
        "Looking for an AI video production agency! Need a team that can move fast and "
        "has experience producing AI-generated video content for FMCG brands.\n"
        "If you've worked with FMCG clients before, please send me your portfolio via DM.",
    ),
    (
        "Sunita Pradhan",
        "Looking for a Digital Marketing Agency\n"
        "We are looking to connect with digital marketing agencies experienced in "
        "managing and promoting GIG profiles and platforms. If you have relevant "
        "experience and expertise, share your company profile with us.",
    ),
    (
        "Aastha Jha",
        "We're looking for an agency that can help us answer that. Not just with "
        "performance marketing, but with ideas.\n"
        "If you've built brands people remember, we'd love to see your work. DM me or "
        "tag someone who should be in this conversation.",
    ),
]

# Genuine *staff* hiring — the over-correction guard for the agency-hiring fix.
# These must stay job_posting even after "hiring an agency" is allowed through.
STAFF_JOB_POSTS: list[tuple[str, str]] = [
    (
        "Priya Menon",
        "We're hiring a Marketing Manager to join our team in Bangalore. Full-time, "
        "competitive salary. Apply now!",
    ),
    (
        "Rohit Sharma",
        "We're hiring! Looking for a Performance Marketing Specialist to join us. "
        "Send your CV to careers@example.com",
    ),
    (
        "Anita Desai",
        "New role: Social Media Executive. Full-time position with benefits package. "
        "Interested candidates, apply here.",
    ),
]


# --- Rhetorical sales hooks: the "?" family seen live -------------------------
# All three reached the outreach list as client_lead. Same root cause: a request
# phrase aimed at the *reader* and closed with a question mark is an ad, not an
# ask. A genuine buyer states a need ("looking for an agency to help us"); an
# advertiser asks one ("Looking for an agency? Meet us!").
SALES_HOOK_POSTS: list[tuple[str, str, PostCategory]] = [
    (
        "Middle East Event Show",
        "Looking for a Social Media Agency that understands events? Meet xNDigitize "
        "at the Middle East Event Show!",
        PostCategory.COMPETITOR_SELFPROMO,
    ),
    (
        "Hannah Silverstein",
        "Looking for a Brand Strategist or Creative Consultant? I'm open to work, "
        "seeking my next role (ideally FT)",
        PostCategory.COMPETITOR_SELFPROMO,
    ),
    (
        "Estherokunfolami",
        "Good morning, Happy wednesday. Sharing more of the Kitho website, this is "
        "the profile setup screen where users can set up their profile.",
        PostCategory.CONTENT_NOISE,
    ),
    # The same showcase shape as above, with the CTA tail that made it look like a
    # request: a designer presenting work and inviting DMs is still not a buyer.
    (
        "Estherokunfolami",
        "Good morning, Happy Wednesday. Sharing more of the Kitho website, this is "
        "the profile setup screen. Recent work from my portfolio — DM me if you need "
        "a designer for your next project.",
        PostCategory.COMPETITOR_SELFPROMO,
    ),
    (
        "Adverto Digital",
        "Need more leads? We can help. Book a call with our team today.",
        PostCategory.COMPETITOR_SELFPROMO,
    ),
    (
        "Freelance Dev",
        "Available for hire — taking on new clients this quarter. Hire me for your "
        "next website build. DM me.",
        PostCategory.COMPETITOR_SELFPROMO,
    ),
]

# A greeting opener is normal politeness above a real ask — it must not suppress
# the lead. Guards the "greeting only counts when nothing is requested" rule.
GREETING_LEADS: list[tuple[str, str]] = [
    (
        "Ravi Sharma",
        "Good morning everyone! We're looking for a marketing agency to help with "
        "our D2C launch. DM me your case studies.",
    ),
    (
        "Priya N",
        "Happy Monday! Looking for a branding agency for our rebrand. Mail us at p@x.com",
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

    @pytest.mark.parametrize("author, post", GOLD_STANDARD_LEADS)
    def test_gold_standard_leads_are_client_leads(self, author: str, post: str) -> None:
        # docs/example_leads.md — the agency's hand-picked bar. All 19 must pass.
        result = classify_post(post, author_name=author)
        assert result.category is PostCategory.CLIENT_LEAD, (author, result.signals)

    def test_all_nineteen_gold_standard_leads_survive(self) -> None:
        kept = [
            a for a, p in GOLD_STANDARD_LEADS if classify_post(p, author_name=a).category.is_client
        ]
        assert len(kept) == 19, [a for a, _ in GOLD_STANDARD_LEADS if a not in kept]

    @pytest.mark.parametrize("author, post, expected", SALES_HOOK_POSTS)
    def test_rhetorical_sales_hooks_are_not_client_leads(
        self, author: str, post: str, expected: PostCategory
    ) -> None:
        # Live false positives: an ad, a job seeker, and a portfolio showcase.
        result = classify_post(post, author_name=author)
        assert result.category is not PostCategory.CLIENT_LEAD, (author, result.signals)
        assert result.category is expected, (author, result.signals)

    @pytest.mark.parametrize("author, post", GREETING_LEADS)
    def test_greeting_opener_does_not_suppress_a_real_ask(self, author: str, post: str) -> None:
        # "Good morning!" above a genuine request is politeness, not chit-chat.
        result = classify_post(post, author_name=author)
        assert result.category is PostCategory.CLIENT_LEAD, (author, result.signals)

    def test_question_mark_separates_an_ad_from_an_ask(self) -> None:
        # The rule in one pair: same words, different punctuation, opposite verdict.
        ad = classify_post("Looking for a marketing agency? Meet us at stand 12!")
        ask = classify_post("Looking for a marketing agency to help us launch. DM me.")
        assert ad.category is PostCategory.COMPETITOR_SELFPROMO, ad.signals
        assert ask.category is PostCategory.CLIENT_LEAD, ask.signals

    @pytest.mark.parametrize("author, post", STAFF_JOB_POSTS)
    def test_staff_hiring_is_still_job_posting(self, author: str, post: str) -> None:
        # Guard against over-correcting the agency-hiring fix: hiring *people*
        # (join our team / full-time / apply now / send CV / a role title) is a job ad.
        result = classify_post(post, author_name=author)
        assert result.category is PostCategory.JOB_POSTING, (author, result.signals)

    def test_hiring_an_agency_is_a_client_lead_not_a_job_posting(self) -> None:
        # "We're Hiring" + an *agency* as the object hired — the headline bug.
        result = classify_post(
            "We're Hiring: Performance Marketing Agency. We're looking to partner "
            "with an experienced agency for our launch."
        )
        assert result.category is PostCategory.CLIENT_LEAD, result.signals

    def test_staff_hiring_wins_even_when_an_agency_is_mentioned(self) -> None:
        # The exemption must not rescue a real job ad that happens to say "agency".
        result = classify_post(
            "We're hiring a Marketing Manager to join our agency. Full-time, apply now!"
        )
        assert result.category is PostCategory.JOB_POSTING, result.signals

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

    def test_join_our_marketing_team_is_recruiter(self) -> None:
        # "join our <anything> team" must trip the recruiter rule, not read as a client.
        result = classify_post(JOIN_TEAM_POST, author_name="Once Upon A Farm")
        assert result.category is PostCategory.RECRUITER_STAFFING, result.signals

    def test_advice_about_job_postings_is_content_noise(self) -> None:
        # Advice opener ("watch out for") is commentary — not a request for help.
        result = classify_post(ADVICE_POST, author_name="Davidloughney")
        assert result.category is PostCategory.CONTENT_NOISE, result.signals

    def test_testimonial_is_content_noise(self) -> None:
        # Praise for someone already hired — not a client seeking help.
        result = classify_post(TESTIMONIAL_POST, author_name="Jayamallik")
        assert result.category is PostCategory.CONTENT_NOISE, result.signals

    def test_personal_story_is_content_noise(self) -> None:
        # A life-journey narrative — storytelling, not a request.
        result = classify_post(STORY_POST, author_name="Oche Blessing")
        assert result.category is PostCategory.CONTENT_NOISE, result.signals

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
