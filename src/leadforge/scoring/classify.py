"""Post classification — is this a genuine *client request*, or noise? (Phase 9).

The single most important filter in the product. LeadForge finds businesses that
publicly *ask* for outside help (clients); everything else — recruiters staffing
roles, agencies self-promoting, opinion posts, article shares — is noise that
must stay out of the outreach list.

Keyword matching alone can't tell a REQUEST from COMMENTARY: "looking for a
marketing agency" appears verbatim in a real ask, in an article share ("if you're
looking for a marketing agency, this article is worth reading"), and in an
anecdote ("these scammers target someone looking for a marketing agency"). So the
rule is two-sided and dependency-free (no AI):

    client_lead  ⟺  a first-person REQUEST (+ a target)  AND  no strong junk signal

Junk signals are checked first, in precedence order, and each names *why* the post
is not a lead:

* ``job_posting``          — classic employer hiring (hiring / apply now / full-time).
* ``recruiter_staffing``   — a role to *join* an agency/its clients (freelance bench).
* ``competitor_selfpromo`` — an agency promoting itself (company author, listicle).
* ``content_noise``        — opinion opener, article share, or story/anecdote.

Only if none of those fire and a genuine first-person request is present does a
post become ``client_lead``; a request-less, junk-less post is ``unclear``.
Grounded in real posts we saw misclassified live (see tests/unit/test_scoring.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from leadforge.models.enums import PostCategory


def _compile(*patterns: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, re.IGNORECASE) for p in patterns)


# --- First-person REQUEST for help (the positive signal) --------------------
# Either an explicit "we/I are looking for / need / seeking …", or a
# sentence-initial "Looking for a …" (implied first person). Deliberately NOT
# matched: "if you're looking for", "someone looking for", "when a business owner
# looks for" — those are second/third person and are commentary, not a request.
_REQUEST = _compile(
    r"\b(?:we(?:['’]?re| are)|i(?:['’]?m| am))\s+(?:currently\s+|now\s+)?"
    r"(?:looking for|searching for|on the hunt for|in the market for|seeking|after)\b",
    r"\b(?:we|i)\s+(?:need|require|want)\b",
    r"\bin need of\b",
    r"\bcalling for (?:a|an)\b",
    r"(?:^|[.!?\n]\s*)(?:looking for|searching for|seeking)\s+(?:a|an|some|our)\b",
    r"(?:^|[.!?\n]\s*)need (?:a|an|someone|help)\b",
)

# A concrete thing being asked for — a request needs a target to be a lead
# ("we need a coffee" is not). Broad on purpose; need-match scores the fit later.
_TARGET = _compile(
    r"\b(?:agenc(?:y|ies)|freelancers?|contractors?|consultants?|marketers?|"
    r"strateg(?:ist|ists|y)|specialists?|experts?|editors?|designers?|developers?|"
    r"writers?|creators?|managers?|help|partner|vendor|support|someone)\b",
)

# Call-to-action that reinforces a genuine ask (used with a target present).
_CTA = _compile(
    r"\b(?:dm|pm|message|ping|contact|email|inbox)\s+me\b",
    r"\bkindly\s+dm\b",
    r"\bdrop me a (?:message|line|note)\b",
    r"\bsend (?:me )?(?:your |a )?(?:portfolio|showreel|reel|resume|cv|note|rates|proposal)\b",
    r"\bif you(?:'d| would) like to be considered\b",
    r"\bhappy to share (?:the )?(?:scope|budget|brief|details)\b",
)

# --- job_posting: classic employer hiring staff -----------------------------
_JOB = _compile(
    r"\b(?:we(?:['’]?re| are)\s+|now\s+|urgent(?:ly)?\s+)?hiring\b",
    r"\bapply (?:now|here|today|online|via|at|using|by|through)\b",
    r"\bfull[\s-]?time\b",
    r"\bpart[\s-]?time\b",
    r"\bsalary\b",
    r"\bbenefits package\b",
    r"\b(?:applicants?|candidates?)\b",
    r"\bjob (?:opening|opportunit(?:y|ies)|posting|description|vacanc(?:y|ies))\b",
    r"\bnew (?:role|position|opening|vacancy)\b",
    r"\b(?:send|submit|share|email|drop)(?:\s+\w+){0,4}\s+(?:cv|résumé|resume)\b",
    r"\bwe(?:['’]?re| are) looking for (?:a|an|our)\b[^.!?\n]*\bto join (?:our|the|us|my)\b",
)

# --- recruiter_staffing: a role to *join* an agency / its client bench -------
_RECRUITER = _compile(
    r"\bto join (?:us|them|our|the|my)\b",
    r"\blooking for (?:a|an)\b[^.!?\n]*\bto join\b",  # "…a Content Creator to join them"
    r"\bjoin (?:our|the|my)(?:\s+\w+){0,3}\s+team\b",  # "join our [growing/Marketing] team"
    r"\bjoin (?:us|them)\b",
    r"\bcome join\b",
    r"\b(?:on a |work(?:ing)? on a )?freelance basis\b",
    r"\bworking across\b[^.!?\n]*\bclients?\b",
    r"\bgrowing our (?:roster|network|bench|team)\b",
    r"\b(?:add to|expand|grow)\b[^.!?\n]*\b(?:roster|bench)\b",
    r"\bour (?:roster|bench|talent pool)\b",
    r"@[a-z0-9.-]*(?:talent|recruit|staffing|hire|jobs)[a-z0-9.-]*\.",
)

# --- competitor_selfpromo: an agency marketing itself -----------------------
# (a) the *author* is a company/agency, not a person; (b) generic promo/listicle.
_COMPANY_NAME = _compile(
    r"agenc(?:y|ies)|media|studio|marketing|consult(?:ing|ancy)?|digital|"
    r"solutions|talent|labs|interactive|creative co\b|collective",
)
_SELFPROMO = _compile(
    r"\bwhy (?:hire|choose|work with|you (?:need|should))\b",
    r"\bhow to (?:find|choose|hire|pick|select|vet)\b[^.!?\n]*\b(?:the right|a|an|your)\b",
    r"\b\d+\s+(?:reasons|benefits|signs|tips|ways|things)\b",
    r"\btop\s+\d+\b",
    r"\bbenefits of (?:hiring|working with|outsourcing to)\b",
    r"\bhere are (?:the|\d+)\b",
)

# --- content_noise: opinion, article share, story/anecdote ------------------
_CONTENT_NOISE = _compile(
    # opinion / rhetorical openers
    r"\bone thing i(?:['’]ve| have) been thinking\b",
    r"\byou know (?:those|that|when)\b",
    r"\bhere['’]s why\b",
    r"\bwhen a (?:business owner|company|founder|client)\b",
    r"\b(?:hot take|unpopular opinion|controversial opinion)\b",
    r"\blet['’]s talk about\b",
    r"\bever wonder(?:ed)?\b",
    r"\bthink about it\b",
    # advice / commentary openers — teaching *about* a topic, not requesting help
    r"\bwatch out for\b",
    r"\bpro tip\b",
    r"\bhere['’]s what\b",
    r"\bstop doing\b",
    # article shares
    r"\bthis article\b",
    r"\bworth (?:a )?read(?:ing)?\b",
    r"\bread (?:the|this|my|our) (?:article|full|blog|post|piece|breakdown)\b",
    r"\breviewed (?:seven|eight|nine|ten|\d+|several|some)\b",
    r"\bcheck out (?:this|my|our) (?:article|blog|post|piece|guide)\b",
    r"\blink in (?:the )?comments\b",
    r"\b(?:new|latest) (?:blog|post|article|newsletter)\b",
    r"\bjust (?:published|wrote|posted)\b",
    # story / anecdote
    r"\bi recently (?:received|got|saw|came across)\b",
    r"\bthese scammers\b",
    r"\b(?:true story|storytime|story time)\b",
    r"\ba (?:client|friend|founder) (?:once|recently)\b",
    # testimonial / appreciation — already worked with someone, not seeking help
    r"\bwhen i met\b",
    r"\bwanted to work with (?:her|him|them)\b",
    r"\bis so special\b",
    r"\bso grateful (?:to|for)\b",
    r"\bshout[\s-]?out to\b",
    r"\bhighly recommend working with\b",
    r"\bhad the pleasure of working\b",
    # personal story / journey narrative
    r"\bi survived\b",
    r"\bmy journey\b",
    r"\bsat down reflecting\b",
    r"\b20\d{2}:",  # "2022:" year-marker storytelling
    r"\bin 20\d{2} i\b",
)


@dataclass(frozen=True)
class ClassifyResult:
    """A category plus the signals that fired — transparency, not a black box."""

    category: PostCategory
    has_request: bool
    signals: dict[str, list[str]] = field(default_factory=dict)


def _hits(text: str, patterns: tuple[re.Pattern[str], ...]) -> list[str]:
    """Each pattern's first matched substring (deduped, order-preserving)."""
    found: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            token = " ".join(match.group(0).split()).strip().lower()
            if token and token not in seen:
                seen.add(token)
                found.append(token)
    return found


