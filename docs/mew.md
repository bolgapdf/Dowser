# Catching Mew in Pokémon Silver

A worked example. By the end you'll have found the address that decides what
wild Pokémon you're about to meet, and you'll have caught a Mew with it.

There is no magic number in this guide, on purpose. Published addresses are
specific to one game and one revision, and finding it yourself takes about two
minutes — which is the whole reason this tool exists.

## Why Mew is 151

Generation 2 numbers its species in Pokédex order. Mew is #151 in the Pokédex,
so Mew is species `151` in memory. (Generation 1 used a separate internal
ordering where Mew was 21, which is why Red and Blue guides quote a different
number.)

Silver never offers Mew, but the ROM still carries every species' stats, sprite,
and cry — all 251 of them. Nothing has to be invented; the game just has to be
told to use one it wouldn't normally pick.

## Before you start

1. **Save your game in-game**, then **make a save state** in Cartridge.
   Everything below is reversible if you keep a state to fall back to.
2. Turn on **Settings › Advanced › Cheat Search**.
3. Stand in tall grass somewhere with common encounters. Route 30 or 31 is fine.

## Finding the address

Open a terminal:

```sh
dowser live
```

```
connected to POKEMON SILVER at 127.0.0.1:8484
8-bit search. `?` for help, `quit` to stop.
```

Now walk into the grass until something appears.

**Round 1.** Say a Rattata shows up. Rattata is #19, so type `19`:

```
[-] 19
  equals 19: 214 candidates
```

Run from the battle and walk until something *different* appears.

**Round 2.** Say it's a Sentret, #161:

```
[214] 161
  equals 161: 3 candidates
```

Two rounds is often enough, because asking for two specific values in a row is
extremely selective. If more than a handful survive, run and repeat with a third
species.

```
[3] list
  wram:1 $D0EF = 161
  wram:1 $D204 = 161
  wram:0 $C6E9 = 161
```

Several addresses hold the species at once: the one the encounter generator
wrote, the one the battle system copied it into, and usually one the screen is
drawing from. You want the first, and the way to find out which it is, is to try.

## Checking you have the right one

Don't jump straight to Mew. Freeze the first candidate to something ordinary and
verifiable:

```
[3] quit
$ dowser code D0EF 16 --bank 1
01100EFD
```

That pins the address to 16 — Pidgey. Enter that code in Cartridge, walk into the
grass, and see what appears.

- **A Pidgey every time** — that's the address. Move on.
- **The right name but the wrong sprite**, or nothing changes — that's a copy
  further down the chain. Try the next candidate.

This step costs a minute and tells you which of the three actually drives the
encounter, rather than which one merely reflects it.

## The Mew

Once you know which address works, change the value to 151:

```sh
dowser code D0EF 151 --bank 1
```

Walk into the grass. Turn the code off *before* you throw a Ball if you'd rather
the rest of your encounters stayed normal — the species is already locked in by
the time the battle starts.

Catch it as you would anything else. It'll be whatever level that route's
encounter table generates, with the moves Mew learns by then, and its stats are
rolled normally. Inside the game it is an entirely ordinary Mew.

## Things worth knowing

**It won't pass as legitimate.** Anything obtained this way carries no encounter
history a later generation would accept, so it can't be transferred forward and
it will be obvious to anyone who checks. Fine for your own cartridge; don't trade
it to strangers as the real thing.

**Turn the code off afterwards.** A frozen species byte means *every* encounter
is Mew, which stops being fun quickly and makes the rest of the route unusable.

**Don't leave a code running through a save.** Write to memory the game didn't
expect to change and you can corrupt a save file. Switch codes off before saving,
and keep the save state you made at the start.

**If the search never narrows**, check you're reading the Pokédex number and not
the level or the HP. Species numbers over 255 don't exist in Gen 2, so an 8-bit
search is always the right width here.

## The same trick, elsewhere

Nothing above is specific to Pokémon. The loop is: know a number, say what it is,
change it, say what changed. Money, HP, item quantities, and step counters all
fall out the same way — though money in Gen 2 is three bytes of binary-coded
decimal, so `9999` is stored as `0x99 0x99`, and searching for the decimal value
will find nothing. Search for what's on screen one byte at a time instead.
