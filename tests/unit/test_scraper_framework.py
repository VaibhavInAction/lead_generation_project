"""ScrapeRunner cross-cutting behavior with fakes (README §6, §8, §12, §22)."""

from __future__ import annotations

from collections.abc import Callable

from leadforge.config.settings import Settings
from leadforge.models.schemas import RawLead, SearchQuery
from leadforge.scrapers.base import RunSummary, ScrapeRunner
from leadforge.scrapers.errors import BlockedError, ParseError, TransientError
from leadforge.utils.throttle import DomainThrottle

from .conftest import FakeCheckpointStore, FakeRunRecorder, FakeScraper


def _noop(_seconds: float) -> None:
    return None


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "scrape_delay_min": 0.0,
        "scrape_delay_max": 0.0,
        "scrape_authwall_limit": 3,
        "scrape_checkpoint_every": 2,
        "scrape_daily_cap": 150,
        "scrape_max_retries": 3,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def _make_runner(
    scraper: FakeScraper,
    settings: Settings,
    *,
    checkpoints: FakeCheckpointStore | None = None,
    recorder: FakeRunRecorder | None = None,
) -> tuple[ScrapeRunner, FakeCheckpointStore, FakeRunRecorder]:
    checkpoints = checkpoints or FakeCheckpointStore()
    recorder = recorder or FakeRunRecorder()
    throttle = DomainThrottle(0, 0, sleep=_noop, rand=lambda _a, _b: 0.0)
    runner = ScrapeRunner(
        scraper,
        settings,
        checkpoint_store=checkpoints,
        run_recorder=recorder,
        throttle=throttle,
        now=lambda: 0.0,
        retry_sleep=_noop,
    )
    return runner, checkpoints, recorder


def _raw(url: str) -> RawLead:
    return RawLead(source="fake", source_url=url, data={"author_name": "A", "post_text": "hi"})


QUERY = SearchQuery(need="marketing", since="7d")
URLS = [f"https://a.test/posts/{i}" for i in range(1, 4)]


def _run(runner: ScrapeRunner, handler: Callable[[RawLead], None], **kw: object) -> RunSummary:
    return runner.run(QUERY, run_id="run1", handler=handler, **kw)


class TestHappyPath:
    def test_extracts_handles_and_checkpoints(self) -> None:
        scraper = FakeScraper(URLS, _raw)
        runner, checkpoints, recorder = _make_runner(scraper, _settings())
        collected: list[RawLead] = []

        summary = _run(runner, collected.append)

        assert len(collected) == 3
        assert summary.status == "completed"
        assert summary.leads_found == 3
        assert summary.pages_visited == 3
        assert checkpoints.saved[("fake", "marketing")]["seen_urls"] == sorted(URLS)
        assert len(recorder.started) == 1
        assert len(recorder.finished) == 1

    def test_respects_query_limit(self) -> None:
        scraper = FakeScraper(URLS, _raw)
        runner, _, _ = _make_runner(scraper, _settings())
        collected: list[RawLead] = []

        limited = SearchQuery(need="marketing", since="7d", limit=2)
        summary = runner.run(limited, run_id="run1", handler=collected.append)

        assert summary.leads_found == 2
        assert len(collected) == 2


class TestRetry:
    def test_retries_transient_then_succeeds(self) -> None:
        state = {"n": 0}

        def extractor(url: str) -> RawLead:
            state["n"] += 1
            if state["n"] < 3:
                raise TransientError("timeout")
            return _raw(url)

        scraper = FakeScraper(["https://a.test/posts/1"], extractor)
        runner, _, _ = _make_runner(scraper, _settings())
        summary = _run(runner, lambda _r: None)

        assert summary.leads_found == 1
        assert summary.errors == 0
        assert state["n"] == 3

    def test_counts_error_after_retries_exhausted(self) -> None:
        def extractor(_url: str) -> RawLead:
            raise TransientError("always")

        scraper = FakeScraper(["https://a.test/posts/1"], extractor)
        runner, _, _ = _make_runner(scraper, _settings(scrape_max_retries=2))
        summary = _run(runner, lambda _r: None)

        assert summary.leads_found == 0
        assert summary.errors == 1


