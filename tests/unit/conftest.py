"""Shared unit-test helpers: offline HTML fixtures and fake collaborators.

Tests never touch the network or a browser (README §23) — scrapers are driven by
saved fixtures and injected fakes.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from leadforge.models.schemas import RawLead, SearchQuery
from leadforge.scrapers.base import BaseScraper, RunSummary

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def load_fixture(name: str) -> str:
    """Read a saved HTML fixture by filename."""
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def ddg_html() -> str:
    return load_fixture("ddg_results.html")


@pytest.fixture
def post_html() -> str:
    return load_fixture("linkedin_post.html")


@pytest.fixture
def broken_post_html() -> str:
    return load_fixture("linkedin_post_broken.html")


@pytest.fixture
def hiring_post_html() -> str:
    return load_fixture("linkedin_post_hiring.html")


@pytest.fixture
def slug_post_html() -> str:
    return load_fixture("linkedin_post_slug.html")


@pytest.fixture
def authwall_html() -> str:
    return load_fixture("linkedin_authwall.html")


@pytest.fixture
def brave_json() -> str:
    return load_fixture("brave_results.json")


@pytest.fixture
def serper_json() -> str:
    return load_fixture("serper_results.json")


class FakeScraper(BaseScraper):
    """A scraper whose discover/extract are supplied inline for tests."""

    def __init__(self, urls, extractor, *, source_name: str = "fake") -> None:
        self.source_name = source_name
        self._urls = list(urls)
        self._extractor = extractor

    def discover(self, query: SearchQuery) -> Iterator[str]:
        yield from self._urls

    def extract(self, url: str) -> RawLead:
        return self._extractor(url)


class FakeCheckpointStore:
    """In-memory CheckpointStore implementation."""

    def __init__(self) -> None:
        self.saved: dict[tuple[str, str], dict[str, object]] = {}

    def load(self, source: str, query: str) -> dict[str, object] | None:
        return self.saved.get((source, query))

    def save(self, source: str, query: str, state: dict[str, object]) -> None:
        self.saved[(source, query)] = state


class FakeRunRecorder:
    """In-memory RunRecorder implementation with configurable prior usage."""

    def __init__(self, used_today: int = 0) -> None:
        self.started: list[tuple[str, str, str]] = []
        self.finished: list[RunSummary] = []
        self._used = used_today

    def start(self, run_id: str, source: str, query: str) -> None:
        self.started.append((run_id, source, query))

    def finish(self, summary: RunSummary) -> None:
        self.finished.append(summary)

    def requests_used_today(self, source: str) -> int:
        return self._used
