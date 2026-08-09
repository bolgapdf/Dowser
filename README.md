# Dowser

Find the Game Boy memory address behind a number, and write the code that pins it.

Point it at save states from [Cartridge](https://github.com/bolgapdf/Cartridge) and it narrows
every byte of work RAM, high RAM, and cartridge RAM down to the one address holding your health,
your money, or your step counter — then emits the eight-digit code that freezes it.

```
$ dowser new --width 8
$ dowser scan 1.state equals 47          # 47 HP right now
128 candidates
$ dowser scan 2.state decreased          # took a hit
8 candidates
$ dowser scan 3.state unchanged          # stood still
6 candidates
$ dowser scan 3.state equals 31          # it reads 31
1 candidate
  wram:1 $D123 = 31

$ dowser code D123 255
01FF23D1
```

## How it narrows

Each round asks one true thing about the value and discards every address that disagrees. The
intersection is what identifies it — no single question is remotely selective enough on its own.

Measured over 200 simulated searches, with 30% of RAM rewritten between states (`scripts/funnel.py`):

| round | median | p90 | worst |
|---|---:|---:|---:|
| scannable bytes | 32,895 | 32,895 | 32,895 |
| `equals 47` | 128 | 143 | 158 |
| `decreased` | 8 | 11 | 15 |
| `unchanged` | 6 | 8 | 15 |
| `equals 31` | 1 | 1 | 2 |

Unique after four rounds in 90% of trials. A scan is a vectorised pass over the whole address
space, so a round costs about 0.01 ms — the bottleneck is how fast you can play, not the search.

## What it searches

Only memory a game writes during play. ROM never changes, and a value found in video RAM is a
picture of a number rather than the number itself.

| region | addresses | notes |
|---|---|---|
| Work RAM bank 0 | `$C000–$CFFF` | |
| Work RAM banks 1–7 | `$D000–$DFFF` | banks 2+ are Color only |
| Cartridge RAM | `$A000–$BFFF` | banked, present when the cartridge has it |
| High RAM | `$FF80–$FFFE` | |

Two details that matter more than they look:

**Banks are part of an address's identity.** Work RAM banks 1 and 5 both answer to `$D000`, so a
result that says `$D040` without saying which bank hasn't told you anything. On a mono game only
banks 0 and 1 exist, and scanning the other six would add 24 KB of stale candidates that can never
change — noise that makes the first filter look far worse than it is.

**16-bit values don't straddle regions.** Anything over 255 lives in two adjacent bytes, little-endian.
But the last byte of bank 3 and the first byte of bank 4 are adjacent in the *file*, not in the
console's address space, and reading them as a pair invents a number no game ever wrote.

## Filters

Absolute filters need only the current state and are how a search starts:

`equals` · `not-equals` · `less-than` · `greater-than` · `between`

Relative filters compare against the previous round, which is what makes the search work when you
can see a health bar but not a number:

`decreased` · `increased` · `changed` · `unchanged` · `decreased-by` · `increased-by`

`decreased-by` is much sharper than `decreased` when you know the damage number. It's done in
signed arithmetic on purpose: at 8 bits, `prev - delta` below zero would wrap to something huge and
match nothing.

## Codes

The classic format is eight hex digits, `ttvvaaaa`:

| | |
|---|---|
| `tt` | type. `01` writes the value once per frame |
| `vv` | the value |
| `aaaa` | the address, byte-swapped |

So writing `$FF` to `$DA19` is `01FF19DA`. That's why published codes look like their address is
back to front — it is, because the SM83 is little-endian and the format stores the address exactly
as the console would.

A 16-bit value needs two codes, one per byte, because the hardware writes single bytes.

The format predates the Color's eight work RAM banks and devices disagreed about how to name one,
so codes for banks 2 and above are marked ambiguous rather than guessed at. A code that silently
targets the wrong bank is worse than one that admits it can't say.

## Install

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Requires Python 3.11+ and NumPy.

## Reading save states

Cartridge writes a zlib-compressed binary property list. Python reads it without knowing anything
about Swift: `PropertyListEncoder` stores `Data` as bytes and `Codable` names the keys after the
properties, so `workRAM` in the emulator is `workRAM` in the file. Uncompressed states load too,
since Cartridge falls back to writing those when zlib fails.

## Library

```python
from dowser import ScanSession, load, equals, decreased, encode

session = ScanSession(width=8)
session.scan(load("1.state").address_space(), equals(47))
session.scan(load("2.state").address_space(), decreased())

for candidate in session.candidates():
    print(candidate, encode(candidate.address, 255)[0])
```

## Legal

Dowser reads save states you made from cartridges you own. It ships no ROMs and no game data.
Cheat codes are memory addresses and values — facts about a program, not copies of one.

Not affiliated with, endorsed by, or derived from any commercial cheat device.

MIT.
