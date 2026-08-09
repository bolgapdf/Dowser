"""Reading states, verified against a file built the way Cartridge builds one."""

from __future__ import annotations

import plistlib
import zlib
from pathlib import Path

import pytest

from dowser import load, load_all
from dowser.snapshot import NotASaveState


def apple_compress(payload: bytes) -> bytes:
    """What NSData.compressed(using: .zlib) writes: raw DEFLATE, no header.

    The fakes used zlib.compress() at first, which meant the suite happily
    validated a format Cartridge never produces.
    """
    deflate = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
    return deflate.compress(payload) + deflate.flush()


def write_state(
    path: Path,
    *,
    title: str = "POKEMON SILVER",
    work_ram: bytes | None = None,
    cartridge_ram: bytes = b"",
    color_mode: bool = True,
    compress: bool = True,
) -> Path:
    """A state with the keys Codable synthesises from Cartridge's Snapshot."""
    plist = plistlib.dumps(
        {
            "title": title,
            "workRAM": work_ram if work_ram is not None else bytes(0x8000),
            "highRAM": bytes(0x7F),
            "unmappedIO": bytes(16),
            "mapper": {"romBank": 1, "ramBank": 0, "ramEnabled": True, "ram": cartridge_ram},
            "carriedCycles": 0,
            "colorMode": color_mode,
            "workRAMBank": 1,
        },
        fmt=plistlib.FMT_BINARY,
    )
    path.write_bytes(apple_compress(plist) if compress else plist)
    return path


def test_reads_a_compressed_state(tmp_path):
    ram = bytearray(0x8000)
    ram[0x123] = 47
    snapshot = load(write_state(tmp_path / "a.state", work_ram=bytes(ram)))

    assert snapshot.title == "POKEMON SILVER"
    assert snapshot.color_mode
    assert snapshot.work_ram[0x123] == 47


def test_reads_an_uncompressed_state(tmp_path):
    """Cartridge falls back to plain plist when zlib fails, so this must load."""
    snapshot = load(write_state(tmp_path / "b.state", compress=False))
    assert snapshot.title == "POKEMON SILVER"


def test_cartridge_ram_becomes_scannable_regions(tmp_path):
    snapshot = load(write_state(tmp_path / "c.state", cartridge_ram=bytes(0x4000)))
    names = {r.name for r in snapshot.address_space().regions}
    assert "sram" in names

    sram_banks = [r.bank for r in snapshot.address_space().regions if r.name == "sram"]
    assert sram_banks == [0, 1]  # 16 KB is two 8 KB banks


def test_states_from_different_games_are_refused(tmp_path):
    a = write_state(tmp_path / "a.state", title="POKEMON SILVER")
    b = write_state(tmp_path / "b.state", title="ZELDA")
    with pytest.raises(NotASaveState, match="different games"):
        load_all([a, b])


def test_a_file_that_is_not_a_state(tmp_path):
    path = tmp_path / "not.state"
    path.write_bytes(b"this is not a property list")
    with pytest.raises(NotASaveState):
        load(path)


def test_a_plist_missing_the_ram_keys(tmp_path):
    path = tmp_path / "partial.state"
    path.write_bytes(apple_compress(plistlib.dumps({"title": "X"}, fmt=plistlib.FMT_BINARY)))
    with pytest.raises(NotASaveState, match="highRAM|workRAM"):
        load(path)


def test_a_zlib_wrapped_state_still_loads(tmp_path):
    """The fallback path, in case a state was ever written the other way."""
    plist = plistlib.dumps(
        {"title": "X", "workRAM": bytes(0x2000), "highRAM": bytes(0x7F), "mapper": {}},
        fmt=plistlib.FMT_BINARY,
    )
    path = tmp_path / "wrapped.state"
    path.write_bytes(zlib.compress(plist))
    assert load(path).title == "X"
