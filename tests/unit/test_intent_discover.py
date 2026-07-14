"""Search-phase throttling in discover() and the search fetchers, all offline (README §6, §23).

The search phase must be throttled like extraction — the earlier bug fired one
request per phrase template with no delay. The Serper/Brave fetchers are exercised
with a monkeypatched ``httpx`` so no network is touched.
"""

from __future__ import annotations

import json

import httpx
import pytest
from structlog.testing import capture_logs

from leadforge.config.settings import Settings
from leadforge.models.schemas import SearchQuery
from leadforge.scrapers.errors import BlockedError, TransientError
from leadforge.scrapers.intent.fetchers import BraveSearchFetcher, SerperSearchFetcher
from leadforge.scrapers.intent.linkedin_posts import LinkedInPostsScraper

TEMPLATES = ["looking for a {need}", "need a {need}", "hire a {need}"]


class RecordingThrottle:
    """A Throttle spy that logs each wait into a shared event list."""

    def __init__(self, events: list[tuple[str, str]]) -> None:
        self._events = events

    def wait(self, domain: str) -> float:
        self._events.append(("wait", domain))
        return 0.0


class RecordingSearchFetcher:
    """A SearchFetcher that logs each search and returns canned post URLs."""

    domain = "search.test"

    def __init__(self, events: list[tuple[str, str]]) -> None:
        self._events = events
        self.calls: list[tuple[str, str]] = []

    def search(self, term: str, since: str) -> list[str]:
        self._events.append(("search", term))
        self.calls.append((term, since))
        idx = len(self.calls)
        return [f"https://www.linkedin.com/posts/p{idx}"]


class DummyPageFetcher:
    """Unused by discover(); present only to satisfy the constructor."""

    def fetch(self, url: str) -> str:  # pragma: no cover - never called here
        return "<html></html>"


def _scraper(throttle: RecordingThrottle, fetcher: RecordingSearchFetcher) -> LinkedInPostsScraper:
    return LinkedInPostsScraper(
        Settings(_env_file=None),
        search_fetcher=fetcher,
        page_fetcher=DummyPageFetcher(),
        templates=TEMPLATES,
        throttle=throttle,
    )


class TestSearchPhaseThrottling:
    def test_throttles_once_per_search_before_each_request(self) -> None:
        events: list[tuple[str, str]] = []
        fetcher = RecordingSearchFetcher(events)
        scraper = _scraper(RecordingThrottle(events), fetcher)

        urls = list(scraper.discover(SearchQuery(need="marketing", since="7d")))

        # One throttle wait per phrase template, and each wait precedes its search.
        assert events == [
            ("wait", "search.test"),
            ("search", "looking for a marketing"),
            ("wait", "search.test"),
            ("search", "need a marketing"),
            ("wait", "search.test"),
            ("search", "hire a marketing"),
        ]
        assert fetcher.calls == [
            ("looking for a marketing", "7d"),
            ("need a marketing", "7d"),
            ("hire a marketing", "7d"),
        ]
        assert urls == [
            "https://www.linkedin.com/posts/p1",
            "https://www.linkedin.com/posts/p2",
            "https://www.linkedin.com/posts/p3",
        ]

    def test_still_throttles_when_a_search_fails(self) -> None:
        events: list[tuple[str, str]] = []

        class Flaky(RecordingSearchFetcher):
            def search(self, term: str, since: str) -> list[str]:
                self._events.append(("search", term))
                raise BlockedError("429")

        scraper = _scraper(RecordingThrottle(events), Flaky(events))
        urls = list(scraper.discover(SearchQuery(need="marketing", since="7d")))

        assert urls == []  # every search blocked, but the run survived
        assert [e[0] for e in events] == ["wait", "search", "wait", "search", "wait", "search"]


class TestBraveSearchFetcher:
    def _patch_httpx(self, monkeypatch, response) -> dict[str, object]:
        captured: dict[str, object] = {}

        def fake_get(url, *, params=None, headers=None, timeout=None):
            captured["url"] = url
            captured["params"] = params
            captured["headers"] = headers
            return response

        monkeypatch.setattr(httpx, "get", fake_get)
        return captured

    def test_parses_results_and_sends_auth_and_freshness(self, monkeypatch, brave_json) -> None:
        class Resp:
            status_code = 200

            def json(self) -> dict:
                return json.loads(brave_json)

        captured = self._patch_httpx(monkeypatch, Resp())
        urls = BraveSearchFetcher("secret-key").search("looking for a marketing agency", "7d")

        assert urls == [
            "https://www.linkedin.com/posts/jane-doe_marketing-activity-111",
            "https://www.linkedin.com/posts/ravi-kumar_need-marketing-activity-222",
        ]
        assert captured["headers"]["X-Subscription-Token"] == "secret-key"  # type: ignore[index]
        assert captured["params"]["q"] == "looking for a marketing agency"  # type: ignore[index]
        assert captured["params"]["freshness"] == "pw"  # type: ignore[index]  # 7d -> past week

    def test_bad_key_maps_to_blocked_error(self, monkeypatch) -> None:
        class Resp:
            status_code = 401

            def json(self) -> dict:  # pragma: no cover - not reached on 401
                return {}

        self._patch_httpx(monkeypatch, Resp())
        with pytest.raises(BlockedError, match="BRAVE_API_KEY"):
            BraveSearchFetcher("bad-key").search("marketing", "7d")


