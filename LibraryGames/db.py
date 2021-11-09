import sqlite3

import click
from flask import current_app
from flask import g
from flask.cli import with_appcontext
import pickle
from datetime import date

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
    refresh_db()
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
    import requests
    from boardgamegeek import BGGClient
    from boardgamegeek.exceptions import BGGItemNotFoundError, BGGApiError
    import html
    import string
    bgg = BGGClient()
    page = requests.get("https://anok.ent.sirsi.net/client/rss/hitlist/default/lm=TABLEGAMES&isd=true")
    soup = BeautifulSoup(page.text, features="lxml")
    db = get_db()
    libraryids = [row['id'] for row in db.execute("SELECT id FROM library WHERE bgg_id IS NOT NULL")]
    found = [False]*len(libraryids)
    print(len(found))
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
                print(search_name)
                games = bgg.search(no_punctuation(search_name))
                games = sorted(games, key=lambda s: hamming(search_name, s.name))
                #if len(games) > 1:
                #    print("## looking at year", year, [g.year for g in games])
                #    year_games = [g for g in games if abs(g.year - year) < 2]
                #    if len(year_games) > 0:
                #        games = year_games
                if len(games) > 1:
                    matching_author = []
                    print("### looked at authors", author)
                    for g in games[:10]:
                        game = bgg.game(game_id = g.id)
                        print(game.name)
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
                bgg = BGGClient()
        if game_result:
            try:
                g = bgg.game(game_id = game_result.id)
            except BGGApiError as e:
                bgg = BGGClient()
                g = bgg.game(game_id = game_result.id)
            print("Found", search_name, g.name, g.id)
            db.execute(
                "REPLACE INTO bgg (id, gamep, updated) VALUES (?,?,?)",
                (g.id, pickle.dumps(g), str(date.today())),
            )
            db.execute(
                "UPDATE library set bgg_id = ? where id = ?",
                (g.id, libraryid),
            )
        else:
            print("#########")
            print(libraryname, "not found")
            print("#########")

        db.commit()
    for n,libraryid in enumerate(libraryids):
        if not found[n]:
            row = db.execute(
                "select * FROM library where id = ?",
                (libraryid,),
                ).fetchone()
            print(row["name"], row["bgg_id"])
            delete = input("Delete [Y/n]?")
            if delete.lower() != "n":
                db.execute(
                        "DELETE FROM library where id = ?",
                        (libraryid,),
                        )
                db.commit()



def refresh_bgg():
    from boardgamegeek import BGGClient
    from boardgamegeek.exceptions import BGGItemNotFoundError, BGGApiError
    bgg = BGGClient()

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
