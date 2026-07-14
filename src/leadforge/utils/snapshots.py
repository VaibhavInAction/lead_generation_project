"""Snapshot-on-parse-failure — the single most valuable scraper debugging aid (README §22).

When a selector breaks (it will), the offending HTML is already on disk under
``logs/snapshots/`` before anyone notices, so the fix is a diff away.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path

from leadforge.models.base import utcnow

SNAPSHOT_DIR = Path("logs") / "snapshots"


def _slug(url: str) -> str:
    """A short, filesystem-safe tag derived from the URL (readable + unique-ish)."""
    tail = re.sub(r"[^a-zA-Z0-9]+", "-", url)[-48:].strip("-") or "page"
    # Not a security hash — just a short, stable tag to disambiguate filenames.
    digest = hashlib.sha1(url.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
    return f"{tail}-{digest}"


def save_html_snapshot(
    html: str,
    url: str,
    *,
    root: Path = SNAPSHOT_DIR,
    now: datetime | None = None,
) -> Path:
    """Write ``html`` to ``logs/snapshots/<timestamp>-<slug>.html`` and return the path."""
    root.mkdir(parents=True, exist_ok=True)
    stamp = (now or utcnow()).strftime("%Y%m%dT%H%M%S")
    path = root / f"{stamp}-{_slug(url)}.html"
    path.write_text(html, encoding="utf-8")
    return path
