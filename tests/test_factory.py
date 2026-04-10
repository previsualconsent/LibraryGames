from LibraryGames import create_app


def test_config():
    """Test create_app without passing test config."""
    assert not create_app().testing
    assert create_app({"TESTING": True}).testing


def test_database_can_be_overridden_with_environment(monkeypatch):
    sandbox_path = "/tmp/library-games-sandbox.sqlite"
    monkeypatch.setenv("LIBRARY_GAMES_DATABASE", sandbox_path)

    app = create_app()

    assert app.config["DATABASE"] == sandbox_path


def test_hello(client):
    response = client.get("/hello")
    assert response.data == b"Hello, World!"
