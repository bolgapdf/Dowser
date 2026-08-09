"""Successive filtering of candidate addresses.

The loop is the whole idea: take a snapshot, say something true about the value
you're hunting, and throw away every address that disagrees. Each round is
cheap; it's the intersection of four or five rounds that identifies an address
out of tens of thousands.

Two kinds of question can be asked. Absolute ones ("it equals 47") need only the
current snapshot and are how a search starts. Relative ones ("it went down")
compare against the snapshot from the previous round, and are what make the
search usable when you can see a health bar but not a number.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .memory import AddressSpace
from .widths import resolve

# A predicate receives the current values and the previous ones (or None on the
# first pass) and returns a boolean mask over every index.
Predicate = Callable[[np.ndarray, np.ndarray | None], np.ndarray]


class NeedsPrevious(Exception):
    """Raised when a relative filter is used as the first scan.

    "It decreased" has no meaning until there is something to have decreased
    from, and silently matching everything would quietly ruin a search several
    rounds later.
    """


@dataclass(frozen=True)
class Filter:
    """One question, with a name so a session can report what was asked."""

    name: str
    predicate: Predicate
    relative: bool = False

    def __call__(self, current: np.ndarray, previous: np.ndarray | None) -> np.ndarray:
        if self.relative and previous is None:
            raise NeedsPrevious(f"{self.name} needs an earlier snapshot to compare against")
        return self.predicate(current, previous)


def equals(value: int) -> Filter:
    return Filter(f"equals {value}", lambda cur, _prev: cur == value)


def not_equals(value: int) -> Filter:
    return Filter(f"is not {value}", lambda cur, _prev: cur != value)


def less_than(value: int) -> Filter:
    return Filter(f"less than {value}", lambda cur, _prev: cur < value)


def greater_than(value: int) -> Filter:
    return Filter(f"greater than {value}", lambda cur, _prev: cur > value)


def between(low: int, high: int) -> Filter:
    return Filter(f"between {low} and {high}", lambda cur, _prev: (cur >= low) & (cur <= high))


def decreased() -> Filter:
    return Filter("decreased", lambda cur, prev: cur < prev, relative=True)


def increased() -> Filter:
    return Filter("increased", lambda cur, prev: cur > prev, relative=True)


def changed() -> Filter:
    return Filter("changed", lambda cur, prev: cur != prev, relative=True)


def unchanged() -> Filter:
    return Filter("unchanged", lambda cur, prev: cur == prev, relative=True)


def decreased_by(delta: int) -> Filter:
    """Exact damage. Far sharper than "decreased" when you know the number.

    Signed arithmetic on purpose: at 8 bits, `prev - delta` for a value near
    zero would wrap to something enormous and match nothing.
    """
    return Filter(
        f"decreased by {delta}",
        lambda cur, prev: cur.astype(np.int32) == prev.astype(np.int32) - delta,
        relative=True,
    )


def increased_by(delta: int) -> Filter:
    return Filter(
        f"increased by {delta}",
        lambda cur, prev: cur.astype(np.int32) == prev.astype(np.int32) + delta,
        relative=True,
    )


@dataclass(frozen=True)
class Round:
    """What one filter did, kept so a session can explain itself."""

    filter_name: str
    remaining: int


@dataclass(frozen=True)
class Candidate:
    """A surviving address, in terms a person can act on."""

    region: str
    bank: int
    address: int
    value: int
    width: str

    def __str__(self) -> str:
        where = self.region if self.region == "hram" else f"{self.region}:{self.bank}"
        return f"{where} ${self.address:04X} = {self.value}"


class ScanSession:
    """A narrowing search over one game's memory.

    Holds the candidate set and the snapshot each round was measured against,
    so relative filters compare like with like.
    """

    def __init__(self, width: str | int = "u8") -> None:
        # `resolve` raises on anything unknown, and accepts the old 8/16 form.
        self.width = resolve(width).key
        self.history: list[Round] = []
        self._indices: np.ndarray | None = None
        self._previous: np.ndarray | None = None
        self._space: AddressSpace | None = None

    @property
    def started(self) -> bool:
        return self._indices is not None

    @property
    def remaining(self) -> int:
        """Candidates still standing. Before the first scan, nothing is."""
        return 0 if self._indices is None else int(self._indices.size)

    def scan(self, space: AddressSpace, filter_: Filter) -> int:
        """Apply one filter and return how many candidates survive."""
        values = space.read(self.width)

        if self._indices is None:
            mask = filter_(values, None) & space.valid(self.width)
            self._indices = np.flatnonzero(mask)
        else:
            if self._space is not None and not self._space.compatible_with(space):
                raise ValueError(
                    "snapshot layout changed mid-search; "
                    "these states are from different cartridges or console modes"
                )
            current = values[self._indices]
            previous = None if self._previous is None else self._previous[self._indices]
            self._indices = self._indices[filter_(current, previous)]

        self._previous = values
        self._space = space
        self.history.append(Round(filter_.name, int(self._indices.size)))
        return int(self._indices.size)

    def candidates(self, limit: int | None = None) -> list[Candidate]:
        if self._indices is None or self._space is None:
            return []

        space = self._space
        values = space.read(self.width)
        chosen = self._indices if limit is None else self._indices[:limit]

        return [
            Candidate(
                region=space.regions[int(space.region_ids[i])].name,
                bank=int(space.banks[i]),
                address=int(space.addresses[i]),
                value=int(values[i]),
                width=self.width,
            )
            for i in chosen
        ]

    def reset(self) -> None:
        self.history.clear()
        self._indices = None
        self._previous = None
        self._space = None