class TestKillSwitch:
    def test_aborts_after_consecutive_blocks(self) -> None:
        def extractor(_url: str) -> RawLead:
            raise BlockedError("authwall")

        scraper = FakeScraper(URLS, extractor)
        runner, _, recorder = _make_runner(scraper, _settings(scrape_authwall_limit=3))
        summary = _run(runner, lambda _r: None)

        assert summary.status == "aborted"
        assert summary.leads_found == 0
        assert summary.pages_visited == 3
        assert "consecutive" in (summary.message or "")
        assert recorder.finished[0].status == "aborted"

    def test_block_counter_resets_on_success(self) -> None:
        # block, ok, block, ok, block → never 3 consecutive, so no abort.
        outcomes = iter([True, False, True, False, True])

        def extractor(url: str) -> RawLead:
            if next(outcomes):
                raise BlockedError("authwall")
            return _raw(url)

        urls = [f"https://a.test/posts/{i}" for i in range(5)]
        scraper = FakeScraper(urls, extractor)
        runner, _, _ = _make_runner(scraper, _settings(scrape_authwall_limit=3))
        summary = _run(runner, lambda _r: None)

        assert summary.status == "completed"
        assert summary.leads_found == 2


class TestParseFailure:
    def test_snapshots_html_and_continues(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)

        def extractor(url: str) -> RawLead:
            raise ParseError("layout changed", url=url, html="<html>broken</html>")

        scraper = FakeScraper(["https://a.test/posts/1"], extractor)
        runner, _, _ = _make_runner(scraper, _settings())
        summary = _run(runner, lambda _r: None)

        assert summary.rejects == 1
        assert summary.leads_found == 0
        assert len(summary.snapshots) == 1
        snapshots = list((tmp_path / "logs" / "snapshots").glob("*.html"))
        assert len(snapshots) == 1


class TestDailyCap:
    def test_stops_when_cap_reached(self) -> None:
        scraper = FakeScraper(URLS, _raw)
        runner, _, _ = _make_runner(scraper, _settings(scrape_daily_cap=2))
        summary = _run(runner, lambda _r: None)

        assert summary.leads_found == 2
        assert summary.pages_visited == 2
        assert "daily request cap" in (summary.message or "")

    def test_prior_usage_counts_against_cap(self) -> None:
        scraper = FakeScraper(URLS, _raw)
        recorder = FakeRunRecorder(used_today=150)
        runner, _, _ = _make_runner(scraper, _settings(scrape_daily_cap=150), recorder=recorder)
        summary = _run(runner, lambda _r: None)

        assert summary.leads_found == 0
        assert summary.pages_visited == 0


class TestResume:
    def test_resume_skips_already_seen_urls(self) -> None:
        checkpoints = FakeCheckpointStore()
        first = FakeScraper(URLS[:2], _raw)
        runner1, _, _ = _make_runner(first, _settings(), checkpoints=checkpoints)
        _run(runner1, lambda _r: None)

        second = FakeScraper(URLS, _raw)  # same two + one new
        runner2, _, _ = _make_runner(second, _settings(), checkpoints=checkpoints)
        collected: list[RawLead] = []
        summary = runner2.run(QUERY, run_id="run2", handler=collected.append, resume=True)

        assert summary.leads_found == 1
        assert [r.source_url for r in collected] == [URLS[2]]


class TestHandlerIsolation:
    def test_handler_failure_does_not_kill_run(self) -> None:
        scraper = FakeScraper(URLS[:2], _raw)
        runner, _, _ = _make_runner(scraper, _settings())

        def bad_handler(_raw: RawLead) -> None:
            raise RuntimeError("store failed")

        summary = _run(runner, bad_handler)

        assert summary.status == "completed"
        assert summary.leads_found == 2
        assert summary.rejects == 2
