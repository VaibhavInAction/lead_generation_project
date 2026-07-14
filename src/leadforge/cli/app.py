"""LeadForge CLI (Typer). Thin wrappers over the service layer — no business logic here."""

from __future__ import annotations

import importlib
import os
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from leadforge import __version__
from leadforge.config.settings import Settings, get_settings
from leadforge.utils.logging import configure_logging

if TYPE_CHECKING:
    from leadforge.scrapers.base import RunSummary

app = typer.Typer(
    name="leadforge",
    help="LeadForge — intent-first, zero-cost lead generation. See README.md for the spec.",
    no_args_is_help=True,
)

intent_app = typer.Typer(
    help="Intent-signal mining — the v0.1 core (README §14).", no_args_is_help=True
)
app.add_typer(intent_app, name="intent")

CheckResult = tuple[str, str, str]  # (status: ok|warn|fail, name, detail)

CORE_PACKAGES = ("pydantic", "sqlalchemy", "httpx", "structlog", "bs4", "playwright", "typer")

RUNTIME_DIRS = ("data", "logs")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"leadforge {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Show version."
    ),
) -> None:
    import logging

    configure_logging(get_settings())
    # Alembic emits plugin-registration chatter at INFO the moment it's imported
    # (any DB-touching command pulls it in). Commands narrate their own progress,
    # so keep Alembic to warnings and above.
    logging.getLogger("alembic").setLevel(logging.WARNING)


def _check_python() -> CheckResult:
    found = ".".join(str(v) for v in sys.version_info[:3])
    if sys.version_info >= (3, 11):  # noqa: UP036 — doctor verifies the *runtime*, not metadata
        return ("ok", "python", found)
    return ("fail", "python", f"{found} — 3.11+ required")


def _check_packages() -> list[CheckResult]:
    results: list[CheckResult] = []
    for pkg in CORE_PACKAGES:
        try:
            importlib.import_module(pkg)
            results.append(("ok", f"package: {pkg}", "importable"))
        except ImportError:
            results.append(("fail", f"package: {pkg}", 'missing — run: pip install -e ".[dev]"'))
    return results


