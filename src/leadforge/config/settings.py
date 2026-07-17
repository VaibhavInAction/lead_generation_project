"""Application settings, loaded from environment variables / .env.

Single source of configuration truth (README §20). All modules receive
settings via `get_settings()` or dependency injection — never read
`os.environ` directly elsewhere.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "sqlite:///data/leadforge.db"

    # Sources (comma-separated kill switch, README §6)
    sources_enabled: str = "linkedin_posts"

    # Scraping conduct — compliance controls, not tuning knobs (README §6)
    scrape_delay_min: float = 8.0
    scrape_delay_max: float = 15.0
    scrape_daily_cap: int = 150
    scrape_headless: bool = True
    # Consecutive authwalls/CAPTCHAs that cleanly abort a run (kill switch, README §13)
    scrape_authwall_limit: int = 5
    # Persist checkpoint progress after every N extracted leads (README §8)
    scrape_checkpoint_every: int = 5
    # Max transient-failure retries per request (README §12)
    scrape_max_retries: int = 3
    # Phrase templates for intent mining live in config, not code (README §13.1)
    intent_queries_path: str = "intent_queries.yaml"
    # The agency's target services, mined together by `intent scrape-all` (README §14)
    needs_path: str = "needs.yaml"
    # Tunable scoring weights/thresholds; missing file → built-in defaults (README §16)
    scoring_path: str = "scoring.yaml"

    # Search discovery (README §13.1). Serper.dev (Google results as JSON, free,
    # no card) is the default; Brave needs a card; DDG-HTML soft-blocks (HTTP 202)
    # and is kept only as a keyless fallback.
    search_engine: str = "serper"  # serper | brave | ddg
    search_country: str = "us"  # Google gl code weighting results: "in" = India, "us" = USA
    serper_api_key: str = ""  # required when SEARCH_ENGINE=serper; never hardcode
    brave_api_key: str = ""  # required when SEARCH_ENGINE=brave; never hardcode

    # Local AI (optional tier — platform must work with this off, README §15)
    ai_enabled: bool = False
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"

    # Logging
    log_level: str = "INFO"
    log_format: str = "console"  # console | json

    # Output
    export_dir: str = "exports"

    @property
    def sources(self) -> list[str]:
        """SOURCES_ENABLED parsed into a clean list."""
        return [s.strip() for s in self.sources_enabled.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
