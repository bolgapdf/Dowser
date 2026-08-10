"""Remembering addresses, and releasing one cheat without disturbing others."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from dowser import saved, web  # noqa: E402
from tests.test_live import FakeCartridge  # noqa: E402


@pytest.fixture
def client(tmp_path):
    server = FakeCartridge()
    web.search.port = server.port
    web.search.reset("u8")
    web.search.frozen = []
    web.search.active = {}
    web.search.game = "POKEMON SILVER"
    web.search.library = saved.Library(tmp_path / "found.json")
    with TestClient(web.app) as client:
        yield client, server
    server.close()


def narrow_to_one(api) -> int:
    """Run the species search and cut it to a single candidate."""
    api.post("/api/recipes/wild-species/start")
    api.post("/api/recipes/step", json={"value": 47})
    web.search.session._indices = web.search.session._indices[:1]
    return web.search.session.candidates()[0].address


# ---- the store --------------------------------------------------------------


def test_a_found_address_survives_a_restart(tmp_path):
    path = tmp_path / "found.json"
    first = saved.Library(path)
    first.remember("POKEMON SILVER", "wild-species", [saved.Found(0xD0EF, 1, "u8", 161)])

    second = saved.Library(path)
    found = second.get("POKEMON SILVER", "wild-species")
    assert [(f.address, f.bank) for f in found] == [(0xD0EF, 1)]


def test_games_do_not_share_addresses(tmp_path):
    library = saved.Library(tmp_path / "f.json")
    library.remember("SILVER", "money", [saved.Found(0xD84E, 1, "bcd3")])
    assert library.get("CRYSTAL", "money") == []


def test_a_corrupt_file_is_survivable(tmp_path):
    path = tmp_path / "found.json"
    path.write_text("{not json at all")
    assert saved.Library(path).games() == []


def test_forgetting_one_recipe_leaves_the_others(tmp_path):
    library = saved.Library(tmp_path / "f.json")
    library.remember("SILVER", "money", [saved.Found(1, 0, "bcd3")])
    library.remember("SILVER", "wild-species", [saved.Found(2, 1, "u8")])

    library.forget("SILVER", "money")
    assert library.get("SILVER", "money") == []
    assert len(library.get("SILVER", "wild-species")) == 1


def test_writes_are_atomic(tmp_path):
    """A half-written file would lose the one thing that can't be re-derived."""
    path = tmp_path / "found.json"
    library = saved.Library(path)
    library.remember("SILVER", "money", [saved.Found(1, 0, "bcd3")])
    assert json.loads(path.read_text())["SILVER"]["money"][0]["address"] == 1
    assert not list(tmp_path.glob("*.tmp"))


# ---- the scenario that prompted all this ------------------------------------


def test_the_mew_problem(client):
    """Catch Mew, then switch to something else without searching again.

    Holding the encounter species at Mew means every encounter is Mew, so the
    search can never narrow again on that save. The address has to be kept.
    """
    api, _ = client
    address = narrow_to_one(api)

    # Find it once and hold it at Mew.
    api.post("/api/freeze", json={"value": 151, "address": address})
    assert web.search.library.get("POKEMON SILVER", "wild-species")

    # Come back later: the recipe opens already knowing the address.
    body = api.post("/api/recipes/wild-species/start").json()
    assert body["recipe"]["done"] is True
    assert body["recipe"]["remembered"][0]["address"] == address

    # Switch to Bulbasaur with no search at all.
    body = api.post("/api/recipes/wild-species/apply", json={"value": 1}).json()
    assert body["active"]["wild-species"]["value"] == 1


def test_releasing_one_cheat_leaves_the_other_held(client):
    api, server = client
    address = narrow_to_one(api)
    api.post("/api/freeze", json={"value": 151, "address": address})

    web.search.library.remember(
        "POKEMON SILVER", "item-quantity", [saved.Found(0xD892, 1, "u8", 5)]
    )
    api.post("/api/recipes/item-quantity/apply", json={"value": 99})
    assert set(web.search.active) == {"wild-species", "item-quantity"}

    api.post("/api/recipes/wild-species/release", json={})
    assert set(web.search.active) == {"item-quantity"}
    # And the emulator was told the surviving one, not left empty.
    assert any("FREEZE" in command for command in server.frozen)


def test_forgetting_lets_the_search_run_again(client):
    api, _ = client
    address = narrow_to_one(api)
    api.post("/api/freeze", json={"value": 151, "address": address})

    body = api.post("/api/recipes/wild-species/forget", json={}).json()
    assert body["recipe"]["remembered"] == []
    assert body["recipe"]["done"] is False
    assert body["recipe"]["stepNumber"] == 1
    assert web.search.active == {}


def test_applying_without_a_remembered_address(client):
    api, _ = client
    api.post("/api/recipes/money/start")
    response = api.post("/api/recipes/money/apply", json={"value": 999999})
    assert response.status_code == 400
    assert "nothing remembered" in response.json()["detail"]


def test_a_value_too_big_for_the_width(client):
    api, _ = client
    web.search.library.remember("POKEMON SILVER", "money", [saved.Found(0xD84E, 1, "bcd3")])
    api.post("/api/recipes/money/start")
    response = api.post("/api/recipes/money/apply", json={"value": 1_000_000})
    assert response.status_code == 400
    assert "between 0 and 999999" in response.json()["detail"]


def test_the_one_shot_cheats_are_marked(client):
    """The page warns before forgetting one of these, so mark them honestly."""
    api, _ = client
    assert api.post("/api/recipes/wild-species/start").json()["recipe"]["selfErasing"] is True
    assert api.post("/api/recipes/money/start").json()["recipe"]["selfErasing"] is False


def test_the_menu_knows_what_has_been_found(client):
    api, _ = client
    address = narrow_to_one(api)
    api.post("/api/freeze", json={"value": 151, "address": address})
    assert "wild-species" in api.get("/api/status").json()["knownIds"]
