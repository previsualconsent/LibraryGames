import asyncio
import html
import logging
import pickle
import re
import sqlite3
import string
import time
import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from typing import Callable
from typing import TypeVar

import aiohttp
import click
import requests
from bgg_pi import BggClient as AsyncBggClient
from bgg_pi.const import BASE_URL
from bs4 import BeautifulSoup
from bs4 import Tag
from bs4 import XMLParsedAsHTMLWarning
from flask import current_app
from flask import g
from flask.cli import with_appcontext


LOGGER = logging.getLogger(__name__)
_T = TypeVar("_T")


@dataclass
class BggSearchResult:
    id: int
    name: str
    year: int | None = None


@dataclass
class BggHotItem:
    id: int
    rank: int


@dataclass
class BggRank:
    id: int
    friendlyname: str
    value: str | None


@dataclass
class BggGame:
    id: int
    name: str
    year: int | None
    ranks: list[BggRank]
    designers: list[str]


def _normalize_bgg_title(value: str) -> str:
    text = value.lower().strip()
    text = re.sub(r"^[^a-z0-9]+", "", text)
    text = text.replace("=", ":")
    text = re.sub(r"[^a-z0-9: ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


MANUAL_BGG_GAMES = {}


MANUAL_BGG_SEARCH = {}


class BggClientAdapter:
    def __init__(self, username: str = "librarygames"):
        self.username = username

    def hot_items(self, item_type: str):
        return asyncio.run(self._hot_items(item_type))

    async def _hot_items(self, item_type: str):
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{BASE_URL}/hot?type={item_type}", timeout=30
            ) as response:
                if response.status != 200:
                    return []
                text = await response.text()

        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return []

        items = []
        for item in root.findall("item"):
            item_id = item.get("id")
            rank = item.get("rank")
            if item_id and rank:
                items.append(BggHotItem(id=int(item_id), rank=int(rank)))
        return items

    def search(self, query: str):
        return asyncio.run(self._search(query))

    async def _search(self, query: str):
        normalized_query = _normalize_bgg_title(query)
        params = {"query": query, "type": "boardgame"}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{BASE_URL}/search", params=params, timeout=30
            ) as response:
                if response.status != 200:
                    return self._manual_search_results(normalized_query)
                text = await response.text()

        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return self._manual_search_results(normalized_query)

        results = []
        for item in root.findall("item"):
            item_id = item.get("id")
            if not item_id:
                continue

            name = None
            for candidate in item.findall("name"):
                if candidate.get("type") == "primary":
                    name = candidate.get("value")
                    break
            if not name:
                continue

            year_value = None
            year_node = item.find("yearpublished")
            year_text = year_node.get("value") if year_node is not None else None
            if year_text:
                try:
                    year_value = int(year_text)
                except ValueError:
                    year_value = None

            results.append(BggSearchResult(id=int(item_id), name=name, year=year_value))
        if results:
            return results
        return self._manual_search_results(normalized_query)

    def _manual_search_results(self, normalized_query: str):
        for key, result in MANUAL_BGG_SEARCH.items():
            if key in normalized_query or normalized_query in key:
                return [result]
        return []

    def game(self, game_id: int):
        return asyncio.run(self._game(int(game_id)))

    async def _game(self, game_id: int):
        async with aiohttp.ClientSession() as session:
            client = AsyncBggClient(session=session, username=self.username)
            try:
                details = await client.fetch_thing_details([game_id])
            except Exception:
                return MANUAL_BGG_GAMES.get(game_id)
            async with session.get(
                f"{BASE_URL}/thing",
                params={"id": game_id, "stats": 1},
                timeout=30,
            ) as response:
                if response.status != 200:
                    return MANUAL_BGG_GAMES.get(game_id)
                xml_text = await response.text()

        if not details:
            return MANUAL_BGG_GAMES.get(game_id)

        detail = details[0]
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return MANUAL_BGG_GAMES.get(game_id)

        item = root.find("item")
        if item is None:
            return None

        designers = [
            value
            for link in item.findall("link")
            if link.get("type") == "boardgamedesigner"
            for value in [link.get("value")]
            if value is not None
        ]

        ranks = []
        ranks_node = item.find("statistics/ratings/ranks")
        if ranks_node is not None:
            for index, rank in enumerate(ranks_node.findall("rank"), start=1):
                ranks.append(
                    BggRank(
                        id=index,
                        friendlyname=rank.get("friendlyname") or rank.get("name") or "Rank",
                        value=rank.get("value"),
                    )
                )

        if not ranks:
            ranks.append(BggRank(id=1, friendlyname="Board Game Rank", value=detail.get("rank")))

        year = detail.get("yearpublished")
        try:
            year = int(year) if year is not None else None
        except (TypeError, ValueError):
            year = None

        return BggGame(
            id=int(detail["id"]),
            name=detail.get("name") or f"Game {game_id}",
            year=year,
            ranks=ranks,
            designers=designers,
        )


def _entry_text(entry: Tag, name: str) -> str | None:
    node = entry.find(name)
    if node is None:
        return None
    text = node.get_text(strip=True)
    return text or None


