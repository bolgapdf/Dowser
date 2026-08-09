"""The CLI, driven the way a search actually goes: one command at a time."""

from __future__ import annotations

import numpy as np
import pytest

from dowser.cli import main
from tests.test_snapshot import write_state

RNG = np.random.default_rng(1998)


@pytest.fixture
def game(tmp_path):
    """Three states of a game where the value at 0xC123 goes 47 -> 31 -> 31."""
    base = bytearray(RNG.integers(0, 256, size=0x8000, dtype=np.uint8).tobytes())
    base[0x123] = 47

    hit = bytearray(base)
    hit[0x123] = 31
    for i in RNG.choice(0x8000, size=30, replace=False):
        hit[int(i)] = int(RNG.integers(0, 256))

    idle = bytearray(hit)
    for i in RNG.choice(0x8000, size=30, replace=False):
        idle[int(i)] = int(RNG.integers(0, 256))
    idle[0x123] = 31

    return {
        "before": write_state(tmp_path / "1.state", work_ram=bytes(base), color_mode=False),
        "after": write_state(tmp_path / "2.state", work_ram=bytes(hit), color_mode=False),
        "idle": write_state(tmp_path / "3.state", work_ram=bytes(idle), color_mode=False),
        "session": tmp_path / "s.npz",
    }


def run(session, *argv) -> int:
    return main(["--session", str(session), *[str(a) for a in argv]])


def test_a_whole_search(game, capsys):
    session = game["session"]

    assert run(session, "new", "--width", "u8") == 0
    run(session, "scan", game["before"], "equals", "47")
    first = capsys.readouterr().out
    assert "candidates" in first

    run(session, "scan", game["after"], "decreased")
    run(session, "scan", game["idle"], "unchanged")
    capsys.readouterr()

    run(session, "list")
    listed = capsys.readouterr().out
    assert "$C123 = 31" in listed


def test_history_records_every_round(game, capsys):
    session = game["session"]
    run(session, "new")
    run(session, "scan", game["before"], "equals", "47")
    run(session, "scan", game["after"], "decreased")
    capsys.readouterr()

    run(session, "history")
    out = capsys.readouterr().out
    assert "equals 47" in out
    assert "decreased" in out


def test_json_output_is_machine_readable(game, capsys):
    import json

    session = game["session"]
    run(session, "new")
    run(session, "scan", game["before"], "equals", "47")
    run(session, "scan", game["after"], "decreased")
    run(session, "scan", game["idle"], "unchanged")
    capsys.readouterr()

    run(session, "list", "--json")
    parsed = json.loads(capsys.readouterr().out)
    assert {"region", "bank", "address", "value", "width"} <= parsed[0].keys()
    assert 0xC123 in [entry["address"] for entry in parsed]


def test_relative_filter_first_explains_itself(game):
    session = game["session"]
    run(session, "new")
    with pytest.raises(SystemExit, match="absolute filter"):
        run(session, "scan", game["before"], "decreased")


def test_wrong_argument_count_is_caught(game):
    session = game["session"]
    run(session, "new")
    with pytest.raises(SystemExit, match="takes 1 value"):
        run(session, "scan", game["before"], "equals")


def test_scanning_without_a_session_says_so(tmp_path, game):
    with pytest.raises(SystemExit, match="Run `dowser new`"):
        run(tmp_path / "missing.npz", "scan", game["before"], "equals", "47")


def test_a_missing_state_file(game):
    session = game["session"]
    run(session, "new")
    with pytest.raises(SystemExit):
        run(session, "scan", "nope.state", "equals", "1")


def test_code_command_accepts_hex_in_the_forms_people_type(capsys):
    for text in ("C123", "$C123", "0xC123"):
        main(["code", text, "255"])
        assert capsys.readouterr().out.strip() == "01FF23C1"


def test_code_command_rejects_an_impossible_value():
    with pytest.raises(SystemExit, match="does not fit"):
        main(["code", "C123", "300"])
