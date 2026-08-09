"""The search has to find a planted address and reject everything else."""

from __future__ import annotations

import numpy as np
import pytest

from dowser import (
    NeedsPrevious,
    ScanSession,
    build_address_space,
    changed,
    decreased,
    decreased_by,
    equals,
    increased,
    unchanged,
)
from dowser.memory import WRAM_BANK0_BASE, WRAM_BANK_SIZE

RNG = np.random.default_rng(20260809)


def make_ram(banks: int = 2) -> bytearray:
    """Work RAM with plausible noise in it.

    Zero-filled RAM would make the search look far better than it is: almost
    every address would be eliminated by the first filter for free.
    """
    return bytearray(RNG.integers(0, 256, size=banks * WRAM_BANK_SIZE, dtype=np.uint8).tobytes())


def space_for(ram: bytes, *, color: bool = False):
    return build_address_space(bytes(ram), b"\x00" * 0x7F, color_mode=color)


def test_finds_a_planted_value_through_successive_filters():
    # Health at 0xC123, which in a two-bank layout is bank 0, offset 0x123.
    offset = 0x123
    address = WRAM_BANK0_BASE + offset

    before = make_ram()
    before[offset] = 47

    after = bytearray(before)
    after[offset] = 31
    # A dozen other bytes move too, the way a real frame would.
    for i in RNG.choice(len(after), size=12, replace=False):
        after[int(i)] = int(RNG.integers(0, 256))

    session = ScanSession(width=8)
    first = session.scan(space_for(before), equals(47))
    assert first > 1, "a single-byte value should not be unique on the first pass"

    session.scan(space_for(after), decreased())
    session.scan(space_for(after), equals(31))

    found = session.candidates()
    assert [c.address for c in found] == [address]
    assert found[0].value == 31
    assert found[0].bank == 0


def test_decreased_by_is_sharper_than_decreased():
    offset = 0x400
    before = make_ram()
    before[offset] = 100
    after = bytearray(before)
    after[offset] = 88

    loose = ScanSession()
    loose.scan(space_for(before), equals(100))
    loose_remaining = loose.scan(space_for(after), decreased())

    exact = ScanSession()
    exact.scan(space_for(before), equals(100))
    exact_remaining = exact.scan(space_for(after), decreased_by(12))

    assert exact_remaining <= loose_remaining
    assert WRAM_BANK0_BASE + offset in [c.address for c in exact.candidates()]


def test_decreased_by_does_not_wrap_at_zero():
    """`prev - delta` below zero must match nothing, not wrap to 0xFA."""
    ram = bytearray(len(make_ram()))
    ram[0x10] = 5
    before = space_for(ram)

    after_ram = bytearray(ram)
    after_ram[0x10] = 251  # what an unsigned 5 - 10 would look like
    after = space_for(after_ram)

    session = ScanSession()
    session.scan(before, equals(5))
    assert session.scan(after, decreased_by(10)) == 0


def test_sixteen_bit_value_spanning_two_bytes():
    """A counter above 255 is invisible to an 8-bit scan."""
    offset = 0x200
    value = 9999
    ram = make_ram()
    ram[offset] = value & 0xFF
    ram[offset + 1] = value >> 8

    wide = ScanSession(width=16)
    wide.scan(space_for(ram), equals(value))
    assert WRAM_BANK0_BASE + offset in [c.address for c in wide.candidates()]

    narrow = ScanSession(width=8)
    assert narrow.scan(space_for(ram), equals(value & 0xFFFF)) == 0


def test_sixteen_bit_reads_do_not_straddle_regions():
    """The last byte of one bank and the first of the next are not a number."""
    ram = bytearray(2 * WRAM_BANK_SIZE)
    ram[WRAM_BANK_SIZE - 1] = 0x34
    ram[WRAM_BANK_SIZE] = 0x12

    session = ScanSession(width=16)
    assert session.scan(space_for(ram), equals(0x1234)) == 0


def test_unchanged_and_changed_partition_the_space():
    before_ram = make_ram()
    after_ram = bytearray(before_ram)
    for i in RNG.choice(len(after_ram), size=40, replace=False):
        after_ram[int(i)] = (after_ram[int(i)] + 1) % 256

    before, after = space_for(before_ram), space_for(after_ram)

    still = ScanSession()
    still.scan(before, equals(int(before_ram[0])))
    still_count = still.scan(after, unchanged())

    moved = ScanSession()
    moved.scan(before, equals(int(before_ram[0])))
    moved_count = moved.scan(after, changed())

    total = ScanSession()
    total_count = total.scan(before, equals(int(before_ram[0])))

    assert still_count + moved_count == total_count


def test_relative_filter_first_is_an_error():
    session = ScanSession()
    with pytest.raises(NeedsPrevious):
        session.scan(space_for(make_ram()), increased())


def test_mismatched_layouts_are_refused():
    session = ScanSession()
    session.scan(space_for(make_ram(banks=2)), equals(0))
    with pytest.raises(ValueError, match="layout changed"):
        session.scan(space_for(make_ram(banks=8), color=True), equals(0))


def test_colour_mode_exposes_all_eight_banks():
    ram = make_ram(banks=8)
    mono = space_for(ram, color=False)
    colour = space_for(ram, color=True)
    assert len(mono) == 2 * WRAM_BANK_SIZE + 0x7F
    assert len(colour) == 8 * WRAM_BANK_SIZE + 0x7F


def test_banked_addresses_report_their_bank():
    """Banks 1 and 5 both answer to 0xD000, so the bank has to come back too."""
    ram = bytearray(8 * WRAM_BANK_SIZE)
    ram[5 * WRAM_BANK_SIZE + 0x40] = 77

    session = ScanSession()
    session.scan(space_for(ram, color=True), equals(77))
    found = session.candidates()

    assert len(found) == 1
    assert found[0].bank == 5
    assert found[0].address == 0xD040
