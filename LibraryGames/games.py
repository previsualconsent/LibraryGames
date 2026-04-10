import datetime
import pickle
import threading

from flask import Blueprint
from flask import current_app
from flask import flash
from flask import g
from flask import jsonify
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for

from werkzeug.exceptions import abort

from LibraryGames.auth import login_required
from LibraryGames.db import _get_bgg_client, get_db, refresh_db

bp = Blueprint("games", __name__)

_REFRESH_LOCK = threading.Lock()


def _rank_sort_value(rank):
    if rank in (None, "", "Not Ranked"):
        return float("inf")
    try:
        return int(rank)
    except (TypeError, ValueError):
        return float("inf")


def _refresh_job_for_user(user_id: int):
    return get_db().execute(
        "SELECT * FROM refresh_job WHERE created_by = ? ORDER BY id DESC LIMIT 1",
        (user_id,),
    ).fetchone()


def _update_refresh_job(job_id: int, status: str, message: str | None = None, error: str | None = None):
    db = get_db()
    db.execute(
        "UPDATE refresh_job "
        "SET status = ?, message = COALESCE(?, message), error = COALESCE(?, error), "
        "started_at = CASE WHEN ? = 'running' THEN CURRENT_TIMESTAMP ELSE started_at END, "
        "finished_at = CASE WHEN ? IN ('success', 'failed') THEN CURRENT_TIMESTAMP ELSE finished_at END "
        "WHERE id = ?",
        (status, message, error, status, status, job_id),
    )
    db.commit()


def _run_refresh_job(app, job_id: int):
    with app.app_context():
        try:
            _update_refresh_job(job_id, "running", "Refresh in progress")
            refresh_db()
            _update_refresh_job(job_id, "success", "Refresh completed")
        except Exception as exc:
            _update_refresh_job(job_id, "failed", "Refresh failed", str(exc))


def _get_list_row(user_id: int, listname: str):
    return get_db().execute(
        "SELECT id, name FROM list WHERE user_id = ? AND name = ?",
        (user_id, listname),
    ).fetchone()


def _get_or_create_list_id(user_id: int, listname: str) -> int:
    db = get_db()
    db.execute(
        "INSERT OR IGNORE INTO list (user_id, name) VALUES (?, ?)",
        (user_id, listname),
    )
    db.commit()
    row = _get_list_row(user_id, listname)
    if row is None:
        raise RuntimeError("Could not create list")
    return row["id"]


def _update_game_bgg_mapping(gameid: int, bggid: str):
    db = get_db()
    bgg = _get_bgg_client()
    try:
        bgg_game = bgg.game(game_id=bggid)
    except Exception:
        bgg_game = None

    if not bgg_game:
        return False

    db.execute(
        "REPLACE INTO bgg (id, gamep, updated) VALUES (?, ?, CURRENT_DATE)",
        (bgg_game.id, pickle.dumps(bgg_game)),
    )
    updated = db.execute(
        "UPDATE library SET bgg_id = ? WHERE id = ?",
        (bgg_game.id, gameid),
    )
    db.commit()
    return updated.rowcount > 0


