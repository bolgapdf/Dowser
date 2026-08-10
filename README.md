# Dowser

A memory-search tool for Game Boy and Game Boy Color games, paired with
[Cartridge](https://github.com/bolgapdf/Cartridge), an emulator also
built from scratch. It finds the address behind a number in a running
game, such as health or money, and can hold it there while the game
keeps playing.

## What it does

- A guided web interface: pick a cheat from a menu, answer two or three
  plain-language questions, and it narrows the address down on its own.
  No memory addresses or hex values shown unless asked for.
- Eleven built-in guided searches for Pokémon Gold, Silver, and Crystal:
  choose which Pokémon appears, set money or item counts, change a
  Pokémon's stats or experience, force a shiny encounter.
- Remembers what it finds per cartridge, so a cheat can be reapplied
  later with one click instead of searching again.
- A terminal REPL and a Python library, for searching directly or against
  save-state files instead of a running game.

## How it works

A search asks one true thing about a value at a time (is it 47, did it
go down, did it stay the same) and discards every address in memory
that disagrees. Two or three rounds is usually enough to go from tens of
thousands of candidates to one. Different games store numbers
differently: some values are byte-swapped, and Pokémon's money is
stored as binary-coded decimal rather than as a plain integer. The
search engine reads memory according to a declared format rather than
assuming one, and the guided recipes pick the right format automatically.

Freezing a value sends it to Cartridge over a local network connection
and holds it there live, rather than producing a code to enter by hand.

## Proof it works

117 automated tests cover the search engine, the number formats, and the
live connection to Cartridge.

## Built with

Python, FastAPI, NumPy, and a dependency-free HTML/JavaScript front end.

## Running it

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,web]"
./dowse web
```

Opens a browser at `127.0.0.1:8585`. Requires Cartridge running with
**Settings › Advanced › Cheat Search** turned on; the connection never
leaves `127.0.0.1`.

A full worked example, finding and catching a specific Pokémon that
isn't normally available, is in [docs/mew.md](docs/mew.md).
</content>
