"""The parts of a Game Boy's memory worth searching, laid out flat.

A cheat search only cares about memory a game writes to during play: work RAM,
high RAM, and whatever the cartridge carries. ROM is excluded because it never
changes, and video memory because a value found there is a picture of a number
rather than the number itself.

Regions are concatenated into one array so a filter is a single vectorised pass
instead of a loop per bank. The parallel `addresses` and `banks` arrays are what
turn an index in that flat array back into something you can write a code for.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Where each region lives in the CPU's address space.
SRAM_BASE = 0xA000
WRAM_BANK0_BASE = 0xC000
WRAM_BANKED_BASE = 0xD000
HRAM_BASE = 0xFF80

WRAM_BANK_SIZE = 0x1000
SRAM_BANK_SIZE = 0x2000


@dataclass(frozen=True)
class Region:
    """One contiguous, separately addressable run of bytes.

    `bank` is part of a region's identity rather than a detail of it: work RAM
    banks 1 and 5 both answer to 0xD000, so an address alone doesn't say what
    you found.
    """

    name: str
    bank: int
    base: int
    data: np.ndarray

    def __post_init__(self) -> None:
        if self.data.dtype != np.uint8:
            raise ValueError(f"{self.name}: expected uint8, got {self.data.dtype}")
        if self.data.ndim != 1:
            raise ValueError(f"{self.name}: expected a flat array")

    @property
    def label(self) -> str:
        return self.name if self.bank == 0 and self.name == "hram" else f"{self.name}:{self.bank}"


class AddressSpace:
    """Every scannable byte of one snapshot, flattened.

    Instances are immutable and cheap to hold: a scan keeps two of these at a
    time (the previous snapshot and the current one) to answer questions like
    "did this go down".
    """

    def __init__(self, regions: list[Region]) -> None:
        if not regions:
            raise ValueError("an address space needs at least one region")

        self.regions = regions
        self.values = np.concatenate([r.data for r in regions])

        self.addresses = np.concatenate(
            [np.arange(r.base, r.base + r.data.size, dtype=np.uint32) for r in regions]
        )
        self.banks = np.concatenate([np.full(r.data.size, r.bank, dtype=np.int16) for r in regions])
        self.region_ids = np.concatenate(
            [np.full(r.data.size, i, dtype=np.int32) for i, r in enumerate(regions)]
        )

        # A 16-bit value is two adjacent bytes, but only if they're adjacent in
        # the console's address space too. Without this, the last byte of work
        # RAM bank 3 and the first of bank 4 would read as a 16-bit number that
        # no game could ever have written.
        self.pair_ok = np.zeros(self.values.size, dtype=bool)
        offset = 0
        for region in regions:
            if region.data.size >= 2:
                self.pair_ok[offset : offset + region.data.size - 1] = True
            offset += region.data.size

    def __len__(self) -> int:
        return int(self.values.size)

    def read(self, width: int) -> np.ndarray:
        """The scannable values at every index, as 8- or 16-bit numbers.

        For 16-bit the result is little-endian, which is the byte order the
        SM83 uses and therefore the order games store counters in. Indices where
        a pair would straddle two regions are present but meaningless; callers
        mask them with `pair_ok`.
        """
        if width == 8:
            return self.values.astype(np.uint16)
        if width == 16:
            low = self.values.astype(np.uint16)
            high = np.zeros_like(low)
            high[:-1] = self.values[1:]
            return low | (high << 8)
        raise ValueError(f"width must be 8 or 16, got {width}")

    def valid(self, width: int) -> np.ndarray:
        """Indices that can hold a value of this width."""
        return self.pair_ok if width == 16 else np.ones(self.values.size, dtype=bool)

    def describe(self, index: int) -> str:
        region = self.regions[int(self.region_ids[index])]
        return f"{region.label} ${int(self.addresses[index]):04X}"

    def compatible_with(self, other: AddressSpace) -> bool:
        """Whether two snapshots can be compared index for index.

        They can't if the cartridge changed size or the emulator switched
        between mono and colour work RAM, and comparing them anyway would
        silently produce nonsense rather than an error.
        """
        return len(self.regions) == len(other.regions) and all(
            a.name == b.name and a.bank == b.bank and a.data.size == b.data.size
            for a, b in zip(self.regions, other.regions, strict=True)
        )


def build_address_space(
    work_ram: bytes,
    high_ram: bytes,
    cartridge_ram: bytes = b"",
    *,
    color_mode: bool = False,
) -> AddressSpace:
    """Assemble the searchable regions from the raw arrays in a save state.

    Work RAM is stored as one 32 KB block covering eight banks. A mono game only
    ever sees the first two, so scanning the rest would add 24 KB of stale
    candidates that can never change — noise that makes the first filter look
    far less effective than it is.
    """
    work = np.frombuffer(work_ram, dtype=np.uint8)
    bank_count = 8 if color_mode else 2
    available = work.size // WRAM_BANK_SIZE
    bank_count = min(bank_count, available)

    regions = [
        Region("wram", 0, WRAM_BANK0_BASE, work[:WRAM_BANK_SIZE].copy()),
    ]
    for bank in range(1, bank_count):
        start = bank * WRAM_BANK_SIZE
        regions.append(
            Region("wram", bank, WRAM_BANKED_BASE, work[start : start + WRAM_BANK_SIZE].copy())
        )

    if cartridge_ram:
        sram = np.frombuffer(cartridge_ram, dtype=np.uint8)
        for bank in range(max(1, sram.size // SRAM_BANK_SIZE)):
            start = bank * SRAM_BANK_SIZE
            chunk = sram[start : start + SRAM_BANK_SIZE]
            if chunk.size:
                regions.append(Region("sram", bank, SRAM_BASE, chunk.copy()))

    if high_ram:
        regions.append(Region("hram", 0, HRAM_BASE, np.frombuffer(high_ram, dtype=np.uint8).copy()))

    return AddressSpace(regions)
