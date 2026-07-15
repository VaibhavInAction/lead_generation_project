"""Post classification — is this a *client* lead or a *job* posting? (Phase 9).

The single most important filter in the product. LeadForge finds businesses that
want to *hire an agency* (clients); a recruiter posting "we're hiring a Marketing
Manager" is the exact opposite — noise that must be kept out of the outreach list.

We classify ``post_text`` with two keyword/phrase lexicons and a simple rule:

* ``job_posting`` — employer hiring staff. EXCLUDED from results by default.
* ``client_lead`` — someone seeking outside help. KEPT and scored.
* ``unclear``     — neither lexicon matched; shown only on request.

Grounded in real posts we saw live: "URGENT HIRING | Google Ads Expert … to join
our team" → job_posting; "looking for a marketing agency … can anyone recommend"
→ client_lead. No ML — transparent regex signals, listed right here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from leadforge.models.enums import PostCategory

# --- Employer-hiring-for-staff signals (README §14: the noise we exclude) ---
_JOB_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bwe(?:['’]?re| are)\s+hiring\b",
        r"\bnow hiring\b",
        r"\burgent(?:ly)?\s+hiring\b",
        r"\bhiring\b",
        r"\bjoin (?:our|the|my)\b[^.!?\n]*\bteam\b",  # "join our (growing) team"
        r"\bto join us\b",
        r"\bfull[\s-]?time\b",
        r"\bpart[\s-]?time\b",
        r"\bapply (?:now|here|today|online|via|at|using|by)\b",
        r"\b(?:send|submit|share|email|drop)(?:\s+\w+){0,4}\s+(?:cv|résumé|resume)\b",
        r"\b(?:your\s+)?(?:cv|résumé)\b",
        r"\bjob (?:opening|opportunit(?:y|ies)|posting|description|vacanc(?:y|ies))\b",
        r"\bwe(?:['’]?re| are) looking for (?:a|an|our)\b[^.!?\n]*\bto join\b",
        r"\bnew (?:role|position|opening|vacancy)\b",
        r"\bsalary\b",
        r"\b(?:applicants?|candidates?)\b",
    )
)

# --- Client-seeking-outside-help signals (README §14: the leads we keep) ---
_CLIENT_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\blooking for (?:a|an|some)\b[^.!?\n]*"
        r"\b(?:agency|freelancer?|consultant|marketer|expert|specialist|partner|help)\b",
        r"\b(?:marketing|digital|creative|advertising|ad|seo|social(?:[\s-]?media)?"
        r"|ppc|branding|design|web) agency\b",
        r"\b(?:can|does|would|could)\s+anyone\s+recommend\b",
        r"\banyone\s+recommend\b",
        r"\brecommendations?\s+for\s+(?:a|an|any)?\b",
        r"\brecommend (?:a|an|any|me a)\b",
        r"\bneed help with\b",
        r"\b(?:looking to|want to|need to|planning to)\s+outsource\b",
        r"\boutsourc(?:e|ing)\b",
        r"\bneed someone to (?:run|manage|handle|help|do|build|lead)\b",
        r"\bhire (?:a|an)\s+(?:freelance|freelancer|agency|consultant|marketer)\b",
        r"\b(?:freelancer?|consultant)\b",
        r"\bwho (?:can|do you|would you)\s+recommend\b",
        r"\bin search of (?:a|an)\b",
        r"\bseeking (?:a|an)\b[^.!?\n]*\b(?:agency|freelancer?|consultant|partner)\b",
    )
)


@dataclass(frozen=True)
class ClassifyResult:
    """A category plus the signals that fired — transparency, not a black box."""

    category: PostCategory
    job_signals: list[str]
    client_signals: list[str]


def _matches(text: str, patterns: tuple[re.Pattern[str], ...]) -> list[str]:
    """Return each pattern's first matched substring (deduped, order-preserving)."""
    hits: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            token = match.group(0).strip().lower()
            if token not in seen:
                seen.add(token)
                hits.append(token)
    return hits


def classify_post(post_text: str | None) -> ClassifyResult:
    """Classify a post as ``client_lead`` / ``job_posting`` / ``unclear``.

    Rule: whichever lexicon has more distinct hits wins; a tie in which *both*
    fire resolves to ``job_posting`` (we would rather drop an ambiguous
    hiring-flavored post than mail a recruiter). No hits either way → ``unclear``.
    """
    text = post_text or ""
    job = _matches(text, _JOB_PATTERNS)
    client = _matches(text, _CLIENT_PATTERNS)

    if not job and not client:
        category = PostCategory.UNCLEAR
    elif len(client) > len(job):
        category = PostCategory.CLIENT_LEAD
    elif len(job) > len(client):
        category = PostCategory.JOB_POSTING
    else:  # both fired equally — treat the ambiguous hiring-flavored post as a job
        category = PostCategory.JOB_POSTING

    return ClassifyResult(category=category, job_signals=job, client_signals=client)
