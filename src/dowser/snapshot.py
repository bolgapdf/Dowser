"""Reading Cartridge save states.

A state is a zlib-compressed binary property list, which is a format Python can
read without knowing anything about Swift: `PropertyListEncoder` writes `Data`
as bytes and `Codable` names the keys after the properties, so `workRAM` in the
emulator is `workRAM` in the file.

Uncompressed states are accepted too. Cartridge writes them that way when zlib
fails, and its own loader falls back the same way.
"""

from __future__ import annotations

import plistlib
import zlib
from dataclasses import dataclass
from pathlib import Path

from .memory import AddressSpace, build_address_space


class NotASaveState(Exception):
    """The file isn't a state, or is from a version that stores different keys."""


@dataclass(frozen=True)
class Snapshot:
    """One save state, reduced to the parts a cheat search cares about."""

    title: str
    work_ram: bytes
    high_ram: bytes
    cartridge_ram: bytes
    color_mode: bool
    work_ram_bank: int
    path: Path | None = None

    @property
    def label(self) -> str:
        return self.path.name if self.path else self.title

    def address_space(self) -> AddressSpace:
        return build_address_space(
            self.work_ram,
            self.high_ram,
            self.cartridge_ram,
            color_mode=self.color_mode,
        )


def _plist_from(data: bytes) -> dict:
    try:
        raw = zlib.decompress(data)
    except zlib.error:
        raw = data  # Written before compression, or written when zlib failed.

    try:
        plist = plistlib.loads(raw)
    except Exception as error:  # plistlib raises several unrelated types
        raise NotASaveState(f"not a binary property list: {error}") from error

    if not isinstance(plist, dict):
        raise NotASaveState("expected a dictionary at the top level")
    return plist


def load(path: str | Path) -> Snapshot:
    path = Path(path)
    plist = _plist_from(path.read_bytes())

    missing = {"workRAM", "highRAM"} - plist.keys()
    if missing:
        raise NotASaveState(f"missing {', '.join(sorted(missing))}")

    mapper = plist.get("mapper") or {}

    return Snapshot(
        title=plist.get("title", ""),
        work_ram=bytes(plist["workRAM"]),
        high_ram=bytes(plist["highRAM"]),
        cartridge_ram=bytes(mapper.get("ram", b"")),
        color_mode=bool(plist.get("colorMode", False)),
        work_ram_bank=int(plist.get("workRAMBank", 1)),
        path=path,
    )


def load_all(paths: list[str | Path]) -> list[Snapshot]:
    """Load several states, refusing a mismatched set.

    Comparing states from two different games would produce a confident answer
    built on nonsense, so the titles have to agree.
    """
    snapshots = [load(p) for p in paths]
    titles = {s.title for s in snapshots}
    if len(titles) > 1:
        raise NotASaveState(f"states are from different games: {', '.join(sorted(titles))}")
    return snapshots