def _entry_href(entry: Tag) -> str | None:
    link = entry.find("link")
    if link is None:
        return None
    href = link.get("href")
    return href if isinstance(href, str) and href else None


def _parse_entry_content(content_text: str) -> dict[str, str]:
    content: dict[str, str] = {}
    for line in content_text.replace("<br/>", "\n").split("\n"):
        if not line:
            continue
        parts = line.split(":", 1)
        if len(parts) != 2:
            continue
        key, value = parts
        content[key.strip()] = value.strip()
    return content

def get_db():
    """Connect to the application's configured database. The connection
    is unique for each request and will be reused if this is called
    again.
    """
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config["DATABASE"],
            detect_types=sqlite3.PARSE_DECLTYPES,
            timeout=30,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA journal_mode = WAL")
        g.db.execute("PRAGMA busy_timeout = 30000")

    return g.db


def run_with_db_retry(
    operation: Callable[[], _T], retries: int = 20, delay: float = 0.25
) -> _T:
    last_error = None
    for _ in range(retries):
        try:
            return operation()
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower():
                raise
            last_error = exc
            time.sleep(delay)

    if last_error is not None:
        raise last_error

    raise RuntimeError("Database retry loop exited unexpectedly")


def close_db(e=None):
    """If this request connected to the database, close the
    connection.
    """
    db = g.pop("db", None)

    if db is not None:
        db.close()


def init_db():
    """Clear existing data and create new tables."""
    db = get_db()

    with current_app.open_resource("schema.sql") as f:
        db.executescript(f.read().decode("utf8"))


@click.command("init-db")
@with_appcontext
def init_db_command():
    """Clear existing data and create new tables."""
    init_db()
    click.echo("Initialized the database.")


@click.command("refresh-db")
@with_appcontext
def refresh_db_command():
    """Just add New library games to db"""
    refresh_db()
    click.echo("Refreshed the database.")


@click.command("refresh-bgg")
@with_appcontext
def refresh_bgg_command():
    """Just add New library games to db"""
    refresh_bgg()
    click.echo("Refreshed the database.")


@click.command("migrate-db")
@with_appcontext
def migrate_db_command():
    """Apply non-destructive schema migrations to existing databases."""
    migrate_db()
    click.echo("Database migrations completed.")


def init_app(app):
    """Register database functions with the Flask app. This is called by
    the application factory.
    """
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(refresh_db_command)
    app.cli.add_command(refresh_bgg_command)
    app.cli.add_command(migrate_db_command)


def _table_columns(db: sqlite3.Connection, table_name: str) -> set[str]:
    rows = db.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row[1] for row in rows}


def migrate_db() -> None:
    db = get_db()

    list_columns = _table_columns(db, "list") if _table_columns(db, "list") else set()
    if not list_columns:
        db.execute(
            "CREATE TABLE list ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " user_id INTEGER NOT NULL,"
            " name TEXT NOT NULL,"
            " created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            " UNIQUE (user_id, name),"
            " FOREIGN KEY (user_id) REFERENCES user (id)"
            ")"
        )

    list_game_columns = _table_columns(db, "list_game")
    if "list_name" in list_game_columns:
        users = db.execute("SELECT id FROM user ORDER BY id").fetchall()
        default_user = users[0]["id"] if users else None
        if default_user is None:
            raise RuntimeError("Cannot migrate list data without at least one user.")

        db.execute(
            "CREATE TABLE list_game_new ("
            " list_id INTEGER NOT NULL,"
            " game_id INTEGER NOT NULL,"
            " PRIMARY KEY (list_id, game_id),"
            " FOREIGN KEY (list_id) REFERENCES list (id),"
            " FOREIGN KEY (game_id) REFERENCES library (id)"
            ")"
        )

        old_rows = db.execute(
            "SELECT DISTINCT list_name FROM list_game WHERE list_name IS NOT NULL"
        ).fetchall()
        for row in old_rows:
            list_name = row["list_name"]
            db.execute(
                "INSERT OR IGNORE INTO list (user_id, name) VALUES (?, ?)",
                (default_user, list_name),
            )
            list_row = db.execute(
                "SELECT id FROM list WHERE user_id = ? AND name = ?",
                (default_user, list_name),
            ).fetchone()
            if list_row is None:
                continue

            memberships = db.execute(
                "SELECT game_id FROM list_game WHERE list_name = ?",
                (list_name,),
            ).fetchall()
            for membership in memberships:
                db.execute(
                    "INSERT OR IGNORE INTO list_game_new (list_id, game_id) VALUES (?, ?)",
                    (list_row["id"], membership["game_id"]),
                )

        db.execute("DROP TABLE list_game")
        db.execute("ALTER TABLE list_game_new RENAME TO list_game")

    refresh_columns = _table_columns(db, "refresh_job") if _table_columns(db, "refresh_job") else set()
    if not refresh_columns:
        db.execute(
            "CREATE TABLE refresh_job ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " created_by INTEGER NOT NULL,"
            " status TEXT NOT NULL,"
            " message TEXT,"
            " error TEXT,"
            " created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            " started_at TIMESTAMP,"
            " finished_at TIMESTAMP,"
            " FOREIGN KEY (created_by) REFERENCES user (id)"
            ")"
        )

    db.execute("CREATE INDEX IF NOT EXISTS idx_list_user_id ON list (user_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_list_game_list_id ON list_game (list_id)")
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_refresh_job_user_created "
        "ON refresh_job (created_by, created_at DESC)"
    )
    db.commit()


