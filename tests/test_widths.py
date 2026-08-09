"""Reading numbers the way the games actually store them."""

from __future__ import annotations

import numpy as np
import pytest

from dowser import ScanSession, build_address_space, equals
from dowser.memory import WRAM_BANK0_BASE, WRAM_BANK_SIZE
from dowser.widths import resolve

RNG = np.random.default_rng(881988)


def space_for(ram: bytes, *, color: bool = False):
    return build_address_space(bytes(ram), b"\x00" * 0x7F, color_mode=color)


def find(ram: bytes, width: str, value: int) -> list[int]:
    session = ScanSession(width=width)
    session.scan(space_for(ram), equals(value))
    return [c.address for c in session.candidates()]


def noise(size: int = 2 * WRAM_BANK_SIZE) -> bytearray:
    return bytearray(RNG.integers(0, 256, size=size, dtype=np.uint8).tobytes())


# ---- BCD, which is how displayed numbers are stored ------------------------


def test_money_is_found_as_bcd_and_missed_as_binary():
    """¥123456 is stored 12 34 56, so a binary search for it finds nothing."""
    ram = noise()
    ram[0x300:0x303] = bytes([0x12, 0x34, 0x56])

    assert WRAM_BANK0_BASE + 0x300 in find(ram, "bcd3", 123456)
    assert find(ram, "u24be", 123456) == []


def test_bcd_rejects_bytes_that_are_not_decimal_digits():
    """0xAB has no decimal reading, so it must never match anything."""
    ram = bytearray(0x2000)
    ram[0x10:0x12] = bytes([0xAB, 0xCD])

    space = space_for(ram)
    valid = space.valid("bcd2")
    assert not valid[0x10]


def test_bcd_validity_is_itself_a_strong_filter():
    """Most random memory isn't valid BCD, which is why money converges fast."""
    space = space_for(noise())
    fraction = space.valid("bcd3").mean()
    assert 0.0 < fraction < 0.35


def test_coins_as_two_byte_bcd():
    ram = noise()
    ram[0x500:0x502] = bytes([0x99, 0x99])
    assert WRAM_BANK0_BASE + 0x500 in find(ram, "bcd2", 9999)


# ---- Big-endian, which is how Pokémon stores its own structures ------------


def test_pokemon_hp_is_big_endian():
    """A Pokémon with 300 HP stores 01 2C, not 2C 01."""
    ram = noise()
    ram[0x800:0x802] = bytes([0x01, 0x2C])

    assert WRAM_BANK0_BASE + 0x800 in find(ram, "u16be", 300)
    # The reading everyone reaches for first, which silently finds nothing.
    assert WRAM_BANK0_BASE + 0x800 not in find(ram, "u16le", 300)


def test_experience_is_three_bytes_big_endian():
    ram = noise()
    ram[0x900:0x903] = bytes([0x01, 0x86, 0xA0])  # 100,000
    assert WRAM_BANK0_BASE + 0x900 in find(ram, "u24be", 100_000)


def test_little_endian_still_works_for_engine_counters():
    ram = noise()
    ram[0xA00:0xA02] = bytes([0x0F, 0x27])  # 9999 low byte first
    assert WRAM_BANK0_BASE + 0xA00 in find(ram, "u16le", 9999)


# ---- Region seams ----------------------------------------------------------


@pytest.mark.parametrize("width", ["u16le", "u16be", "u24be", "bcd2", "bcd3"])
def test_no_width_reads_across_a_bank_boundary(width):
    """Banks are adjacent in the file and nowhere else."""
    ram = bytearray(2 * WRAM_BANK_SIZE)
    # A pattern that would decode to something at the seam if it were read.
    ram[WRAM_BANK_SIZE - 2 : WRAM_BANK_SIZE + 2] = bytes([0x12, 0x34, 0x56, 0x78])

    space = space_for(ram)
    size = resolve(width).size
    valid = space.valid(width)
    # The last `size - 1` bytes of bank 0 cannot start a value.
    for offset in range(1, size):
        assert not valid[WRAM_BANK_SIZE - offset]


def test_room_is_exact_at_the_end_of_a_region():
    ram = bytearray(2 * WRAM_BANK_SIZE)
    space = space_for(ram)
    valid = space.valid("u24be")
    assert valid[WRAM_BANK_SIZE - 3]
    assert not valid[WRAM_BANK_SIZE - 2]


# ---- Plumbing --------------------------------------------------------------


def test_old_integer_widths_still_work():
    assert resolve(8).key == "u8"
    assert resolve(16).key == "u16le"
    assert ScanSession(width=8).width == "u8"


def test_an_unknown_width_says_what_is_available():
    with pytest.raises(ValueError, match="u16be"):
        resolve("u64")


def test_maximums_are_what_the_reading_can_hold():
    assert resolve("bcd3").maximum == 999_999
    assert resolve("u16be").maximum == 0xFFFF
    assert resolve("u8").maximum == 0xFF
