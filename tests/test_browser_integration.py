import time

from LibraryGames.db import BggGame
from LibraryGames.db import BggRank
from LibraryGames.db import get_db


def _seed_game(app, game_id=1, name="Sample Game"):
    with app.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO library (id, bgg_id, name, url) VALUES (?, ?, ?, ?)",
            (game_id, None, name, f"https://example.com/game/{game_id}"),
        )
        db.commit()


def _seed_list(app, user_id=1, name="favorites", game_ids=None):
    game_ids = game_ids or []
    with app.app_context():
        db = get_db()
        db.execute("INSERT OR IGNORE INTO list (user_id, name) VALUES (?, ?)", (user_id, name))
        list_row = db.execute(
            "SELECT id FROM list WHERE user_id = ? AND name = ?",
            (user_id, name),
        ).fetchone()
        for game_id in game_ids:
            db.execute(
                "INSERT OR IGNORE INTO list_game (list_id, game_id) VALUES (?, ?)",
                (list_row["id"], game_id),
            )
        db.commit()


def test_phase1_browser_auth_and_user_isolation(client, auth, app):
    _seed_game(app, 1, "Ticket to Ride")
    _seed_list(app, user_id=1, name="favorites", game_ids=[1])
    _seed_list(app, user_id=2, name="private")

    login_redirect = client.get("/lists")
    assert login_redirect.status_code == 302

    auth.login(username="test", password="test")
    page = client.get("/lists")
    assert page.status_code == 200
    assert b"favorites" in page.data
    assert b"private" not in page.data


def test_phase2_browser_refresh_status_flow(client, auth, monkeypatch):
    def fake_refresh_db():
        time.sleep(0.05)

    auth.login(username="test", password="test")
    monkeypatch.setattr("LibraryGames.games.refresh_db", fake_refresh_db)

    start = client.get("/refresh", follow_redirects=True)
    status = client.get("/refresh/status")

    assert start.status_code == 200
    assert b"Refresh started in the background." in start.data
    assert status.status_code == 200
    assert status.get_json()["status"] in {"queued", "running", "success"}


def test_phase3_browser_quick_edit_and_delete(client, auth, app, monkeypatch):
    _seed_game(app, 1, "Ticket to Ride")
    _seed_list(app, user_id=1, name="favorites", game_ids=[1])

    bgg_game = BggGame(
        id=9209,
        name="Ticket to Ride",
        year=2004,
        ranks=[BggRank(id=1, friendlyname="Board Game Rank", value="1")],
        designers=["Alan R. Moon"],
    )

    class _BggClient:
        def hot_items(self, item_type):
            return []

        def search(self, query):
            return []

        def game(self, game_id):
            return bgg_game

    auth.login(username="test", password="test")
    monkeypatch.setattr("LibraryGames.games._get_bgg_client", lambda: _BggClient())

    updated = client.post("/edit/1/quick", data={"bggid": "9209"}, follow_redirects=True)
    deleted = client.post("/delete/1", follow_redirects=True)

    assert updated.status_code == 200
    assert b"BGG ID updated." in updated.data
    assert deleted.status_code == 200
    assert b"Game deleted." in deleted.data


def test_phase4_browser_error_state_visible(client, auth, monkeypatch):
    def fake_refresh_db():
        raise RuntimeError("simulated upstream failure")

    auth.login(username="test", password="test")
    monkeypatch.setattr("LibraryGames.games.refresh_db", fake_refresh_db)

    client.get("/refresh", follow_redirects=True)
    status = client.get("/refresh/status")

    assert status.status_code == 200
    payload = status.get_json()
    assert payload["status"] in {"failed", "running", "queued"}
    if payload["status"] == "failed":
        assert payload["error"] == "simulated upstream failure"
