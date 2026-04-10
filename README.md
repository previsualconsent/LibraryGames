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
- Avoid reintroducing legacy Flask tutorial/blog artifacts
- Prefer extending `tests/test_games.py` and `tests/test_db.py` for new behavior