def _get_bgg_client():
    return BggClientAdapter()


def no_punctuation(value: str) -> str:
    return value.translate(str.maketrans("", "", string.punctuation))


def hamming(left: str, right: str) -> tuple[int, int]:
    left_words = no_punctuation(left).lower().split()
    right_words = no_punctuation(right).lower().split()
    return (
        sum(word not in right_words for word in left_words),
        sum(word not in left_words for word in right_words),
    )


def refresh_db():
    bgg = _get_bgg_client()

    page = None
    last_error = None
    for attempt in range(1, 4):
        try:
            page = requests.get(
                "https://anok.ent.sirsi.net/client/rss/hitlist/default/lm=TABLEGAMES&isd=true",
                timeout=30,
            )
            page.raise_for_status()
            break
        except Exception as exc:
            last_error = exc
            LOGGER.warning("refresh_db feed attempt %s failed: %s", attempt, exc)
            time.sleep(1)

    if page is None:
        raise RuntimeError(f"Could not fetch library feed: {last_error}")

    LOGGER.info("refresh_db started")
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
    soup = BeautifulSoup(page.text, features="html.parser")
    db = get_db()
    libraryids = [
        row["id"]
        for row in db.execute("SELECT id FROM library WHERE bgg_id IS NOT NULL")
    ]
    found = [False] * len(libraryids)
    for game in soup.find_all("entry"):
        if not isinstance(game, Tag):
            continue

        entry_id = _entry_text(game, "id")
        libraryname = _entry_text(game, "title")
        content_text = _entry_text(game, "content")
        libraryurl = _entry_href(game)
        if not entry_id or not libraryname or not content_text or not libraryurl:
            continue

        libraryid = entry_id.split(":")[-1]
        if int(libraryid) in libraryids:
            found[libraryids.index(int(libraryid))] = True
            continue

        libraryname = html.unescape(libraryname).replace("escape adventures.", "")
        librarycontent = html.unescape(content_text)
        content = _parse_entry_content(librarycontent)
        author = content.get("Author", "").translate(
            str.maketrans("", "", string.punctuation)
        ).split()
        try:
            db.execute(
                "INSERT INTO library (id, name, url) VALUES (?, ?, ?)",
                (libraryid, libraryname, libraryurl),
            )
            db.commit()
        except sqlite3.IntegrityError:
            pass

        search_name = libraryname.replace(".", ":")
        if search_name.endswith("."):
            search_name = search_name[:-1]
        search_name = search_name.replace(" :", ":")
        game_result = None
        while search_name:
            try:
                games = bgg.search(no_punctuation(search_name))
                games = sorted(games, key=lambda s: hamming(search_name, s.name))
                if len(games) > 1:
                    for candidate in games[:10]:
                        candidate_game = bgg.game(game_id=candidate.id)
                        if candidate_game is None:
                            continue
                        hits = sum(
                            author_name in " ".join(candidate_game.designers)
                            for author_name in author
                        )
                        if hits > 0:
                            game_result = candidate
                            break
                    if game_result:
                        break
                if games:
                    game_result = games[0]
                    break
                search_name = ":".join(search_name.split(":")[:-1]).strip()
            except Exception as exc:
                LOGGER.warning("BGG search failed for '%s': %s", search_name, exc)
                bgg = _get_bgg_client()
        if game_result:
            try:
                bgg_game = bgg.game(game_id=game_result.id)
            except Exception:
                bgg = _get_bgg_client()
                bgg_game = bgg.game(game_id=game_result.id)
            if bgg_game is not None:
                db.execute(
                    "REPLACE INTO bgg (id, gamep, updated) VALUES (?, ?, ?)",
                    (bgg_game.id, pickle.dumps(bgg_game), str(date.today())),
                )
                db.execute(
                    "UPDATE library set bgg_id = ? where id = ?",
                    (bgg_game.id, libraryid),
                )

        db.commit()
    LOGGER.info("refresh_db completed")
def refresh_bgg():
    bgg = _get_bgg_client()

    db = get_db()
    bgg_ids = [
        row["id"] for row in db.execute("SELECT id FROM bgg ORDER BY updated DESC")
    ]

    i = 0
    for bggid in bgg_ids:
        i += 1
        print(f"{i} / {len(bgg_ids)}", end="\r", flush=True)

        retry = 5
        while retry > 0:
            try:
                bgg_game = bgg.game(game_id=bggid)
                if bgg_game is None:
                    break

                db.execute(
                    "REPLACE INTO bgg (id, gamep, updated) VALUES (?, ?, ?)",
                    (bgg_game.id, pickle.dumps(bgg_game), str(date.today())),
                )
                db.commit()
                retry = 0
            except Exception as exc:
                retry -= 1
                print(exc, f"for game {bggid}")
    print()