def _check_playwright_browser() -> CheckResult:
    candidates = []
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        candidates.append(Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"]))
    if os.environ.get("LOCALAPPDATA"):  # Windows default
        candidates.append(Path(os.environ["LOCALAPPDATA"]) / "ms-playwright")
    candidates.append(Path.home() / ".cache" / "ms-playwright")  # Linux default
    candidates.append(Path.home() / "Library" / "Caches" / "ms-playwright")  # macOS default

    for root in candidates:
        if root.is_dir() and any(p.name.startswith("chromium") for p in root.iterdir()):
            return ("ok", "playwright chromium", str(root))
    return ("warn", "playwright chromium", "not installed — run: playwright install chromium")


def _check_env_file() -> CheckResult:
    if Path(".env").is_file():
        return ("ok", ".env", "present")
    return ("warn", ".env", "missing — copy .env.example to .env (defaults are used meanwhile)")


def _check_runtime_dirs(settings: Settings) -> list[CheckResult]:
    results: list[CheckResult] = []
    for name in (*RUNTIME_DIRS, settings.export_dir):
        try:
            Path(name).mkdir(parents=True, exist_ok=True)
            results.append(("ok", f"dir: {name}/", "writable"))
        except OSError as exc:
            results.append(("fail", f"dir: {name}/", f"cannot create — {exc}"))
    return results


def _check_database(settings: Settings) -> CheckResult:
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(settings.database_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return ("ok", "database", settings.database_url)
    except Exception as exc:  # noqa: BLE001 — doctor reports, never crashes
        return ("fail", "database", f"{settings.database_url} — {exc}")


def _check_ollama(settings: Settings) -> CheckResult:
    if not settings.ai_enabled:
        return ("ok", "ollama", "skipped (AI_ENABLED=false — heuristics tier only)")
    try:
        import httpx

        resp = httpx.get(f"{settings.ollama_host}/api/tags", timeout=3.0)
        resp.raise_for_status()
        models = [m.get("name", "?") for m in resp.json().get("models", [])]
        if settings.ollama_model in models:
            return ("ok", "ollama", f"reachable, model {settings.ollama_model} available")
        return ("warn", "ollama", f"reachable, but run: ollama pull {settings.ollama_model}")
    except Exception as exc:  # noqa: BLE001
        return ("warn", "ollama", f"unreachable at {settings.ollama_host} — {exc}")


@app.command()
def init() -> None:
    """Create the database and bring it up to the latest schema (README §19).

    Idempotent: safe to re-run — Alembic only applies migrations not yet present.
    """
    from sqlalchemy import inspect

    from leadforge.database import create_db_engine, run_migrations

    settings = get_settings()
    typer.echo(f"Initializing database at {settings.database_url}")
    try:
        run_migrations(settings)
    except Exception as exc:  # noqa: BLE001 — surface a clean message, not a traceback
        typer.secho(f"init: migration failed — {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    engine = create_db_engine(settings)
    tables = sorted(inspect(engine).get_table_names())
    engine.dispose()

    typer.secho(f"init: database ready - {len(tables)} tables.", fg=typer.colors.GREEN)
    for name in tables:
        typer.echo(f"  - {name}")


@app.command()
def doctor() -> None:
    """Verify the local environment is ready for LeadForge."""
    settings = get_settings()
    results: list[CheckResult] = [
        _check_python(),
        *_check_packages(),
        _check_playwright_browser(),
        _check_env_file(),
        *_check_runtime_dirs(settings),
        _check_database(settings),
        _check_ollama(settings),
    ]

    styles = {
        "ok": ("OK", typer.colors.GREEN),
        "warn": ("WARN", typer.colors.YELLOW),
        "fail": ("FAIL", typer.colors.RED),
    }
    for status, name, detail in results:
        label, color = styles[status]
        typer.secho(f"[{label:>4}] {name:<24} {detail}", fg=color)

    fails = sum(1 for s, _, _ in results if s == "fail")
    warns = sum(1 for s, _, _ in results if s == "warn")
    typer.echo()
    if fails:
        summary = f"doctor: {fails} failure(s), {warns} warning(s) — fix failures first."
        typer.secho(summary, fg=typer.colors.RED)
        raise typer.Exit(code=1)
    if warns:
        summary = f"doctor: ready with {warns} warning(s) — warnings limit some features."
        typer.secho(summary, fg=typer.colors.YELLOW)
    else:
        typer.secho("doctor: all checks passed. Ready to build.", fg=typer.colors.GREEN)


def _print_run_summary(summary: object) -> None:
    """Render a scrape run's counts (README §21: found / stored / rejected …)."""
    # Local import keeps the type out of the module's import graph until needed.
    from leadforge.scrapers.base import RunSummary

    assert isinstance(summary, RunSummary)  # noqa: S101 — internal invariant
    rows = [
        ("pages visited", summary.pages_visited),
        ("extracted", summary.leads_found),
        ("stored (new)", summary.stored_new),
        ("stored (updated)", summary.stored_updated),
        ("rejected", summary.rejects),
        ("errors", summary.errors),
    ]
    typer.echo(f"run {summary.run_id} [{summary.status}]")
    for label, value in rows:
        typer.echo(f"  {label:<18} {value}")
    if summary.snapshots:
        typer.echo(f"  {'snapshots':<18} {len(summary.snapshots)} (logs/snapshots/)")


@intent_app.command("scrape")
def intent_scrape(
    need: str = typer.Option(
        ..., "--need", help='What you sell, e.g. "marketing" or "video editor".'
    ),
    source: str = typer.Option(
        "linkedin_posts", "--source", help="Intent source (must be in SOURCES_ENABLED)."
    ),
    since: str = typer.Option("7d", "--since", help="Recency window: 7d, 30d, 1y, …"),
    limit: int | None = typer.Option(None, "--limit", help="Max posts to store this run."),
    resume: bool = typer.Option(
        False, "--resume", help="Resume from the last checkpoint for this source/need."
    ),
) -> None:
    """Mine public LinkedIn posts stating a need and store them as intent leads (README §13.1)."""
    from leadforge.scrapers.registry import is_enabled
    from leadforge.services.intent_scrape import build_intent_scrape_service

    settings = get_settings()
    if not is_enabled(source, settings):
        typer.secho(
            f"intent scrape: source {source!r} is not enabled "
            f"(SOURCES_ENABLED={settings.sources_enabled!r}).",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    try:
        service = build_intent_scrape_service(source, settings)
    except (KeyError, PermissionError, FileNotFoundError, ValueError) as exc:
        typer.secho(f"intent scrape: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    typer.echo(f"[{source}] mining '{need}' (since {since})…")
    summary = service.run(need=need, since=since, limit=limit, resume=resume)
    _print_run_summary(summary)

    if summary.status == "aborted":
        typer.secho(summary.message or "run aborted (compliance stop).", fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)


def _summary_line(summary: RunSummary) -> str:
    """One-line run counts for the batch view."""
    return (
        f"extracted={summary.leads_found:>3}  new={summary.stored_new:>3}  "
        f"updated={summary.stored_updated:>3}  rejects={summary.rejects:>3}  "
        f"errors={summary.errors:>3}  [{summary.status}]"
    )


def _print_batch_totals(summaries: list[tuple[str, RunSummary]]) -> None:
    """Recap each need's counts and the grand total across the batch."""
    typer.echo("\n" + "=" * 72)
    typer.echo(f"Batch summary — {len(summaries)} service(s):")
    for need, summary in summaries:
        typer.echo(f"  {need:<30} {_summary_line(summary)}")

    total_extracted = sum(s.leads_found for _, s in summaries)
    total_new = sum(s.stored_new for _, s in summaries)
    total_updated = sum(s.stored_updated for _, s in summaries)
    total_rejects = sum(s.rejects for _, s in summaries)
    total_errors = sum(s.errors for _, s in summaries)

    typer.echo("-" * 72)
    typer.secho(
        f"TOTAL  extracted={total_extracted}  new={total_new}  updated={total_updated}  "
        f"rejects={total_rejects}  errors={total_errors}",
        fg=typer.colors.GREEN,
    )
    # Cross-need duplicates upsert by post_url, so a post seen under a second
    # service counts as "updated" there, never a second "new" — total_new is the
    # count of distinct new leads stored across the whole batch (README §17).
    typer.echo(f"{total_new} distinct new lead(s) stored, deduped by post_url across all services.")


@intent_app.command("scrape-all")
def intent_scrape_all(
    source: str = typer.Option(
        "linkedin_posts", "--source", help="Intent source (must be in SOURCES_ENABLED)."
    ),
    since: str = typer.Option("7d", "--since", help="Recency window: 7d, 30d, 1y, …"),
    limit_per_need: int | None = typer.Option(
        None, "--limit-per-need", help="Max posts to store per service."
    ),
    resume: bool = typer.Option(
        False, "--resume", help="Resume each service from its last checkpoint."
    ),
    needs_file: str | None = typer.Option(
        None, "--needs-file", help="Path to needs.yaml (default: NEEDS_PATH)."
    ),
) -> None:
    """Mine every service in needs.yaml, storing leads for all of them (README §14).

    Reuses the per-need throttle/retry/checkpoint logic; posts are de-duplicated
    by post_url across the whole batch (DB upsert), so a post found under two
    services is stored once.
    """
    from leadforge.scrapers.intent.queries import load_needs
    from leadforge.scrapers.registry import is_enabled
    from leadforge.services.intent_scrape import build_intent_scrape_service

    settings = get_settings()
    if not is_enabled(source, settings):
        typer.secho(
            f"intent scrape-all: source {source!r} is not enabled "
            f"(SOURCES_ENABLED={settings.sources_enabled!r}).",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    path = needs_file or settings.needs_path
    try:
        needs = load_needs(path)
    except (FileNotFoundError, ValueError) as exc:
        typer.secho(f"intent scrape-all: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    try:
        service = build_intent_scrape_service(source, settings)
    except (KeyError, PermissionError, FileNotFoundError, ValueError) as exc:
        typer.secho(f"intent scrape-all: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Scraping {len(needs)} service(s) from {path} (since {since})…")
    summaries: list[tuple[str, RunSummary]] = []
    aborted = False
    for need in needs:
        typer.echo(f"\n[{source}] '{need}'")
        summary = service.run(need=need, since=since, limit=limit_per_need, resume=resume)
        typer.echo("  " + _summary_line(summary))
        summaries.append((need, summary))
        if summary.status == "aborted":
            aborted = True
            typer.secho(
                "  " + (summary.message or "run aborted (compliance stop)."),
                fg=typer.colors.YELLOW,
            )
            break

    _print_batch_totals(summaries)
    if aborted:
        typer.secho(
            "Batch stopped early on a compliance block; remaining services not run.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(code=1)


# (header, dict-key, column width) for the fixed-width part of the `intent list`
# table. post_url is handled separately as the final, un-truncated column so the
# URL stays complete and clickable.
_INTENT_COLUMNS = (
    ("author", "author_name", 20),
    ("company", "company", 14),
    ("need_text", "need_text", 40),
    ("posted_at", "posted_at", 16),
    ("qual", "data_quality_score", 4),
)
_URL_HEADER = "post_url"


def _console_safe(text: str) -> str:
    """Render text safely on any console.

    Normalizes fancy Unicode (e.g. 𝐛𝐨𝐥𝐝 math letters → ASCII) and replaces any
    character the active stdout encoding can't represent — so an emoji in a lead
    never crashes the table on a legacy console (e.g. Windows cp1252).
    """
    text = unicodedata.normalize("NFKC", text)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, "replace").decode(encoding)


def _cell(value: object, width: int) -> str:
    """Format one value into a fixed-width, single-line, console-safe cell."""
    if value is None:
        text = "-"
    elif isinstance(value, datetime):
        text = value.strftime("%Y-%m-%d %H:%M")
    else:
        text = " ".join(str(value).split())  # collapse newlines/runs of whitespace
    text = _console_safe(text)
    if len(text) > width:
        text = text[: width - 3] + "..."
    return text.ljust(width)


def _print_intent_table(rows: list[dict[str, object]]) -> None:
    """Print intent-lead rows as an aligned table; post_url is shown in full, last."""
    num_w = 3
    fixed = "  ".join(h.ljust(w) for h, _, w in _INTENT_COLUMNS)
    header = "#".ljust(num_w) + "  " + fixed + "  " + _URL_HEADER
    typer.echo(header)
    typer.echo("-" * len(header))
    for i, row in enumerate(rows, 1):
        cells = "  ".join(_cell(row[key], w) for _, key, w in _INTENT_COLUMNS)
        # Full, un-truncated URL as the final column so it stays clickable.
        url = _console_safe(str(row["post_url"])) if row["post_url"] is not None else "-"
        typer.echo(str(i).ljust(num_w) + "  " + cells + "  " + url)


@intent_app.command("list")
def intent_list(
    limit: int = typer.Option(20, "--limit", help="Max leads to show (most recent first)."),
) -> None:
    """List stored intent leads as a table, most recently captured first (README §14)."""
    from leadforge.database import create_db_engine, create_session_factory, session_scope
    from leadforge.database.repositories import IntentLeadRepository

    settings = get_settings()
    engine = create_db_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        with session_scope(session_factory) as session:
            repo = IntentLeadRepository(session)
            total = repo.count()
            # Materialize the rows inside the session so rendering needs no ORM access.
            keys = [key for _, key, _ in _INTENT_COLUMNS] + ["post_url"]
            rows = [
                {key: getattr(lead, key) for key in keys} for lead in repo.list_recent(limit=limit)
            ]
    finally:
        engine.dispose()

    if not rows:
        typer.echo("No intent leads stored yet. Run: leadforge intent scrape --need <thing>")
        return

    _print_intent_table(rows)
    typer.echo(f"\nShowing {len(rows)} of {total} intent lead(s), most recent first.")


@intent_app.command("export")
def intent_export(
    fmt: str = typer.Option("csv", "--format", help="Output format: csv | xlsx."),
    output: str | None = typer.Option(
        None, "--output", help="Output path (default: <EXPORT_DIR>/intent_leads_<timestamp>.<ext>)."
    ),
) -> None:
    """Export all stored intent leads to a file in exports/ (README §18)."""
    from leadforge.database import create_db_engine, create_session_factory, session_scope
    from leadforge.database.repositories import IntentLeadRepository
    from leadforge.exports.intent import INTENT_COLUMNS, write_intent_leads

    fmt_norm = fmt.strip().lower()
    if fmt_norm not in ("csv", "xlsx"):
        typer.secho(
            f"intent export: unsupported --format {fmt!r} (use csv or xlsx).",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    settings = get_settings()
    engine = create_db_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        with session_scope(session_factory) as session:
            repo = IntentLeadRepository(session)
            # All leads, most recent first; materialized so writing needs no ORM access.
            rows = [
                {column: getattr(lead, column) for column in INTENT_COLUMNS}
                for lead in repo.list_recent()
            ]
    finally:
        engine.dispose()

    if not rows:
        typer.echo("No intent leads to export. Run: leadforge intent scrape --need <thing>")
        return

    if output is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = Path(settings.export_dir) / f"intent_leads_{timestamp}.{fmt_norm}"
    else:
        out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    write_intent_leads(rows, out_path, fmt_norm)
    typer.secho(f"Exported {len(rows)} intent lead(s) to {out_path}", fg=typer.colors.GREEN)
