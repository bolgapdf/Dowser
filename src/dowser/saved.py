"""Addresses that have already been found, remembered per game.

Finding an address is a one-time cost, and some searches destroy the conditions
that made them possible. Freeze the wild encounter to Mew and every encounter is
Mew — there is no longer any variation to narrow with, so the same search can
never be run again on that save. Before this file existed, that meant one
Pokémon per playthrough.

Keyed by the cartridge header title, so two games can't inherit each other's
addresses, and stored under the user's home directory rather than the project
so it survives a reinstall.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_PATH = Path.home() / ".dowser" / "found.json"


@dataclass(frozen=True)
class Found:
    """One address a search has already pinned down."""

    address: int
    bank: int
    width: str
    #: What the value read at the moment it was found, purely for display.
    value: int = 0

    @property
    def hex(self) -> str:
        return f"{self.address:04X}"


class Library:
    """What has been found, for every game.

    Writes are atomic. A half-written file here would mean losing the one thing
    that can't be re-derived, and it's a few hundred bytes, so there is no
    reason to be clever about it.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else DEFAULT_PATH
        self._games: dict[str, dict[str, list[dict]]] = {}
        self.load()

    def load(self) -> None:
        try:
            self._games = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            # Missing is normal; corrupt is survivable — the worst case is
            # searching again, which is what you'd be doing anyway.
            self._games = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(handle, "w") as file:
                json.dump(self._games, file, indent=2, sort_keys=True)
            os.replace(temporary, self.path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    # MARK: reading

    def get(self, game: str, recipe: str) -> list[Found]:
        entries = self._games.get(game, {}).get(recipe, [])
        return [Found(**entry) for entry in entries]

    def games(self) -> list[str]:
        return sorted(self._games)

    def for_game(self, game: str) -> dict[str, list[Found]]:
        return {
            recipe: [Found(**entry) for entry in entries]
            for recipe, entries in self._games.get(game, {}).items()
        }

    # MARK: writing

    def remember(self, game: str, recipe: str, found: list[Found]) -> None:
        if not game:
            return  # No cartridge title means nothing to key on.
        self._games.setdefault(game, {})[recipe] = [asdict(f) for f in found]
        self.save()

    def forget(self, game: str, recipe: str) -> None:
        """Drop one recipe's addresses, so it can be searched for again."""
        if self._games.get(game, {}).pop(recipe, None) is not None:
            if not self._games[game]:
                del self._games[game]
            self.save()

    def forget_game(self, game: str) -> None:
        if self._games.pop(game, None) is not None:
            self.save()
