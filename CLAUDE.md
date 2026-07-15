# LeadForge — Code Map

## What this project does

LeadForge finds **sales leads for a digital-marketing agency** by mining public
LinkedIn posts where someone says they need help (e.g. "looking for a marketing
agency" or "need a video editor"). It searches the web for those posts, extracts
who wrote them and what they want, cleans the data, decides whether each post is
a *real customer looking to buy* (versus a job ad, a recruiter, or a competitor's
self-promotion), scores how promising and how fresh each lead is, stores them in
a local database, and exports a ranked outreach list to CSV or Excel. It runs
locally at zero cost — no paid data providers.

## How a lead flows through the system

```
  scrape → clean → classify + score → store → export
```

1. **Scrape.** You run `leadforge intent scrape --need "marketing"`. The service
   layer (`services/intent_scrape.py`) asks the registry for the LinkedIn scraper,
   which searches the web for matching posts (`scrapers/intent/queries.py` +
   `fetchers.py`), opens each post in a headless browser, and parses out the raw
   fields (`scrapers/intent/parsing.py`). Each post comes back as a `RawLead` — a
   dumb bag of source fields.
2. **Clean.** Each `RawLead` is mapped into a typed `IntentLead`
   (`scrapers/intent/mapping.py`), then run through the validation/cleaning
   boundary (`validation/intent.py`): names, text, emails, phones, and URLs are
   normalized, and a **data-quality score** is attached. Junk that can't be used
   is rejected and recorded.
3. **Store.** The cleaned lead is written to the SQLite database, de-duplicated by
   its post URL (`database/repositories.py`) — so the same post found twice is
   stored once.
4. **Classify + score.** You run `leadforge intent score`. This reads every stored
   lead and, for each one, decides its **category** (genuine client lead / job
   posting / recruiter / competitor / content-noise / unclear —
   `scoring/classify.py`), measures how **fresh** it is (`scoring/freshness.py`)
   and how well it **matches** what the agency sells (`scoring/need_match.py`),
   and blends those into a single `lead_score` from 0–100
   (`scoring/lead_score.py`). Only genuine client leads keep a real score;
   everything else is pushed near zero.
5. **Export.** `leadforge intent list` shows the ranked list in the terminal;
   `leadforge intent export` writes it to `exports/` as CSV or Excel
   (`exports/intent.py`). Both default to client leads only — the actual people
   worth contacting.

## Module map

Each real code file and its one-line job. (Package `__init__.py` files, database
migration scripts, and tests are omitted.)

| File | What it does |
| --- | --- |
| `cli/app.py` | The command-line tool. Thin wrappers that call the service layer — no business logic here. |
| `config/settings.py` | All settings, read from environment variables / `.env` (database path, search engine, rate limits, feature switches). |
| **Models — the shapes of the data** | |
| `models/orm.py` | The database tables: leads, intent leads, rejects, scrape runs, checkpoints. |
| `models/schemas.py` | The scraper's input/output shapes: `SearchQuery` (what to look for) and `RawLead` (one raw, un-validated post). |
| `models/enums.py` | Fixed value sets: lead status and post category. |
| `models/base.py` | Shared database plumbing (base class + common columns like timestamps). |
| **Database — talking to storage** | |
| `database/engine.py` | Opens the database connection and hands out sessions — the one place a connection is created. |
| `database/repositories.py` | Every SQL query lives here (add, look-up, upsert, ranked lists). Nothing else writes SQL. |
| `database/migrate.py` | Creates/updates the database schema by running Alembic migrations. |
| **Scrapers — getting posts off the web** | |
| `scrapers/registry.py` | Maps a source name (e.g. `linkedin_posts`) to the code that builds it, and enforces the on/off switch. |
| `scrapers/base.py` | The interface every scraper implements, plus the runner that wraps a scrape with retries, throttling, and checkpoints. |
| `scrapers/errors.py` | The named error types scrapers can raise. |
| `scrapers/intent/linkedin_posts.py` | The LinkedIn public-post miner — the core lead source. |
| `scrapers/intent/queries.py` | Builds the web-search queries; loads the needs list and query templates from YAML. |
| `scrapers/intent/fetchers.py` | The actual network calls: web-search engines (Serper/Brave/DuckDuckGo) and the headless browser that loads a post. |
| `scrapers/intent/parsing.py` | Pulls the useful fields out of a search result or a loaded post page. |
| `scrapers/intent/mapping.py` | Turns a raw scraped post (`RawLead`) into a typed `IntentLead`. |
| **Cleaning & validation — making the data trustworthy** | |
| `validation/intent.py` | The cleaning boundary: cleans a lead's fields and computes its data-quality score (accept / reject decision). |
| `validation/normalizers.py` | Standardizes single fields: email, phone number, URL. |
| `validation/quality.py` | Scores how complete/usable a lead's data is. |
| `cleaning/names.py` | Cleans up author names (strips titles, emojis, credentials). |
| `cleaning/text.py` | General text tidy-up (whitespace, fancy Unicode, boilerplate). |
| **Scoring — ranking the leads** | |
| `scoring/classify.py` | Decides what a post really is: a client lead, a job posting, a recruiter, a competitor, or noise. |
| `scoring/freshness.py` | Scores recency — intent goes stale fast, so newer posts score higher. |
| `scoring/need_match.py` | Scores how well a post matches what the agency actually sells. |
| `scoring/lead_score.py` | Blends the signals into one `lead_score` (0–100). |
| `scoring/config.py` | The tunable knobs (weights, thresholds) for all of the above. |
| **Services — the orchestration glue** | |
| `services/intent_scrape.py` | Runs the whole scrape→clean→store flow for one need. |
| `services/intent_score.py` | Runs the classify+score pass over every stored lead. |
| **Exports & utilities** | |
| `exports/intent.py` | Writes the ranked lead list to a CSV or Excel file. |
| `utils/logging.py` | Sets up structured logging. |
| `utils/retry.py` | Retries transient failures with exponential backoff. |
| `utils/throttle.py` | Rate-limiting so scraping stays polite and within limits. |
| `utils/snapshots.py` | Saves the page HTML when parsing fails — the main scraper debugging aid. |
| `utils/user_agents.py` | Supplies a realistic browser identity for logged-out browsing. |

## Key commands

Setup (once):

```bash
pip install -e ".[dev]"          # install the project + dev tools
playwright install chromium      # install the headless browser
cp .env.example .env             # create local config (optional; defaults work)
leadforge init                   # create the database + schema
leadforge doctor                 # check the environment is ready
```

Everyday use:

```bash
leadforge intent scrape --need "marketing" --since 7d   # mine posts for one need
leadforge intent scrape-all                             # mine every need in needs.yaml
leadforge intent score                                  # (re)classify + score all stored leads
leadforge intent list                                   # show the ranked client-lead list
leadforge intent export --format xlsx                   # write the list to exports/
```

Development checks (run before considering work done):

```bash
pytest        # tests
ruff check .  # lint
mypy src      # type check
```

## Configuration files

- `.env` — secrets and switches (database URL, which search engine, rate limits).
- `needs.yaml` — the list of services the agency sells (used by `scrape-all`).
- `intent_queries.yaml` — search-query templates per need.
- `scoring.yaml` — scoring weights and thresholds.
