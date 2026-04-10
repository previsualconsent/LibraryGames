import sqlite3

import pytest

from LibraryGames.db import BggClientAdapter
from LibraryGames.db import get_db
from LibraryGames.db import hamming
from LibraryGames.db import no_punctuation


class _FakeAiohttpResponse:
    def __init__(self, status, text):
        self.status = status
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self):
        return self._text


class _FakeAiohttpSession:
    def __init__(self, status=401, text="Unauthorized"):
        self.status = status
        self.text_value = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def get(self, *args, **kwargs):
        return _FakeAiohttpResponse(self.status, self.text_value)


def test_get_close_db(app):
    with app.app_context():
        db = get_db()
        assert db is get_db()

    with pytest.raises(sqlite3.ProgrammingError) as e:
        db.execute("SELECT 1")

    assert "closed" in str(e.value)


def test_init_db_command(runner, monkeypatch):
    class Recorder(object):
        called = False

    def fake_init_db():
        Recorder.called = True

    monkeypatch.setattr("LibraryGames.db.init_db", fake_init_db)
    result = runner.invoke(args=["init-db"])
    assert "Initialized" in result.output
    assert Recorder.called


def test_no_punctuation():
    assert no_punctuation(":Ticket to ride!") == "Ticket to ride"


def test_hamming_counts_non_matching_words():
    assert hamming("Ticket to Ride", "Ticket Ride") == (1, 0)


def test_bgg_adapter_search_falls_back_to_manual_mapping(monkeypatch):
    monkeypatch.setattr(
        "LibraryGames.db.aiohttp.ClientSession",
        lambda: _FakeAiohttpSession(),
    )

    results = BggClientAdapter().search(
        ":Ticket to ride : the cross-country train adventure game!"
    )

    assert len(results) == 1
    assert results[0].id == 9209
    assert results[0].name == "Ticket to Ride"


def test_bgg_adapter_hot_items_handles_unauthorized(monkeypatch):
    monkeypatch.setattr(
        "LibraryGames.db.aiohttp.ClientSession",
        lambda: _FakeAiohttpSession(),
    )

    assert BggClientAdapter().hot_items("boardgame") == []
