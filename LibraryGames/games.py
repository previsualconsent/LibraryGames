from flask import Blueprint
from flask import flash
from flask import g
from flask import redirect
from flask import render_template
from flask import request
from flask import session
from flask import url_for
import pickle
from werkzeug.exceptions import abort
import datetime

from LibraryGames.db import get_db, refresh_db
from boardgamegeek import BGGClient
from boardgamegeek.exceptions import *

bp = Blueprint("games", __name__)


def render(edit=False, listname=None, editlist=False, invert=False):
    sortby = request.args.get("sort","rank")
    bgg = BGGClient()
    hot = bgg.hot_items("boardgame")
    hot_ranks = {}
    for h in hot:
        hot_ranks[h.id] = h.rank

    db = get_db()

    joins = ""
    wheres = ""
    games_in_list = []
    if listname is not None:
        for row in db.execute(f"SELECT game_id from list_game where list_name LIKE '{listname}'").fetchall():
            games_in_list.append(row['game_id'])

    sql = (
        "SELECT l.id as id, l.name as lname, l.added, l.url, g.id as bggid, g.gamep"
        " FROM library as l INNER JOIN bgg as g ON l.bgg_id = g.id"
        + joins + ((" WHERE " + wheres) if wheres else "") +
        " ORDER BY added DESC"
        )
    games_with_bgg = db.execute(sql).fetchall()

    sql = (
        "SELECT l.id as id, l.name as lname, l.added, l.url, l.bgg_id"
        " FROM library as l"
        + joins + 
        " WHERE bgg_id is NULL"
        + ((" AND " + wheres) if wheres else "") +
        " ORDER BY added DESC"
        )

    games_without_bgg = db.execute(sql).fetchall()

    games = []
    bgg_games = [pickle.loads(game['gamep']) for game in games_with_bgg]

    games_iter = zip(games_with_bgg, bgg_games)
    for game, bgg_game in games_iter:
        game = dict(game)
        bggid = game['bggid']

        game["name"] = bgg_game.name
        game["bggurl"] = f"https://boardgamegeek.com/boardgame/{game['bggid']}/"
        rank = [r.value for r in bgg_game.ranks if r.id == 1][0]
        if rank:
            game["bggrank"] = rank

        game["ranks"] = [dict(friendlyname=r.friendlyname.split()[0], value=r.value) for r in bgg_game.ranks if r.id != 1]
        game["year"] = bgg_game.year
        game["hot"] = hot_ranks.get(bggid, "")

        if sortby == "hot":
            game["sortby"] = game["hot"]  if game["hot"] else rank + 99999 if rank else 999999 
        elif sortby == "date":
            game["sortby"] = datetime.date.today() - game['added']
        else: #rank
            game["sortby"] = int(rank) if rank else float('inf')

        games.append(game)
    games = sorted(games, key=lambda g: g["sortby"])
    if editlist:
        games = [g for g in games if g['id'] in games_in_list] + [g for g in games if g['id'] not in games_in_list]
    elif listname is not None:
        if invert:
            games = [g for g in games if not g['id'] in games_in_list]
        else:
            games = [g for g in games if g['id'] in games_in_list]
    return render_template("games/index.html", bgggames=games, othergames=games_without_bgg, edit=edit, editlist=editlist, listname=listname, checks =games_in_list, inverted=invert)

@bp.route("/")
def index():
    """Show all the games, most recent first."""
    return render()

@bp.route("/refresh", methods=("GET", "POST"))
def refresh():
    """Refresh db"""
    refresh_db()
    return redirect(url_for("games.index"))

@bp.route("/edit")
def set_edit():
    """edit db"""
    return render(edit=True)

@bp.route("/edit/<gameid>", methods=("GET", "POST"))
def set_edit_gameid(gameid):
    """edit db"""
    db = get_db()
    if request.method == "POST":
        bggid = request.form['bggid']
        bgg = BGGClient()
        bgg_game = bgg.game(game_id=bggid)
        if bgg_game:
            db.execute(
                "REPLACE INTO bgg (id, gamep) VALUES (?,?)",
                (bgg_game.id, pickle.dumps(bgg_game)),
            )
            db.execute(
                "UPDATE library set bgg_id = ? where id = ?",
                (bgg_game.id, gameid),
            )
            db.commit()

    game = db.execute(
        "SELECT *"
        " FROM library as l LEFT OUTER JOIN bgg as g"
        " ON l.bgg_id = g.id"
        " WHERE l.id = ?",
        (gameid,)
    ).fetchone()
    game = dict(game)
    if(game['gamep']):
        gamep = pickle.loads(game['gamep'])
        game['bggname'] = gamep.name
        game["bggurl"] = f"https://boardgamegeek.com/boardgame/{gamep.id}/"
    else:
        game['bggname'] = None

    return render_template("games/update.html", game=game)

@bp.route("/null/<gameid>")
def set_null_gameid(gameid):
    """null gameid in db"""
    db = get_db()
    bgg = BGGClient()
    db.execute(
        "UPDATE library set bgg_id = ? where id = ?",
        (None, gameid),
    )
    db.commit()

    return render(edit=True)

@bp.route("/lists")
def show_lists():
    """show lists"""
    db = get_db()
    list_names = [r['list_name'] for r in  set(db.execute("SELECT list_name from list_game").fetchall())]
    return render_template("games/lists.html", names=sorted(list_names))

@bp.route("/list/<listname>")
def set_list(listname):
    """show list"""
    return render(listname=listname, editlist=False)

@bp.route("/list/<listname>/not")
def set_list_invert(listname):
    """show inverse of list"""
    return render(listname=listname, editlist=False, invert=True)

@bp.route("/list/<listname>/edit", methods=("GET", "POST"))
def set_editlist(listname):
    """edit list"""
    if request.method == "POST":
        db = get_db()
        db.execute("DELETE FROM list_game where list_name LIKE ?", (listname,))
        for key in request.form:
            print(key, request.form[key])
            db.execute(
                "INSERT INTO list_game (game_id, list_name) VALUES (?,?)",
                (key, listname),
                )
        db.commit()
            #db.execute(
            #    "UPDATE library set bgg_id = ? where id = ?",
            #    (bgg_game.id, gameid),
            #)
        for row in db.execute("SELECT * from list_game").fetchall():
            print(dict(row))
    return render(listname=listname, editlist=True)
