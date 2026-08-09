"""How fast the candidate set actually collapses.

The numbers in the README come from here. The point of the simulation is the
churn: a real game rewrites a lot of RAM between two save states minutes apart
— timers, the RNG state, sprite tables, audio counters — and a search that only
looks good against quiet memory doesn't look good against a real cartridge.

Run: python scripts/funnel.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dowser import ScanSession, build_address_space, decreased, equals, unchanged  # noqa: E402

WRAM = 0x8000
HRAM = 0x7F
CHURN = 0.30  # fraction of bytes that differ between two states minutes apart
TRIALS = 200
SLOT = 0x1123  # work RAM bank 1, offset 0x123 -> $D123


def churn(ram: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    changed = ram.copy()
    picks = rng.random(ram.size) < CHURN
    changed[picks] = rng.integers(0, 256, size=int(picks.sum()), dtype=np.uint8)
    return changed


def one_trial(rng: np.random.Generator) -> list[int]:
    before = rng.integers(0, 256, size=WRAM, dtype=np.uint8)
    before[SLOT] = 47

    after = churn(before, rng)
    after[SLOT] = 31  # took a hit

    idle = churn(after, rng)
    idle[SLOT] = 31  # stood still

    hram = bytes(HRAM)
    spaces = [
        build_address_space(ram.tobytes(), hram, color_mode=True) for ram in (before, after, idle)
    ]

    session = ScanSession(width=8)
    counts = [len(spaces[0])]
    counts.append(session.scan(spaces[0], equals(47)))
    counts.append(session.scan(spaces[1], decreased()))
    counts.append(session.scan(spaces[2], unchanged()))
    counts.append(session.scan(spaces[2], equals(31)))

    found = [c.address for c in session.candidates()]
    assert 0xD123 in found, "the planted address must survive every round"
    return counts


def main() -> None:
    rng = np.random.default_rng(20260809)
    trials = np.array([one_trial(rng) for _ in range(TRIALS)])

    labels = [
        "scannable bytes",
        "equals 47",
        "decreased",
        "unchanged",
        "equals 31",
    ]

    print(f"{TRIALS} trials, {int(CHURN * 100)}% of RAM rewritten between states\n")
    print(f"{'round':<18}{'median':>9}{'p90':>9}{'worst':>9}")
    for i, label in enumerate(labels):
        column = trials[:, i]
        print(
            f"{label:<18}{int(np.median(column)):>9,}"
            f"{int(np.percentile(column, 90)):>9,}{int(column.max()):>9,}"
        )

    solved = int((trials[:, -1] == 1).sum())
    print(f"\nunique after four rounds: {solved}/{TRIALS} ({solved / TRIALS:.0%})")


if __name__ == "__main__":
    main()
