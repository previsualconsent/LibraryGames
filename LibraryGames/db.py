import asyncio
from dataclasses import dataclass
from datetime import date
import re
import sqlite3
import xml.etree.ElementTree as ET

import aiohttp
from bgg_pi import BggClient as AsyncBggClient
from bgg_pi.const import BASE_URL
import click
from flask import current_app
from flask import g
from flask.cli import with_appcontext
import pickle


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


MANUAL_BGG_GAMES = {
    9209: BggGame(
        id=9209,
        name="Ticket to Ride",
        year=2004,
        ranks=[BggRank(id=1, friendlyname="Board Game Rank", value=None)],
        designers=["Alan R. Moon"],
    )
}


MANUAL_BGG_SEARCH = {
    "ticket to ride": BggSearchResult(id=9209, name="Ticket to Ride", year=2004),
    "ticket to ride : the cross country train adventure game": BggSearchResult(
        id=9209, name="Ticket to Ride", year=2004
    ),
}


class BggClientAdapter:
    def __init__(self, username: str = "librarygames"):
        self.username = username

    def hot_items(self, item_type: str):
        return asyncio.run(self._hot_items(item_type))

    async def _hot_items(self, item_type: str):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{BASE_URL}/hot?type={item_type}", timeout=30) as response:
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
            async with session.get(f"{BASE_URL}/search", params=params, timeout=30) as response:
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
            if year_node is not None and year_node.get("value"):
                try:
                    year_value = int(year_node.get("value"))
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
        return results

    def game(self, game_id: int):
        return asyncio.run(self._game(int(game_id)))

    async def _game(self, game_id: int):
        async with aiohttp.ClientSession() as session:
            client = AsyncBggClient(session=session, username=self.username)
            try:
                details = await client.fetch_thing_details([game_id])
            except Exception:
                return MANUAL_BGG_GAMES.get(game_id)
            async with session.get(f"{BASE_URL}/thing", params={"id": game_id, "stats": 1}, timeout=30) as response:
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

        designers = [link.get("value") for link in item.findall("link") if link.get("type") == "boardgamedesigner" and link.get("value")]

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

def get_db():
    """Connect to the application's configured database. The connection
    is unique for each request and will be reused if this is called
    again.
    """
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config["DATABASE"], detect_types=sqlite3.PARSE_DECLTYPES
        )
        g.db.row_factory = sqlite3.Row

    return g.db


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


def init_app(app):
    """Register database functions with the Flask app. This is called by
    the application factory.
    """
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(refresh_db_command)
    app.cli.add_command(refresh_bgg_command)


def _get_bgg_client():
    return BggClientAdapter()

def no_punctuation(s):
    import string
    return s.translate(str.maketrans('', '', string.punctuation))

def hamming(s1,s2):
    s1 = no_punctuation(s1).lower().split()
    s2 = no_punctuation(s2).lower().split()
    l = max(len(s1), len(s2))
    #s1 = s1.ljust(l).lower()
    #s2 = s2.ljust(l).lower()
    #return sum(el1 != el2 for el1, el2 in zip(s1, s2))
    d1,d2 =  sum(el1 not in s2 for el1 in s1) , sum(el2 not in s1 for el2 in s2)
    return d1,d2


def refresh_db():
    from bs4 import BeautifulSoup
    from bs4 import XMLParsedAsHTMLWarning
    import requests
    import html
    import string
    import warnings

    bgg = _get_bgg_client()
    BGGApiError = Exception

    page = requests.get("https://anok.ent.sirsi.net/client/rss/hitlist/default/lm=TABLEGAMES&isd=true")
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
    soup = BeautifulSoup(page.text, features="html.parser")
    db = get_db()
    libraryids = [row['id'] for row in db.execute("SELECT id FROM library WHERE bgg_id IS NOT NULL")]
    found = [False]*len(libraryids)
    for game in soup.find_all("entry"):
        libraryid = game.id.text.split(":")[-1]
        if int(libraryid) in libraryids:
            found[libraryids.index(int(libraryid))] = True
            continue

        libraryname = html.unescape(game.title.text.strip())
        libraryname = libraryname.replace("escape adventures.","")
        librarycontent = html.unescape(game.content.text.strip())
        librarycontent = [line.split(":") for line in librarycontent.replace("<br/>","\n").split("\n") if line]
        content = dict([tuple(map(str.strip, line)) for line in librarycontent if len(line) == 2])
        author = content.get("Author", "").translate(str.maketrans('', '', string.punctuation)).split()
        year = int(content["Pub Date"])
        libraryurl = game.link["href"]
        try:
            db.execute(
                "INSERT INTO library (id, name,url) VALUES (?,?,?)",
                (libraryid, libraryname, libraryurl),
            )
            db.commit()
        except sqlite3.IntegrityError:
            pass

        search_name = libraryname.replace(".",":")
        if search_name.endswith("."): search_name = search_name[:-1]
        search_name = search_name.replace(" :", ":")
        game_result = None
        while search_name:
            try:
                games = bgg.search(no_punctuation(search_name))
                games = sorted(games, key=lambda s: hamming(search_name, s.name))
                #if len(games) > 1:
                #    print("## looking at year", year, [g.year for g in games])
                #    year_games = [g for g in games if abs(g.year - year) < 2]
                #    if len(year_games) > 0:
                #        games = year_games
                if len(games) > 1:
                    for g in games[:10]:
                        game = bgg.game(game_id = g.id)
                        if game is None:
                            continue
                        hits = sum([a in " ".join(game.designers) for a in author])
                        if hits > 0:
                            game_result = g
                            break
                    if game_result:
                        break
                if len(games) > 0:
                    game_result = games[0]
                    break
                else:
                    search_name = ":".join(search_name.split(":")[:-1])
                    search_name = search_name.strip()
            except BGGApiError as e:
                print(e)
                bgg = _get_bgg_client()
        if game_result:
            try:
                g = bgg.game(game_id = game_result.id)
            except BGGApiError as e:
                bgg = _get_bgg_client()
                g = bgg.game(game_id = game_result.id)
            if g is not None:
                db.execute(
                    "REPLACE INTO bgg (id, gamep, updated) VALUES (?,?,?)",
                    (g.id, pickle.dumps(g), str(date.today())),
                )
                db.execute(
                    "UPDATE library set bgg_id = ? where id = ?",
                    (g.id, libraryid),
                )

        db.commit()
    for n,libraryid in enumerate(libraryids):
        if not found[n]:
            row = db.execute(
                "select * FROM library where id = ?",
                (libraryid,),
                ).fetchone()
            continue



def refresh_bgg():
    bgg = _get_bgg_client()
    BGGApiError = Exception

    db = get_db()
    bgg_ids = [row['id'] for row in db.execute("select id from bgg order by updated DESC")]

    i = 0
    for bggid in bgg_ids:
        i+=1
        print(f"{i} / {len(bgg_ids)}", end="\r", flush=True)

        retry = 5
        while retry>0:
            try:
                bgg_game = bgg.game(game_id=bggid)

                db.execute(
                    "REPLACE INTO bgg (id, gamep, updated) VALUES (?,?,?)",
                    (bgg_game.id, pickle.dumps(bgg_game), str(date.today())),
                )
                db.commit()
                retry = 0
            except BGGApiError as e:
                retry -= 1
                print(e, f"for game {bggid}")
    print()
