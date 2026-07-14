"""Field normalizers: email, phone, URL (README §17).

Standalone, offline, and pure — ready for company ``Lead`` validation (Phase 8+)
and used now for URL validity in intent-lead quality scoring. Each returns a
normalized value or ``None`` when the input is invalid.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import phonenumbers
import tldextract

# Offline extractor: use the bundled public-suffix snapshot, never the network (§23).
_TLD_EXTRACT = tldextract.TLDExtract(suffix_list_urls=())

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Query-param name prefixes we treat as tracking cruft and strip from URLs.
_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "mc_", "ref", "trk", "originaltrk")


def normalize_email(email: str | None) -> str | None:
    """Lower-cased, trimmed email if it passes a basic syntax check, else ``None``."""
    if not email:
        return None
    candidate = email.strip().lower()
    return candidate if _EMAIL_RE.match(candidate) else None


def is_valid_url(url: str | None) -> bool:
    """True if ``url`` has an http(s) scheme and a host."""
    if not url:
        return False
    parts = urlsplit(url.strip())
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def normalize_url(url: str | None) -> str | None:
    """Normalize an http(s) URL: lower-case host, drop tracking params + fragment.

    Returns ``None`` for anything without an http(s) scheme and a host.
    """
    if not url:
        return None
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith(_TRACKING_PREFIXES)
    ]
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, urlencode(kept), ""))


def registered_domain(url: str | None) -> str | None:
    """Registered domain (``example.co.uk``) of a URL, or ``None`` if unresolvable."""
    if not url:
        return None
    return _TLD_EXTRACT(url).top_domain_under_public_suffix or None


def normalize_phone(phone: str | None, *, region: str = "US") -> str | None:
    """Parse and format a phone number to E.164 (``+14155552671``), else ``None``."""
    if not phone:
        return None
    try:
        parsed = phonenumbers.parse(phone, region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
