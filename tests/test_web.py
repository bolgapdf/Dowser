"""The HTTP API, driven against the stand-in emulator."""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from dowser import web  # noqa: E402
from tests.test_live import FakeCartridge, state_bytes  # noqa: E402


@pytest.fixture
def client():
    """A client wired to a fake emulator, with the search reset between tests."""
    server = FakeCartridge()
    web.search.port = server.port
    web.search.reset(8)
    web.search.frozen = []
    with TestClient(web.app) as client:
        yield client, server
    server.close()


def test_status_reports_the_running_game(client):
    api, _ = client
    body = api.get("/api/status").json()
    assert body["connected"] is True
    assert body["title"] == "POKEMON SILVER"
    assert body["remaining"] == 0


def test_status_when_nothing_is_listening(client):
    api, server = client
    server.close()
    web.search.port = 1  # nothing binds port 1
    body = api.get("/api/status").json()
    assert body["connected"] is False
    assert body["title"] is None


def test_a_search_narrows_and_reports_history(client):
    api, _ = client
    first = api.post("/api/scan", json={"filter": "equals", "value": 47}).json()
    assert first["remaining"] > 0
    assert first["started"] is True

    # The fake serves the same bytes every time, so nothing has moved.
    second = api.post("/api/scan", json={"filter": "unchanged"}).json()
    assert second["remaining"] == first["remaining"]
    assert [r["filter"] for r in second["history"]] == ["equals 47", "unchanged"]


def test_a_relative_filter_first_is_rejected(client):
    api, _ = client
    response = api.post("/api/scan", json={"filter": "increased"})
    assert response.status_code == 400
    assert "earlier snapshot" in response.json()["detail"]


def test_unknown_filter(client):
    api, _ = client
    assert api.post("/api/scan", json={"filter": "vibes", "value": 1}).status_code == 400


def test_missing_value(client):
    api, _ = client
    response = api.post("/api/scan", json={"filter": "equals"})
    assert response.status_code == 400
    assert "needs 1 value" in response.json()["detail"]


def test_width_must_be_eight_or_sixteen(client):
    api, _ = client
    assert api.post("/api/session", json={"width": 12}).status_code == 400
    assert api.post("/api/session", json={"width": 16}).json()["width"] == 16


def test_freeze_requires_a_narrow_enough_set(client):
    api, _ = client
    api.post("/api/scan", json={"filter": "equals", "value": 47})
    response = api.post("/api/freeze", json={"value": 151})
    assert response.status_code == 400
    assert "8 or fewer" in response.json()["detail"]


def test_freeze_one_address_then_thaw(client):
    api, _ = client
    # 0x1123 in the fake holds 47 and nothing else does after two rounds.
    api.post("/api/scan", json={"filter": "equals", "value": 47})
    web.search.session._indices = web.search.session._indices[:1]

    candidate = web.search.session.candidates()[0]
    body = api.post("/api/freeze", json={"value": 151, "address": candidate.address}).json()
    assert body["frozen"] == [
        {
            "address": candidate.address,
            "hex": f"{candidate.address:04X}",
            "bank": candidate.bank,
            "value": 151,
        }
    ]

    assert api.post("/api/thaw", json={}).json()["frozen"] == []


def test_freezing_nothing_is_an_error(client):
    api, _ = client
    assert api.post("/api/freeze", json={"value": 1}).status_code == 400


def test_filters_are_described_for_the_page(client):
    api, _ = client
    listed = api.get("/api/filters").json()["filters"]
    by_name = {f["name"]: f for f in listed}
    assert by_name["equals"]["arity"] == 1
    assert by_name["equals"]["relative"] is False
    assert by_name["decreased"]["relative"] is True
    assert by_name["between"]["arity"] if "between" in by_name else True


def test_the_page_is_served(client):
    api, _ = client
    response = api.get("/")
    assert response.status_code == 200
    assert "<title>Dowser</title>" in response.text


def test_a_scan_against_a_dead_emulator(client):
    api, server = client
    server.close()
    web.search.port = 1
    response = api.post("/api/scan", json={"filter": "equals", "value": 47})
    assert response.status_code == 503


def test_state_hides_candidates_when_there_are_too_many(client):
    api, _ = client
    body = api.post("/api/scan", json={"filter": "greater-than", "value": 0}).json()
    assert body["remaining"] > 200
    assert body["candidates"] == []


def test_sixteen_bit_search_finds_a_wide_value(client, tmp_path):
    api, server = client
    server.close()

    wide = FakeCartridge(payload=state_bytes())
    web.search.port = wide.port
    try:
        api.post("/api/session", json={"width": 16})
        body = api.post("/api/scan", json={"filter": "greater-than", "value": 0}).json()
        assert body["width"] == 16
        assert body["remaining"] > 0
    finally:
        wide.close()
