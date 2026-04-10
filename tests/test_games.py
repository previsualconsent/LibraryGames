import pickle
import time

import pytest

from LibraryGames.db import BggGame
from LibraryGames.db import BggRank
from LibraryGames.db import get_db


class _DummyBggClient:
    def hot_items(self, item_type):
        return []

    def search(self, query):
        return []

    def game(self, game_id):
        return None


class _FixedGameClient(_DummyBggClient):
    def __init__(self, game):
        self._game = game

    def game(self, game_id):
        return self._game


@pytest.fixture(autouse=True)
def stub_bgg_client(monkeypatch):
    monkeypatch.setattr("LibraryGames.games._get_bgg_client", lambda: _DummyBggClient())


def _seed_library_game(
    app,
    game_id=1,
    name="Sample Game",
    url="https://example.com/game/1",
    bgg_game=None,
):
    with app.app_context():
        db = get_db()
        bgg_id = None
        if bgg_game is not None:
            bgg_id = bgg_game.id
            db.execute(
                "INSERT INTO bgg (id, gamep, updated) VALUES (?, ?, ?)",
                (bgg_game.id, pickle.dumps(bgg_game), "2026-04-10"),
            )
        db.execute(
            "INSERT INTO library (id, bgg_id, name, url) VALUES (?, ?, ?, ?)",
            (game_id, bgg_id, name, url),
        )
        db.commit()


def _seed_user_list(app, user_id=1, list_name="favorites", game_ids=None):
    game_ids = game_ids or []
    with app.app_context():
        db = get_db()
        db.execute(
            "INSERT OR IGNORE INTO list (user_id, name) VALUES (?, ?)",
            (user_id, list_name),
        )
        list_row = db.execute(
            "SELECT id FROM list WHERE user_id = ? AND name = ?",
            (user_id, list_name),
        ).fetchone()
        for game_id in game_ids:
            db.execute(
                "INSERT OR IGNORE INTO list_game (list_id, game_id) VALUES (?, ?)",
                (list_row["id"], game_id),
            )
        db.commit()


def test_index_renders_games_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Games" in response.data


def test_lists_require_login(client):
    response = client.get("/lists")
    assert response.status_code == 302
    assert response.headers["Location"] == "http://localhost/auth/login"


def test_user_sees_only_their_lists(client, auth, app):
    _seed_user_list(app, user_id=1, list_name="favorites")
    _seed_user_list(app, user_id=2, list_name="private")

    auth.login(username="test", password="test")
    response = client.get("/lists")

    assert response.status_code == 200
    assert b"favorites" in response.data
    assert b"private" not in response.data


def test_user_cannot_access_other_user_list(client, auth, app):
    _seed_user_list(app, user_id=2, list_name="private")

    auth.login(username="test", password="test")
    response = client.get("/list/private")

    assert response.status_code == 404


def test_create_list_route(client, auth):
    auth.login(username="test", password="test")
    response = client.post("/lists/create", data={"listname": "weekend"}, follow_redirects=True)

    assert response.status_code == 200
    assert b"List &#39;weekend&#39; is ready." in response.data


def test_background_refresh_starts_job(client, auth, monkeypatch):
    def fake_refresh_db():
        time.sleep(0.05)

    auth.login(username="test", password="test")
    monkeypatch.setattr("LibraryGames.games.refresh_db", fake_refresh_db)

    response = client.get("/refresh", follow_redirects=True)
    status_response = client.get("/refresh/status")

    assert response.status_code == 200
    assert b"Refresh started in the background." in response.data
    assert status_response.status_code == 200
    payload = status_response.get_json()
    assert payload["status"] in {"queued", "running", "success"}


def test_refresh_status_requires_login(client):
    response = client.get("/refresh/status")
    assert response.status_code == 302


def test_edit_page_renders_existing_library_game(client, auth, app):
    _seed_library_game(app, game_id=1, name="Ticket to Ride")
    auth.login(username="test", password="test")

    response = client.get("/edit/1")

    assert response.status_code == 200
    assert b"Edit BGG ID" in response.data
    assert b"Ticket to Ride" in response.data


def test_quick_edit_updates_bgg_mapping(client, auth, app, monkeypatch):
    _seed_library_game(app, game_id=1, name="Ticket to Ride")
    auth.login(username="test", password="test")
    bgg_game = BggGame(
        id=9209,
        name="Ticket to Ride",
        year=2004,
        ranks=[BggRank(id=1, friendlyname="Board Game Rank", value="1")],
        designers=["Alan R. Moon"],
    )
    monkeypatch.setattr(
        "LibraryGames.games._get_bgg_client", lambda: _FixedGameClient(bgg_game)
    )

    response = client.post("/edit/1/quick", data={"bggid": "9209"}, follow_redirects=True)

    assert response.status_code == 200
    assert b"BGG ID updated." in response.data


def test_delete_game_removes_catalog_entry(client, auth, app):
    _seed_library_game(app, game_id=1, name="Ticket to Ride")
    _seed_user_list(app, user_id=1, list_name="favorites", game_ids=[1])
    auth.login(username="test", password="test")

    response = client.post("/delete/1", follow_redirects=True)

    assert response.status_code == 200
    assert b"Game deleted." in response.data
    with app.app_context():
        row = get_db().execute("SELECT * FROM library WHERE id = 1").fetchone()
        assert row is None


def test_remove_from_list(client, auth, app):
    _seed_library_game(app, game_id=1, name="Ticket to Ride")
    _seed_user_list(app, user_id=1, list_name="favorites", game_ids=[1])
    auth.login(username="test", password="test")

    response = client.post("/list/favorites/remove/1", follow_redirects=True)

    assert response.status_code == 200
    assert b"Game removed from list." in response.data
    with app.app_context():
        list_row = get_db().execute(
            "SELECT id FROM list WHERE user_id = ? AND name = ?",
            (1, "favorites"),
        ).fetchone()
        rows = get_db().execute(
            "SELECT game_id FROM list_game WHERE list_id = ?",
            (list_row["id"],),
        ).fetchall()
        assert rows == []
