"""Search-query construction for intent mining (README §13.1).

Turns the ``--need`` value plus the phrase templates in ``intent_queries.yaml``
into concrete search queries, with an engine-specific recency filter derived from
``--since`` (intent decays in days, so freshness is not optional). Helpers here
are shared across engines: :func:`recency_code` for DuckDuckGo's ``df`` param and
:func:`brave_freshness` for the Brave API's ``freshness`` param.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlencode

import yaml

# DuckDuckGo HTML endpoint — the most scraper-tolerant of the engines (README §13.1).
DDG_HTML_ENDPOINT = "https://html.duckduckgo.com/html/"

_SINCE_RE = re.compile(r"^\s*(\d+)\s*([dwmy])\s*$", re.IGNORECASE)


def load_query_templates(path: str | Path) -> list[str]:
    """Load phrase templates from ``intent_queries.yaml``.

    Raises ``FileNotFoundError`` if missing and ``ValueError`` if the file has no
    non-empty ``templates`` list — a silent empty list would mine nothing.
    """
    text = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    templates = data.get("templates") or []
    if not isinstance(templates, list) or not all(isinstance(t, str) for t in templates):
        raise ValueError(f"{path}: 'templates' must be a non-empty list of strings")
    if not templates:
        raise ValueError(f"{path}: no query templates defined")
    return templates


def load_needs(path: str | Path) -> list[str]:
    """Load the agency's target service keywords from ``needs.yaml`` (README §14).

    Returns a cleaned, order-preserving, case-insensitively de-duplicated list.
    Raises ``FileNotFoundError`` if the file is missing and ``ValueError`` if it
    has no usable ``needs`` list.
    """
    text = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    raw = data.get("needs")
    if not isinstance(raw, list) or not all(isinstance(n, str) for n in raw):
        raise ValueError(f"{path}: 'needs' must be a list of strings")

    needs: list[str] = []
    seen: set[str] = set()
    for item in raw:
        cleaned = item.strip()
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            needs.append(cleaned)
    if not needs:
        raise ValueError(f"{path}: no needs defined")
    return needs


def build_search_terms(need: str, templates: list[str]) -> list[str]:
    """Substitute ``need`` into every template, yielding one query string each."""
    need = need.strip()
    return [t.replace("{need}", need) for t in templates]


def recency_code(since: str) -> str | None:
    """Map a ``--since`` window (e.g. ``"7d"``, ``"30d"``, ``"1y"``) to a DDG ``df`` code.

    Returns ``d`` / ``w`` / ``m`` / ``y`` (past day/week/month/year), or ``None`` if
    the window is unrecognized (no recency filter applied).
    """
    match = _SINCE_RE.match(since)
    if not match:
        return None
    amount, unit = int(match.group(1)), match.group(2).lower()
    days = {"d": amount, "w": amount * 7, "m": amount * 30, "y": amount * 365}[unit]
    if days <= 1:
        return "d"
    if days <= 7:
        return "w"
    if days <= 31:
        return "m"
    return "y"


def build_search_url(term: str, since: str) -> str:
    """Full DuckDuckGo HTML search URL for one query term, with recency filter."""
    params = {"q": term, "kl": "us-en"}
    code = recency_code(since)
    if code is not None:
        params["df"] = code
    return f"{DDG_HTML_ENDPOINT}?{urlencode(params)}"


def brave_freshness(since: str) -> str | None:
    """Map a ``--since`` window to the Brave API ``freshness`` value (``pd``/``pw``/``pm``/``py``).

    Returns ``None`` when the window is unrecognized (no freshness filter applied).
    """
    code = recency_code(since)
    return f"p{code}" if code is not None else None


def serper_tbs(since: str) -> str | None:
    """Map a ``--since`` window to Serper's Google ``tbs`` value (``qdr:d``/``w``/``m``/``y``).

    Returns ``None`` when the window is unrecognized (no recency filter applied).
    """
    code = recency_code(since)
    return f"qdr:{code}" if code is not None else None