def render(edit=False, listname=None, editlist=False, invert=False):
    sortby = request.args.get("sort", "rank")
    bgg = _get_bgg_client()
    hot = bgg.hot_items("boardgame") if bgg else []
    hot_ranks = {}
    for h in hot:
        hot_ranks[h.id] = h.rank

    db = get_db()

    user_id = g.user["id"] if g.user else None
    list_id = None
    games_in_list = []
    if listname is not None:
        if user_id is None:
            abort(401)
        list_row = _get_list_row(user_id, listname)
        if list_row is None:
            abort(404)
        list_id = list_row["id"]
        for row in db.execute(
            "SELECT game_id FROM list_game WHERE list_id = ?",
            (list_id,),
        ).fetchall():
            games_in_list.append(row["game_id"])

    sql = (
        "SELECT l.id as id, l.name as lname, l.added, l.url, g.id as bggid, g.gamep"
        " FROM library as l INNER JOIN bgg as g ON l.bgg_id = g.id"
        " ORDER BY added DESC"
    )
    games_with_bgg = db.execute(sql).fetchall()

    sql = (
        "SELECT l.id as id, l.name as lname, l.added, l.url, l.bgg_id"
        " FROM library as l"
        " WHERE bgg_id is NULL"
        " ORDER BY added DESC"
    )

    games_without_bgg = db.execute(sql).fetchall()

    games = []
    bgg_games = [pickle.loads(game["gamep"]) for game in games_with_bgg]

    games_iter = zip(games_with_bgg, bgg_games)
    for game, bgg_game in games_iter:
        game = dict(game)
        bggid = game["bggid"]

        game["name"] = bgg_game.name
        game["bggurl"] = f"https://boardgamegeek.com/boardgame/{game['bggid']}/"
        rank = [r.value for r in bgg_game.ranks if r.id == 1][0]
        if rank:
            game["bggrank"] = rank

        game["ranks"] = [
            dict(friendlyname=r.friendlyname.split()[0], value=r.value)
            for r in bgg_game.ranks
            if r.id != 1
        ]
        game["year"] = bgg_game.year
        game["hot"] = hot_ranks.get(bggid, "")

        if sortby == "hot":
            rank_val = _rank_sort_value(rank)
            game["sortby"] = game["hot"] if game["hot"] else rank_val + 99999
        elif sortby == "date":
            game["sortby"] = datetime.date.today() - game["added"]
        else:  # rank
            game["sortby"] = _rank_sort_value(rank)

        games.append(game)
    games = sorted(games, key=lambda item: item["sortby"])
    if editlist:
        games = [g for g in games if g["id"] in games_in_list] + [
            g for g in games if g["id"] not in games_in_list
        ]
    elif listname is not None:
        if invert:
            games = [g for g in games if g["id"] not in games_in_list]
        else:
            games = [g for g in games if g["id"] in games_in_list]

    refresh_status = None
    if user_id is not None:
        refresh_status = _refresh_job_for_user(user_id)

    return render_template(
        "games/index.html",
        bgggames=games,
        othergames=games_without_bgg,
        edit=edit,
        editlist=editlist,
        listname=listname,
        checks=games_in_list,
        inverted=invert,
        refresh_status=refresh_status,
    )


@bp.route("/")
def index():
    """Show all the games, most recent first."""
    return render()


