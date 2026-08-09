"""The guided searches, and the name lookup behind the pickers."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from dowser import gen2, recipes, web  # noqa: E402
from tests.test_live import FakeCartridge  # noqa: E402


@pytest.fixture
def client():
    server = FakeCartridge()
    web.search.port = server.port
    web.search.reset("u8")
    web.search.frozen = []
    with TestClient(web.app) as client:
        yield client
    server.close()


# ---- the data ---------------------------------------------------------------


def test_generation_two_numbers_species_in_dex_order():
    """Which is why Mew is simply 151, and how the Mew hunt worked."""
    assert gen2.SPECIES[151] == "Mew"
    assert gen2.SPECIES[1] == "Bulbasaur"
    assert gen2.SPECIES[251] == "Celebi"
    assert len(gen2.SPECIES) == 251


def test_species_verified_against_a_real_search():
    """The three we actually saw on screen while finding the encounter slot."""
    assert gen2.SPECIES[16] == "Pidgey"
    assert gen2.SPECIES[161] == "Sentret"
    assert gen2.SPECIES[13] == "Weedle"


# ---- pickers ----------------------------------------------------------------


def test_typing_a_prefix_finds_the_species(client):
    names = [n["name"] for n in client.get("/api/names?kind=species&q=pid").json()["names"]]
    # Prefix matches first and shortest first inside those, so the one you
    # probably meant is at the top. Rapidash matches too, and comes last.
    assert names == ["Pidgey", "Pidgeot", "Pidgeotto", "Rapidash"]


def test_a_prefix_beats_a_match_in_the_middle(client):
    """Typing `mew` should offer Mew before Mewtwo."""
    names = client.get("/api/names?kind=species&q=mew").json()["names"]
    assert names[0]["name"] == "Mew"


def test_an_empty_query_leads_with_the_interesting_ones(client):
    names = client.get("/api/names?kind=species").json()["names"]
    assert names[0]["number"] == 151


def test_a_number_typed_directly_is_offered(client):
    names = client.get("/api/names?kind=species&q=151").json()["names"]
    assert names[0]["number"] == 151


def test_items_have_their_own_list(client):
    names = client.get("/api/names?kind=item&q=master").json()["names"]
    assert names[0] == {"number": 1, "name": "Master Ball"}


def test_an_unknown_kind_is_refused(client):
    assert client.get("/api/names?kind=moves").status_code == 400


# ---- recipes ----------------------------------------------------------------


def test_every_recipe_is_coherent():
    """Cheap structural check, so a typo in the table fails here not in the UI."""
    from dowser.widths import resolve

    for recipe in recipes.RECIPES:
        assert recipe.steps, f"{recipe.id} has no steps"
        assert resolve(recipe.width)
        assert recipe.applies in ("number", "species", "item")
        for step in recipe.steps:
            assert step.filter in recipes.ASK, f"{recipe.id}: unknown filter {step.filter}"
            _factory, arity = recipes.ASK[step.filter]
            needs_value = step.answer in ("number", "species", "item")
            assert arity == (1 if needs_value else 0), (
                f"{recipe.id}: '{step.filter}' takes {arity} value(s) "
                f"but the step asks for {step.answer!r}"
            )
        # A first step can't be relative — there is nothing to compare against.
        first = recipe.steps[0]
        if first.filter in ("decreased", "increased", "changed"):
            raise AssertionError(f"{recipe.id} starts with a relative filter")


def test_money_uses_bcd_and_experience_uses_big_endian():
    assert recipes.BY_ID["money"].width == "bcd3"
    assert recipes.BY_ID["experience"].width == "u24be"
    assert recipes.BY_ID["stats"].width == "u16be"


def test_starting_a_recipe_sets_its_width(client):
    body = client.post("/api/recipes/money/start").json()
    assert body["width"] == "bcd3"
    assert body["recipe"]["stepNumber"] == 1
    assert body["recipe"]["step"]["answer"] == "number"


def test_walking_through_a_recipe(client):
    client.post("/api/recipes/wild-species/start")

    first = client.post("/api/recipes/step", json={"value": 16}).json()
    assert first["recipe"]["stepNumber"] == 2
    assert first["started"] is True

    second = client.post("/api/recipes/step", json={"value": 16}).json()
    assert second["recipe"]["stepNumber"] == 3

    third = client.post("/api/recipes/step", json={"value": 16}).json()
    assert third["recipe"]["done"] is True
    assert third["recipe"]["step"] is None


def test_a_step_that_needs_a_number_says_so(client):
    client.post("/api/recipes/wild-species/start")
    response = client.post("/api/recipes/step", json={})
    assert response.status_code == 400
    assert "needs a number" in response.json()["detail"]


def test_stopping_early(client):
    client.post("/api/recipes/wild-species/start")
    client.post("/api/recipes/step", json={"value": 16})
    body = client.post("/api/recipes/skip", json={}).json()
    assert body["recipe"]["done"] is True


def test_stopping_before_starting_is_refused(client):
    client.post("/api/recipes/wild-species/start")
    assert client.post("/api/recipes/skip", json={}).status_code == 400


def test_an_unknown_recipe(client):
    assert client.post("/api/recipes/infinite-vibes/start").status_code == 404


def test_stepping_without_a_recipe(client):
    assert client.post("/api/recipes/step", json={"value": 1}).status_code == 400


def test_the_recipe_list_is_offered(client):
    listed = client.get("/api/recipes").json()["recipes"]
    ids = {r["id"] for r in listed}
    assert {"wild-species", "money", "item-slot", "shiny", "experience"} <= ids


def test_widths_are_described_for_the_page(client):
    widths = {w["key"]: w for w in client.get("/api/widths").json()["widths"]}
    assert widths["bcd3"]["maximum"] == 999_999
    assert widths["u16be"]["bytes"] == 2
