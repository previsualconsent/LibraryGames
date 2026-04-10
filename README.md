# LibraryGames

LibraryGames is a Flask app for tracking tabletop games available through the Anoka County Library system and enriching them with BoardGameGeek metadata when that data is available.

## Current Scope

- Games-first application surface at `/`
- User registration and login under `/auth/*`
- Library list browsing and list editing
- Optional BoardGameGeek enrichment during refresh and manual BGG ID assignment
- Test suite with built-in coverage reporting

## Requirements

- Python 3.13+
- `uv` for environment and package management

## Quick Start

```bash
uv sync
uv run flask --app main:app init-db
uv run flask --app main:app run --host 127.0.0.1 --port 5055
```

Then open `http://127.0.0.1:5055`.

## Common Commands

Initialize the database:

```bash
uv run flask --app main:app init-db
```

Refresh the library feed:

```bash
uv run flask --app main:app refresh-db
```

Refresh stored BGG records:

```bash
uv run flask --app main:app refresh-bgg
```

Run the development server:

```bash
uv run flask --app main:app run --host 127.0.0.1 --port 5055
```

Run tests:

```bash
uv run pytest
```

Run lint and type checks:

```bash
uv run ruff check .
uv run ty check
```

Set up pre-commit hooks:

```bash
uv sync
uv run pre-commit install
```

Run the configured hooks manually:

```bash
uv run pre-commit run --all-files
```

Generate an HTML coverage report:

```bash
uv run coverage html
```

## Project Layout

```text
LibraryGames/
  __init__.py      App factory
  auth.py          Registration and login
  db.py            SQLite access, RSS refresh, BGG integration
  games.py         Games routes and list editing
  schema.sql       Database schema
  static/          CSS assets
  templates/       Jinja templates
tests/
  conftest.py      Shared fixtures
  test_auth.py     Auth coverage
  test_db.py       DB and BGG adapter coverage
  test_factory.py  App factory smoke tests
  test_games.py    Games route coverage
```

## BoardGameGeek Integration Notes

The app uses `bgg-pi` plus a local adapter in `LibraryGames/db.py`.

Important: live BGG lookups may be blocked by upstream BoardGameGeek access controls from some environments. The application is designed to degrade gracefully when that happens.

Known fallback behavior:

- refresh still imports library feed data even if BGG enrichment is unavailable
- manual BGG edit pages keep the submitted ID and show a clear error on failed lookup
- canonical fallback mapping is included for known titles such as Ticket to Ride (`BGG ID 9209`)

## Notes for Contributors

- Packaging is managed with `uv` and `pyproject.toml`
- `uv sync` installs the default test and dev tool groups
- Pre-commit hooks run `ruff` and `pytest` through `uv run`
- Avoid reintroducing legacy Flask tutorial/blog artifacts
- Prefer extending `tests/test_games.py` and `tests/test_db.py` for new behavior

## Product Roadmap

This roadmap captures the next major application improvements and the
required verification bar for each phase.

### Phase 1: Per-User Lists and Access Control

- Introduce user-owned lists in the data model.
- Restrict list routes to authenticated users.
- Scope list reads and writes to the current user.
- Hide list pages and list actions for anonymous users.

Browser integration verification:

- Anonymous users are redirected to login for `/lists` and `/list/*` routes.
- User A cannot view or mutate User B list content.
- Logged-in users can create, edit, and view only their own lists.

### Phase 2: Non-Blocking Refresh and Status Tracking

- Move refresh execution to a background job.
- Add refresh status endpoints and persisted status records.
- Display live refresh status in the UI while browsing games.

Browser integration verification:

- Triggering refresh returns immediately and does not block navigation.
- Refresh status transitions are visible in the UI (`queued` -> `running` -> terminal state).
- The games page remains interactive while refresh is in progress.

### Phase 3: Edit Experience Overhaul and Delete Support

- Replace the current edit flow with inline or reduced-click editing.
- Improve BGG lookup ergonomics (search, select, confirm).
- Add delete capabilities for list membership and safe game cleanup flows.

Browser integration verification:

- Users can update BGG linkage with fewer page transitions.
- Users can remove games from their lists from the list view.
- Delete actions require confirmation and update the UI without stale state.

### Phase 4: Hardening, Observability, and Migration Tooling

- Add structured logging around refresh and BGG operations.
- Improve retries and resilience for external BGG/network failures.
- Introduce formal DB migrations for schema evolution.

Browser integration verification:

- UI shows meaningful error and recovery states on refresh/BGG failures.
- Existing user data remains intact after migration upgrades.
- Critical paths (login, list access, refresh, edit) remain green after deployment migration.

### Phase Exit Rule

No phase is considered complete until:

- unit tests pass,
- lint and type checks pass, and
- phase-specific browser integration tests pass in CI.