@bp.route("/refresh", methods=("GET", "POST"))
@login_required
def refresh():
    """Queue a background refresh job."""
    db = get_db()
    running = db.execute(
        "SELECT id FROM refresh_job WHERE status IN ('queued', 'running') ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if running:
        flash("A refresh job is already running.")
        return redirect(url_for("games.index"))

    with _REFRESH_LOCK:
        db.execute(
            "INSERT INTO refresh_job (created_by, status, message) VALUES (?, ?, ?)",
            (g.user["id"], "queued", "Refresh queued"),
        )
        job_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        db.commit()

    app_obj = getattr(current_app, "_get_current_object", lambda: current_app)()
    if current_app.config.get("TESTING"):
        _run_refresh_job(app_obj, job_id)
    else:
        worker = threading.Thread(
            target=_run_refresh_job,
            args=(app_obj, job_id),
            daemon=True,
        )
        worker.start()

    flash("Refresh started in the background.")
    return redirect(url_for("games.index"))


@bp.route("/refresh/status")
@login_required
def refresh_status():
    job = _refresh_job_for_user(g.user["id"])
    if job is None:
        return jsonify({"status": "idle", "message": "No refresh job"})
    return jsonify(
        {
            "status": job["status"],
            "message": job["message"],
            "error": job["error"],
            "created_at": job["created_at"],
            "started_at": job["started_at"],
            "finished_at": job["finished_at"],
        }
    )


@bp.route("/edit")
@login_required
def set_edit():
    """Show inline edit mode."""
    return render(edit=True)


@bp.route("/edit/<int:gameid>", methods=("GET", "POST"))
@login_required
def set_edit_gameid(gameid):
    """Detailed edit page for a single game."""
    db = get_db()
    lookup_failed = False
    if request.method == "POST":
        bggid = request.form["bggid"]
        if _update_game_bgg_mapping(gameid, bggid):
            flash("BGG ID updated.")
            return redirect(url_for("games.set_edit_gameid", gameid=gameid))

        lookup_failed = True
        flash(
            f"Could not fetch BoardGameGeek details for ID {bggid}. "
            "The BGG API is not returning item details in this environment."
        )

    game = db.execute(
        "SELECT *"
        " FROM library as l LEFT OUTER JOIN bgg as g"
        " ON l.bgg_id = g.id"
        " WHERE l.id = ?",
        (gameid,),
    ).fetchone()
    if game is None:
        abort(404)

    game = dict(game)
    if game["gamep"]:
        gamep = pickle.loads(game["gamep"])
        game["bggname"] = gamep.name
        game["bggurl"] = f"https://boardgamegeek.com/boardgame/{gamep.id}/"
    else:
        game["bggname"] = None
        if lookup_failed and request.method == "POST":
            game["bggid"] = request.form.get("bggid", game.get("bggid"))

    return render_template("games/update.html", game=game)


@bp.route("/edit/<int:gameid>/quick", methods=("POST",))
@login_required
def quick_edit_gameid(gameid):
    bggid = request.form.get("bggid", "").strip()
    if not bggid:
        flash("BGG ID is required.")
        return redirect(url_for("games.set_edit"))

    if _update_game_bgg_mapping(gameid, bggid):
        flash("BGG ID updated.")
    else:
        flash(f"Could not fetch BoardGameGeek details for ID {bggid}.")
    return redirect(url_for("games.set_edit"))


@bp.route("/null/<int:gameid>")
@login_required
def set_null_gameid(gameid):
    """Remove BGG mapping from a game."""
    db = get_db()
    updated = db.execute(
        "UPDATE library SET bgg_id = ? WHERE id = ?",
        (None, gameid),
    )
    if updated.rowcount == 0:
        abort(404)

    db.commit()

    flash("BGG mapping removed.")
    return redirect(url_for("games.set_edit"))


@bp.route("/delete/<int:gameid>", methods=("POST",))
@login_required
def delete_game(gameid):
    db = get_db()
    db.execute("DELETE FROM list_game WHERE game_id = ?", (gameid,))
    deleted = db.execute("DELETE FROM library WHERE id = ?", (gameid,))
    db.execute(
        "DELETE FROM bgg WHERE id NOT IN (SELECT DISTINCT bgg_id FROM library WHERE bgg_id IS NOT NULL)"
    )
    db.commit()
    if deleted.rowcount == 0:
        abort(404)

    flash("Game deleted.")
    return redirect(url_for("games.set_edit"))


@bp.route("/lists/create", methods=("POST",))
@login_required
def create_list():
    listname = request.form.get("listname", "").strip()
    if not listname:
        flash("List name is required.")
        return redirect(url_for("games.show_lists"))

    _get_or_create_list_id(g.user["id"], listname)
    flash(f"List '{listname}' is ready.")
    return redirect(url_for("games.set_editlist", listname=listname))


@bp.route("/lists")
@login_required
def show_lists():
    """Show lists for the current user."""
    db = get_db()
    list_names = sorted(
        {
            row["name"]
            for row in db.execute(
                "SELECT name FROM list WHERE user_id = ? ORDER BY name",
                (g.user["id"],),
            ).fetchall()
        }
    )
    return render_template("games/lists.html", names=list_names)


@bp.route("/list/<listname>")
@login_required
def set_list(listname):
    """Show list for current user."""
    return render(listname=listname, editlist=False)


@bp.route("/list/<listname>/not")
@login_required
def set_list_invert(listname):
    """Show inverse of a list for current user."""
    return render(listname=listname, editlist=False, invert=True)


@bp.route("/list/<listname>/edit", methods=("GET", "POST"))
@login_required
def set_editlist(listname):
    """Edit list membership for current user."""
    list_row = _get_list_row(g.user["id"], listname)
    if list_row is None and request.method == "GET":
        abort(404)

    list_id = _get_or_create_list_id(g.user["id"], listname)
    if request.method == "POST":
        db = get_db()
        db.execute("DELETE FROM list_game WHERE list_id = ?", (list_id,))
        for key in request.form:
            db.execute(
                "INSERT INTO list_game (list_id, game_id) VALUES (?, ?)",
                (list_id, int(key)),
            )
        db.commit()
        flash("List updated.")

    return render(listname=listname, editlist=True)


@bp.route("/list/<listname>/remove/<int:gameid>", methods=("POST",))
@login_required
def remove_from_list(listname, gameid):
    list_row = _get_list_row(g.user["id"], listname)
    if list_row is None:
        abort(404)

    db = get_db()
    db.execute(
        "DELETE FROM list_game WHERE list_id = ? AND game_id = ?",
        (list_row["id"], gameid),
    )
    db.commit()
    flash("Game removed from list.")
    return redirect(url_for("games.set_editlist", listname=listname))
