# Dowser

**A point-and-click tool that finds a hidden number inside a running Game
Boy game — your health, your money, whatever you're after — and lets you
freeze it. No reverse-engineering knowledge required.**

Pairs with **[Cartridge](https://github.com/bolgapdf/Cartridge)**, a Game
Boy emulator I also built from scratch. Cartridge plays the game; Dowser
looks inside its memory while it runs.

## What it actually does

A game's memory is tens of thousands of individual numbers, and only one of
them is, say, your health. This is the classic "Cheat Engine" technique for
finding it: tell the tool what the number is right now, do something that
changes it, tell it what it is now — and each answer throws out every
number in memory that doesn't fit. Two or three rounds is usually enough to
go from thirty thousand possibilities down to exactly one.

The part I actually built is a guided version of this that doesn't require
knowing that technique exists. Open the browser interface, pick "Set your
money" from a menu, and it just asks:

> *How much money do you have? → Buy or sell something → How much now?*

— in plain English, no hex addresses or memory jargon anywhere. Under the
hood it's running the same narrowing search, handling details the user
never has to think about (some numbers in these games are stored
backwards, and some aren't stored as normal numbers at all — more on that
below).

## What's built in

Eleven guided searches for Pokémon Gold, Silver, and Crystal, each just a
short plain-English conversation:

- Choose which Pokémon appears in the tall grass
- Set your money, or any item's quantity
- Turn a bag item into a completely different item
- Stop a move from running out of PP
- Change a Pokémon's stats, level, or experience
- Force a wild Pokémon to be shiny

Once found, an address is remembered — reopen the tool later and you can
reapply the same cheat with one click, no searching again.

## The interesting part

The genuinely tricky bit isn't the search itself — it's that these old
games don't store numbers the same way as each other. Some values are
stored back-to-front. Money isn't stored as an ordinary number at all —
it's stored the way a human reads it, digit by digit, which is a
completely different bit pattern than the number itself. Searching for
"9999" the normal way finds nothing, because on the byte level, "9999"
isn't stored as 9999. Get the format wrong and the search doesn't error —
it just silently finds nothing, which looks exactly like the number not
being there. Handling that automatically, so a first-time user typing in
"my money" just works, is most of what makes the guided version different
from a raw search tool.

There's also a live connection to Cartridge over the network: freezing a
value doesn't just print a code to copy in by hand, it reaches into the
running game immediately and holds it there while you keep playing.

## Proof it works

**117 automated tests**, covering the search engine, the different number
formats, and the live connection to Cartridge.

## Built with

Python, FastAPI, NumPy for the search itself, and a small dependency-free
web front end (plain HTML and JavaScript — no framework, on purpose, for a
tool this size).

## Getting it running

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,web]"
./dowse web
```

Opens a browser window at `127.0.0.1:8585`. Requires Cartridge to be
running with **Settings › Advanced › Cheat Search** turned on. Everything
stays on your own machine — the connection to Cartridge never leaves
`127.0.0.1`.

There's also a full worked walkthrough — finding a specific, normally
unobtainable Pokémon and catching it — in [docs/mew.md](docs/mew.md).
</content>
