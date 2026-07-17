"""Heuristic lead enrichment for intent leads (Phase 8).

Pulls three optional, high-confidence facts out of a lead's post text (and the
author's headline): the poster's ``company``, a public ``contact_email``, and a
``website``. Pure and offline — plain regex plus the shared field normalizers, no
AI, no network. Every extractor returns ``None`` unless the fact is *clearly*
present: a blank beats a guess (fabricated data is worse than a gap, README §17).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from leadforge.scrapers.intent.mapping import company_from_headline
from leadforge.validation.normalizers import normalize_email, normalize_url

# A company-name run: each word starts uppercase (so "Our client" won't match),
# allowing digits, & and dots/hyphens inside (e.g. "Pvt.", "Ltd.", "AT&T").
_COMPANY_WORD = r"[A-Z][A-Za-z0-9&.\-]*"
_COMPANY_NAME = rf"{_COMPANY_WORD}(?:\s+{_COMPANY_WORD}){{0,4}}"

# "Unify Search Solutions Pvt. Ltd. is looking for…" — company as the subject.
_SUBJECT_RE = re.compile(rf"\b({_COMPANY_NAME})\s+is\s+(?:looking|hiring|seeking)\b")
# "we're InstaZorb" / "We are Acme Digital" — self-identification.
_WE_ARE_RE = re.compile(rf"\b[Ww]e(?:'re| are)\s+({_COMPANY_NAME})\b")

# Pronoun/greeting subjects that slip past the capitalization filter but are never
# a company name (rejected as the first word of a match).
_NOT_A_COMPANY = {
    "i", "we", "our", "the", "this", "that", "they", "it", "you",
    "he", "she", "here", "today", "hi", "hey", "hello",
    # hiring/announcement words that follow "we're …" but name no company
    "hiring", "looking", "seeking", "urgent",
}

# Email-ish token; validity is decided by normalize_email, not this pattern.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# A clearly-a-URL token: an explicit http(s):// or a leading www. — anything else
# (a bare "acme.com") is too ambiguous to accept.
_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>()\[\]{}\"']+", re.IGNORECASE)


@dataclass(frozen=True)
class Enrichment:
    """The three optional facts an enrichment pass can add to a lead."""

    company: str | None
    contact_email: str | None
    website: str | None


def enrich_intent_lead(*, post_text: str | None, author_headline: str | None) -> Enrichment:
    """Extract company, contact email, and website from a lead's post + headline."""
    text = post_text or ""
    return Enrichment(
        company=extract_company(text, author_headline),
        contact_email=extract_email(text),
        website=extract_website(text),
    )


def extract_company(post_text: str, author_headline: str | None) -> str | None:
    """The poster's company if clearly stated in the post or headline, else ``None``."""
    return _company_from_post(post_text) or company_from_headline(author_headline)


def extract_email(text: str) -> str | None:
    """The first valid public email in the text, normalized, else ``None``."""
    for candidate in _EMAIL_RE.findall(text):
        email = normalize_email(candidate)
        if email:
            return email
    return None


def extract_website(text: str) -> str | None:
    """The first clearly-a-URL website in the text, normalized, else ``None``."""
    for candidate in _URL_RE.findall(text):
        trimmed = candidate.rstrip(".,);:]}\"'")
        url = trimmed if trimmed.lower().startswith("http") else f"https://{trimmed}"
        normalized = normalize_url(url)
        if normalized:
            return normalized
    return None


def _company_from_post(post_text: str) -> str | None:
    """Company named as a post's subject ("X is hiring") or self-id ("we're X")."""
    for pattern in (_SUBJECT_RE, _WE_ARE_RE):
        match = pattern.search(post_text)
        if match:
            name = match.group(1).strip()
            if name and name.split()[0].lower() not in _NOT_A_COMPANY:
                return name
    return None
