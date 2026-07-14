"""Settings behave per README §20: sane defaults, .env optional, sources parse cleanly."""

from leadforge.config.settings import Settings


def test_defaults_are_zero_cost_and_compliant() -> None:
    s = Settings(_env_file=None)
    assert s.database_url.startswith("sqlite:///")
    assert s.ai_enabled is False
    assert s.scrape_delay_min >= 1
    assert s.scrape_delay_min <= s.scrape_delay_max
    assert s.scrape_daily_cap > 0
    assert s.scrape_headless is True


def test_default_source_is_linkedin_posts() -> None:
    s = Settings(_env_file=None)
    assert s.sources == ["linkedin_posts"]


def test_sources_enabled_parses_messy_csv() -> None:
    s = Settings(_env_file=None, sources_enabled=" linkedin_posts, reddit ,,")
    assert s.sources == ["linkedin_posts", "reddit"]


def test_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("SCRAPE_DAILY_CAP", "42")
    monkeypatch.setenv("LOG_FORMAT", "json")
    s = Settings(_env_file=None)
    assert s.scrape_daily_cap == 42
    assert s.log_format == "json"
