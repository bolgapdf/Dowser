"""Turning a found address into a code, and back.

The classic Game Boy cheat-cartridge format is eight hex digits, `ttvvaaaa`:

    tt  type. 01 is the everyday one: write this value once per frame.
    vv  the value to write.
    aaaa  the address, byte-swapped, because the SM83 is little-endian and the
          format stores the address exactly as the console would.

So writing 0xFF to 0xDA19 is `01FF19DA`, which is why published codes look like
they have their address back to front. They do.

Bank note: the format predates the Color's eight banks of work RAM, and devices
disagreed about how to express one. Codes emitted here for banks 2 and above are
marked ambiguous rather than guessed at, because a code that silently targets
the wrong bank is worse than one that admits it can't say.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

WRITE_EACH_FRAME = 0x01

_CODE_PATTERN = re.compile(r"^[0-9A-Fa-f]{8}$")


@dataclass(frozen=True)
class Code:
    """One eight-digit code."""

    type_byte: int
    value: int
    address: int
    #: True when the address lives in a work RAM bank the format can't name.
    ambiguous_bank: bool = False
    bank: int = 0

    @property
    def text(self) -> str:
        low = self.address & 0xFF
        high = (self.address >> 8) & 0xFF
        return f"{self.type_byte:02X}{self.value:02X}{low:02X}{high:02X}"

    def __str__(self) -> str:
        if self.ambiguous_bank:
            return f"{self.text}  (work RAM bank {self.bank}; verify on your device)"
        return self.text


def parse(text: str) -> Code:
    """Read a code back into its parts.

    Accepts the spacing and dashes people actually paste, since published lists
    are inconsistent about both.
    """
    cleaned = text.strip().replace("-", "").replace(" ", "").replace(":", "")
    if not _CODE_PATTERN.match(cleaned):
        raise ValueError(f"not an eight-digit code: {text!r}")

    raw = int(cleaned, 16)
    type_byte = (raw >> 24) & 0xFF
    value = (raw >> 16) & 0xFF
    low = (raw >> 8) & 0xFF
    high = raw & 0xFF
    return Code(type_byte=type_byte, value=value, address=(high << 8) | low)


def encode(address: int, value: int, *, bank: int = 0, width: int = 8) -> list[Code]:
    """Codes that pin `address` to `value`.

    A 16-bit value needs two codes, one per byte, low first — the cheat hardware
    writes single bytes, so a two-byte counter is two separate pokes.
    """
    if not 0 <= address <= 0xFFFF:
        raise ValueError(f"address out of range: {address:#x}")
    if width not in (8, 16):
        raise ValueError(f"width must be 8 or 16, got {width}")

    limit = 0xFF if width == 8 else 0xFFFF
    if not 0 <= value <= limit:
        raise ValueError(f"value {value} does not fit in {width} bits")

    # Only 0xD000-0xDFFF is banked; bank 1 is what a mono game always sees
    # there, so it needs no qualification.
    ambiguous = bank >= 2 and 0xD000 <= address <= 0xDFFF

    if width == 8:
        return [Code(WRITE_EACH_FRAME, value, address, ambiguous_bank=ambiguous, bank=bank)]

    return [
        Code(WRITE_EACH_FRAME, value & 0xFF, address, ambiguous_bank=ambiguous, bank=bank),
        Code(
            WRITE_EACH_FRAME,
            (value >> 8) & 0xFF,
            address + 1,
            ambiguous_bank=ambiguous,
            bank=bank,
        ),
    ]
