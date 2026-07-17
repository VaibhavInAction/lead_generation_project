"""Cross-cutting scraper primitives: throttle, retry, snapshots, queries (README §6, §12)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from leadforge.scrapers.intent.queries import (
    brave_freshness,
    build_search_terms,
    build_search_url,
    load_needs,
    recency_code,
    serper_tbs,
)
from leadforge.utils.retry import retry_call
from leadforge.utils.snapshots import save_html_snapshot
from leadforge.utils.throttle import DailyRequestCap, DomainThrottle


class TestDomainThrottle:
    def test_first_hit_does_not_wait(self) -> None:
        slept: list[float] = []
        throttle = DomainThrottle(8, 15, sleep=slept.append, rand=lambda _a, _b: 10.0)
        assert throttle.wait("example.com") == 0.0
        assert slept == []

    def test_rejects_inverted_bounds(self) -> None:
        with pytest.raises(ValueError, match="min_seconds"):
            DomainThrottle(15, 8)


class TestDailyRequestCap:
    def test_allows_up_to_limit(self) -> None:
        cap = DailyRequestCap(3)
        assert [cap.allow() for _ in range(4)] == [True, True, True, False]
        assert cap.remaining == 0

    def test_seeded_with_prior_usage(self) -> None:
        cap = DailyRequestCap(5, already_used=5)
        assert cap.remaining == 0
        assert cap.allow() is False


class TestRetryCall:
    def test_succeeds_after_transient_failures(self) -> None:
        attempts = {"n": 0}

        def flaky() -> str:
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise ValueError("boom")
            return "ok"

        result = retry_call(flaky, retries=3, exceptions=(ValueError,), sleep=lambda _s: None)
        assert result == "ok"
        assert attempts["n"] == 3

    def test_reraises_after_exhausting_retries(self) -> None:
        def always_fail() -> str:
            raise ValueError("nope")

        with pytest.raises(ValueError, match="nope"):
            retry_call(always_fail, retries=2, exceptions=(ValueError,), sleep=lambda _s: None)

    def test_does_not_retry_unlisted_exceptions(self) -> None:
        calls = {"n": 0}

        def fail() -> str:
            calls["n"] += 1
            raise KeyError("different")

        with pytest.raises(KeyError):
            retry_call(fail, retries=3, exceptions=(ValueError,), sleep=lambda _s: None)
        assert calls["n"] == 1


class TestSnapshots:
    def test_writes_html_to_snapshot_dir(self, tmp_path) -> None:
        root = tmp_path / "snaps"
        when = datetime(2026, 7, 14, 12, 0, 0, tzinfo=UTC)
        path = save_html_snapshot("<html>x</html>", "https://x.test/post/1", root=root, now=when)
        assert path.exists()
        assert path.read_text(encoding="utf-8") == "<html>x</html>"
        assert path.parent == root


class TestQueries:
    def test_build_search_terms_substitutes_need(self) -> None:
        terms = build_search_terms("video editor", ['site:x "need a {need}"', "{need} help"])
        assert terms == ['site:x "need a video editor"', "video editor help"]

    @pytest.mark.parametrize(
        ("since", "code"),
        [("1d", "d"), ("7d", "w"), ("30d", "m"), ("90d", "y"), ("1y", "y"), ("weird", None)],
    )
    def test_recency_code(self, since: str, code: str | None) -> None:
        assert recency_code(since) == code

    def test_build_search_url_includes_recency_and_query(self) -> None:
        url = build_search_url('site:linkedin.com/posts "need a marketing agency"', "7d")
        assert url.startswith("https://html.duckduckgo.com/html/?")
        assert "df=w" in url
        assert "marketing+agency" in url

    @pytest.mark.parametrize(
        ("since", "freshness"),
        [("1d", "pd"), ("7d", "pw"), ("30d", "pm"), ("1y", "py"), ("weird", None)],
    )
    def test_brave_freshness(self, since: str, freshness: str | None) -> None:
        assert brave_freshness(since) == freshness

    @pytest.mark.parametrize(
        ("since", "tbs"),
        [("1d", "qdr:d"), ("7d", "qdr:w"), ("30d", "qdr:m"), ("1y", "qdr:y"), ("weird", None)],
    )
    def test_serper_tbs(self, since: str, tbs: str | None) -> None:
        assert serper_tbs(since) == tbs


class TestLoadNeeds:
    def test_loads_cleans_and_dedupes(self, tmp_path) -> None:
        path = tmp_path / "needs.yaml"
        path.write_text(
            "needs:\n"
            "  - marketing agency\n"
            "  - '  SEO agency  '\n"  # surrounding whitespace stripped
            "  - Marketing Agency\n"  # case-insensitive duplicate dropped
            "  - ''\n",  # empty entry dropped
            encoding="utf-8",
        )
        assert load_needs(path) == ["marketing agency", "SEO agency"]

    def test_missing_file_raises(self, tmp_path) -> None:
        with pytest.raises(FileNotFoundError):
            load_needs(tmp_path / "nope.yaml")

    def test_empty_needs_raises(self, tmp_path) -> None:
        path = tmp_path / "needs.yaml"
        path.write_text("needs: []\n", encoding="utf-8")
        with pytest.raises(ValueError, match="no needs defined"):
            load_needs(path)

    def test_wrong_type_raises(self, tmp_path) -> None:
        path = tmp_path / "needs.yaml"
        path.write_text("needs: not-a-list\n", encoding="utf-8")
        with pytest.raises(ValueError, match="must be a list of strings"):
            load_needs(path)

    def test_seed_file_is_valid(self) -> None:
        # The shipped needs.yaml is user-editable config: assert it loads and is
        # well-formed, not its exact contents (those change per agency).
        needs = load_needs("needs.yaml")
        assert len(needs) >= 1
        assert all(isinstance(n, str) and n.strip() for n in needs)