class TestSerperSearchFetcher:
    def _patch_httpx(self, monkeypatch, response) -> dict[str, object]:
        captured: dict[str, object] = {}

        def fake_post(url, *, json=None, headers=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return response

        monkeypatch.setattr(httpx, "post", fake_post)
        return captured

    def test_parses_results_and_sends_exact_body(self, monkeypatch, serper_json) -> None:
        class Resp:
            status_code = 200

            def json(self) -> dict:
                return json.loads(serper_json)

        captured = self._patch_httpx(monkeypatch, Resp())
        urls = SerperSearchFetcher("secret-key").search("looking for a marketing agency", "7d")

        assert urls == [
            "https://www.linkedin.com/posts/jane-doe_marketing-activity-111",
            "https://www.linkedin.com/posts/ravi-kumar_need-marketing-activity-222",
        ]
        assert captured["url"] == "https://google.serper.dev/search"
        assert captured["headers"]["X-API-KEY"] == "secret-key"  # type: ignore[index]
        assert captured["headers"]["Content-Type"] == "application/json"  # type: ignore[index]
        # Exact body per Serper's spec: q + gl + num + tbs (7d -> qdr:w).
        assert captured["json"] == {
            "q": "looking for a marketing agency",
            "gl": "us",
            "num": 10,
            "tbs": "qdr:w",
        }

    @pytest.mark.parametrize(("since", "tbs"), [("1d", "qdr:d"), ("30d", "qdr:m"), ("1y", "qdr:y")])
    def test_tbs_maps_each_since_window(self, monkeypatch, serper_json, since, tbs) -> None:
        class Resp:
            status_code = 200

            def json(self) -> dict:
                return json.loads(serper_json)

        captured = self._patch_httpx(monkeypatch, Resp())
        SerperSearchFetcher("k").search("marketing", since)
        assert captured["json"]["tbs"] == tbs  # type: ignore[index]

    def test_omits_tbs_when_since_unrecognized(self, monkeypatch, serper_json) -> None:
        class Resp:
            status_code = 200

            def json(self) -> dict:
                return json.loads(serper_json)

        captured = self._patch_httpx(monkeypatch, Resp())
        SerperSearchFetcher("k").search("marketing", "whenever")
        # No recency window -> no tbs key at all (an empty/invalid tbs triggers HTTP 400).
        assert captured["json"] == {"q": "marketing", "gl": "us", "num": 10}

    def test_bad_key_maps_to_blocked_error(self, monkeypatch) -> None:
        class Resp:
            status_code = 401
            text = '{"message":"Unauthorized"}'

            def json(self) -> dict:  # pragma: no cover - not reached on 401
                return {}

        self._patch_httpx(monkeypatch, Resp())
        with pytest.raises(BlockedError, match="SERPER_API_KEY"):
            SerperSearchFetcher("bad-key").search("marketing", "7d")

    def test_rate_limit_maps_to_blocked_error(self, monkeypatch) -> None:
        class Resp:
            status_code = 429
            text = '{"message":"Too Many Requests"}'

            def json(self) -> dict:  # pragma: no cover - not reached on 429
                return {}

        self._patch_httpx(monkeypatch, Resp())
        with pytest.raises(BlockedError, match="rate limited"):
            SerperSearchFetcher("k").search("marketing", "7d")

    def test_400_logs_response_body_then_raises(self, monkeypatch) -> None:
        class Resp:
            status_code = 400
            text = '{"message":"Not enough credits"}'

            def json(self) -> dict:  # pragma: no cover - not reached on 400
                return {}

        self._patch_httpx(monkeypatch, Resp())
        with capture_logs() as logs, pytest.raises(TransientError, match="400"):
            SerperSearchFetcher("k").search("marketing", "7d")
        # The Serper error body is logged so a live 400 is diagnosable.
        assert any(entry.get("body") == '{"message":"Not enough credits"}' for entry in logs)
