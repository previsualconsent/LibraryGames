import time

import pytest


@pytest.mark.e2e
def test_playwright_auth_and_list_creation(page, live_server):
    username = f"pw_user_{int(time.time() * 1000)}"

    page.goto(live_server)
    page.get_by_role("link", name="Register").click()
    page.get_by_label("Username").fill(username)
    page.get_by_label("Password").fill("testpass")
    page.get_by_role("button", name="Register").click()

    page.get_by_label("Username").fill(username)
    page.get_by_label("Password").fill("testpass")
    page.get_by_role("button", name="Log In").click()

    page.get_by_role("link", name="Lists").click()
    page.get_by_label("New List").fill("playwright-list")
    page.get_by_role("button", name="Create").click()

    page.wait_for_url(f"{live_server}/list/playwright-list/edit")
    page.get_by_text("List 'playwright-list' is ready.").wait_for()
    assert "playwright-list" in page.get_by_role(
        "heading", name="Games - playwright-list - [Invert]"
    ).inner_text()


@pytest.mark.e2e
def test_playwright_refresh_status_flow(page, live_server, monkeypatch):
    username = f"pw_refresh_{int(time.time() * 1000)}"

    def fake_refresh_db():
        time.sleep(0.2)

    monkeypatch.setattr("LibraryGames.games.refresh_db", fake_refresh_db)

    page.goto(f"{live_server}/auth/register")
    page.get_by_label("Username").fill(username)
    page.get_by_label("Password").fill("testpass")
    page.get_by_role("button", name="Register").click()

    page.get_by_label("Username").fill(username)
    page.get_by_label("Password").fill("testpass")
    page.get_by_role("button", name="Log In").click()

    page.get_by_role("link", name="Refresh").click()

    page.get_by_text("Refresh started in the background.").wait_for()
    page.get_by_text("Refresh:").wait_for()
    page.wait_for_function(
        "() => document.body.innerText.includes('running - Refresh in progress') || document.body.innerText.includes('success - Refresh completed')"
    )
    page.wait_for_function(
        "() => document.body.innerText.includes('success - Refresh completed')"
    )
