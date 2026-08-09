"""How a run of bytes turns into a number.

A cheat search is only as good as its idea of what a number looks like, and
Game Boy games disagree with each other constantly:

* Most engine counters are plain little-endian, because that's what the CPU is.
* Anything the game *displays* is often BCD, where 0x12 means twelve, not
  eighteen. Drawing digits from BCD is a nibble shift; drawing them from binary
  is repeated division, which an 8-bit CPU has no instruction for. This is the
  entire reason the SM83 has `DAA`.
* Pokémon stores its own 16- and 24-bit values **big-endian**, inside a
  little-endian machine, because the data structures were designed to be read
  most-significant byte first.

Searching for a displayed number with the wrong reading finds nothing at all,
which looks exactly like the value not being in memory.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Width:
    """One way of reading a number out of memory."""

    key: str
    size: int
    label: str
    #: Largest value this reading can represent, for validating user input.
    maximum: int
    description: str = ""

    @property
    def is_bcd(self) -> bool:
        return self.key.startswith("bcd")


WIDTHS: dict[str, Width] = {
    "u8": Width("u8", 1, "8-bit", 0xFF, "One byte. Levels, species, small counts."),
    "u16le": Width("u16le", 2, "16-bit", 0xFFFF, "Two bytes, low first. Most engine counters."),
    "u16be": Width(
        "u16be", 2, "16-bit big-endian", 0xFFFF, "Two bytes, high first. Pokémon HP and stats."
    ),
    "u24be": Width(
        "u24be", 3, "24-bit big-endian", 0xFFFFFF, "Three bytes, high first. Pokémon experience."
    ),
    "bcd2": Width(
        "bcd2", 2, "BCD, 2 bytes", 9_999, "Displayed numbers up to 9,999. Game Corner coins."
    ),
    "bcd3": Width("bcd3", 3, "BCD, 3 bytes", 999_999, "Displayed numbers up to 999,999. Money."),
}

#: Accepts the old integer form so existing callers keep working.
ALIASES = {8: "u8", 16: "u16le", 24: "u24be"}


def resolve(width: str | int) -> Width:
    key = ALIASES.get(width, width) if isinstance(width, int) else width
    if key not in WIDTHS:
        raise ValueError(f"unknown width {width!r}; try one of {', '.join(WIDTHS)}")
    return WIDTHS[key]


def _columns(values: np.ndarray, size: int) -> list[np.ndarray]:
    """`values` shifted by 0..size-1, so byte *n* of each candidate lines up.

    The tail is padded with zeroes; those indices are excluded by the validity
    mask rather than by shortening the array, so every array in the system stays
    the same length and indices mean one thing throughout.
    """
    columns = []
    for offset in range(size):
        column = np.zeros(values.size, dtype=np.uint32)
        if offset == 0:
            column[:] = values
        else:
            column[:-offset] = values[offset:]
        columns.append(column)
    return columns


def decode(values: np.ndarray, width: Width) -> np.ndarray:
    """Read every index as a number of this width."""
    columns = _columns(values, width.size)

    if width.key == "u8":
        return columns[0]
    if width.key == "u16le":
        return columns[0] | (columns[1] << 8)
    if width.key == "u16be":
        return (columns[0] << 8) | columns[1]
    if width.key == "u24be":
        return (columns[0] << 16) | (columns[1] << 8) | columns[2]

    if width.is_bcd:
        # Each byte is two decimal digits. Nibbles above 9 aren't BCD at all;
        # they decode to nonsense here and are masked out by `valid` below.
        total = np.zeros(values.size, dtype=np.uint32)
        for column in columns:
            total = total * 100 + (column >> 4) * 10 + (column & 0x0F)
        return total

    raise ValueError(f"no decoder for {width.key}")


def valid(values: np.ndarray, width: Width) -> np.ndarray:
    """Indices where this reading is meaningful.

    For BCD that means every nibble is a decimal digit. It's a strong filter on
    its own — random memory is only about 39% valid BCD per byte — which is why
    a money search converges so fast once it's reading the right format.
    """
    if not width.is_bcd:
        return np.ones(values.size, dtype=bool)

    ok = np.ones(values.size, dtype=bool)
    for column in _columns(values, width.size):
        ok &= ((column >> 4) <= 9) & ((column & 0x0F) <= 9)
    return ok