def classify_post(post_text: str | None, *, author_name: str | None = None) -> ClassifyResult:
    """Classify a post into a :class:`PostCategory`.

    Junk signals are tested first, in precedence order, so a hiring post that also
    says "join our team" stays ``job_posting`` and a recruiter ask that also reads
    like an article stays ``recruiter_staffing``. A post survives as ``client_lead``
    only when it carries a first-person request *and* a target *and* trips no junk
    signal; a request-less, junk-less post is ``unclear``.
    """
    text = post_text or ""
    name = author_name or ""

    job = _hits(text, _JOB)
    recruiter = _hits(text, _RECRUITER)
    company_author = _hits(name, _COMPANY_NAME)
    selfpromo = _hits(text, _SELFPROMO)
    noise = _hits(text, _CONTENT_NOISE)

    request = _hits(text, _REQUEST)
    target = _hits(text, _TARGET)
    cta = _hits(text, _CTA)
    # A request needs a target; a CTA alongside a target also reads as a genuine ask.
    has_request = bool(request and target) or bool(cta and target)

    signals: dict[str, list[str]] = {
        "request": request,
        "target": target,
        "cta": cta,
        "job": job,
        "recruiter": recruiter,
        "company_author": company_author,
        "selfpromo": selfpromo,
        "content_noise": noise,
    }

    # Precedence: strongest / most specific junk first.
    if job:
        category = PostCategory.JOB_POSTING
    elif recruiter:
        category = PostCategory.RECRUITER_STAFFING
    elif company_author or selfpromo:
        category = PostCategory.COMPETITOR_SELFPROMO
    elif noise:
        category = PostCategory.CONTENT_NOISE
    elif has_request:
        category = PostCategory.CLIENT_LEAD
    else:
        category = PostCategory.UNCLEAR

    return ClassifyResult(category=category, has_request=has_request, signals=signals)
