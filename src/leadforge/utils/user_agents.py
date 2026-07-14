"""Realistic session identity for logged-out browsing (README §12).

A plausible, current desktop user agent, viewport, and locale — session hygiene,
not evasion. We never rotate to hide; a stable, honest identity is what a normal
browser presents. No proxies, no fingerprint spoofing.
"""

from __future__ import annotations

from dataclasses import dataclass

# A current, common desktop Chrome UA. Kept realistic and singular on purpose:
# the compliance stance (README §6) is human-speed browsing, not rotation.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class BrowserProfile:
    """The identity a scraper presents to a site."""

    user_agent: str = DEFAULT_USER_AGENT
    viewport_width: int = 1366
    viewport_height: int = 768
    locale: str = "en-US"

    @property
    def viewport(self) -> dict[str, int]:
        """Viewport dict in the shape Playwright expects."""
        return {"width": self.viewport_width, "height": self.viewport_height}


DEFAULT_PROFILE = BrowserProfile()
