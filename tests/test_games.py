import pickle

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


def _seed_library_game(app, game_id=1, name="Sample Game", url="https://example.com/game/1", list_name=None, bgg_game=None):
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
        if list_name:
            db.execute(
                "INSERT INTO list_game (game_id, list_name) VALUES (?, ?)",
                (game_id, list_name),
            )
        db.commit()


def test_index_renders_games_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Games" in response.data
    assert b"Log In" in response.data
    assert b"Register" in response.data


def test_edit_page_renders_existing_library_game(client, app):
    _seed_library_game(app, game_id=1, name="Ticket to Ride")

    response = client.get("/edit/1")

    assert response.status_code == 200
    assert b"Edit BGG ID" in response.data
    assert b"Ticket to Ride" in response.data


def test_edit_page_missing_game_returns_404(client):
    assert client.get("/edit/999").status_code == 404


def test_edit_post_updates_bgg_mapping(client, app, monkeypatch):
    _seed_library_game(app, game_id=1, name="Ticket to Ride")
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

    response = client.post("/edit/1", data={"bggid": "9209"}, follow_redirects=True)

    assert response.status_code == 200
    assert b"BGG ID updated." in response.data
    with app.app_context():
        row = get_db().execute("SELECT bgg_id FROM library WHERE id = 1").fetchone()
        assert row["bgg_id"] == 9209


def test_edit_post_lookup_failure_preserves_input(client, app, monkeypatch):
    _seed_library_game(app, game_id=645097, name=":Ticket to ride : the cross-country train adventure game!")
    monkeypatch.setattr(
        "LibraryGames.games._get_bgg_client", lambda: _FixedGameClient(None)
    )

    response = client.post(
        "/edit/645097", data={"bggid": "12345"}, follow_redirects=True
    )

    assert response.status_code == 200
    assert b"Could not fetch BoardGameGeek details for ID 12345." in response.data
    assert b"value=\"12345\"" in response.data


def test_null_gameid_clears_mapping(client, app):
    bgg_game = BggGame(
        id=9209,
        name="Ticket to Ride",
        year=2004,
        ranks=[BggRank(id=1, friendlyname="Board Game Rank", value="1")],
        designers=["Alan R. Moon"],
    )
    _seed_library_game(app, game_id=1, name="Ticket to Ride", bgg_game=bgg_game)

    response = client.get("/null/1")

    assert response.status_code == 200
    with app.app_context():
        row = get_db().execute("SELECT bgg_id FROM library WHERE id = 1").fetchone()
        assert row["bgg_id"] is None


def test_lists_and_filters_render_expected_games(client, app):
    bgg_game = BggGame(
        id=9209,
        name="Ticket to Ride",
        year=2004,
        ranks=[BggRank(id=1, friendlyname="Board Game Rank", value="1")],
        designers=["Alan R. Moon"],
    )
    _seed_library_game(app, game_id=1, name="Ticket to Ride", list_name="favorites", bgg_game=bgg_game)
    _seed_library_game(app, game_id=2, name="Azul")

    lists_response = client.get("/lists")
    include_response = client.get("/list/favorites")
    exclude_response = client.get("/list/favorites/not")

    assert lists_response.status_code == 200
    assert b"favorites" in lists_response.data
    assert include_response.status_code == 200
    assert b"Ticket to Ride" in include_response.data
    assert exclude_response.status_code == 200
    assert b"Azul" in exclude_response.data


def test_edit_list_post_replaces_membership(client, app):
    _seed_library_game(app, game_id=1, name="Ticket to Ride", list_name="favorites")
    _seed_library_game(app, game_id=2, name="Azul")

    response = client.post("/list/favorites/edit", data={"2": "on"})

    assert response.status_code == 200
    with app.app_context():
        rows = get_db().execute(
            "SELECT game_id FROM list_game WHERE list_name = ? ORDER BY game_id",
            ("favorites",),
        ).fetchall()
        assert [row["game_id"] for row in rows] == [2]


def test_refresh_route_flashes_success(client, monkeypatch):
    called = {"value": False}

    def fake_refresh_db():
        called["value"] = True

    monkeypatch.setattr("LibraryGames.games.refresh_db", fake_refresh_db)

    response = client.get("/refresh", follow_redirects=True)

    assert response.status_code == 200
    assert called["value"] is True
    assert b"Games database refreshed." in response.data


def test_refresh_route_flashes_failure(client, monkeypatch):
    def fake_refresh_db():
        raise RuntimeError("boom")

    monkeypatch.setattr("LibraryGames.games.refresh_db", fake_refresh_db)

    response = client.get("/refresh", follow_redirects=True)

    assert response.status_code == 200
    assert b"Refresh failed: boom" in response.data