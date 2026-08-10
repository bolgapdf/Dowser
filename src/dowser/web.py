"""A browser front end for the search.

The terminal prompt is fine once you know it, and hostile before that: you have
to remember that `<` means decreased and that freezing takes an address you
have to read off a previous line. A page can just show the candidates with a
button next to each one.

It also fits how this is actually used — the emulator has the screen, and the
search wants to live in a window beside it rather than in front of it.

Everything runs locally. The browser talks to this server, and this server talks
to Cartridge over the same loopback socket the CLI uses.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import gen2, recipes, saved, scan
from .live import Live, NotConnected
from .widths import WIDTHS, resolve

STATIC = Path(__file__).parent / "static"

# The filters a button can ask for, and how many numbers each needs. Keeping
# this as data means the page can render its own buttons from /api/filters
# rather than hard-coding a list that drifts.
FILTERS: dict[str, tuple] = {
    "equals": (scan.equals, 1),
    "not-equals": (scan.not_equals, 1),
    "less-than": (scan.less_than, 1),
    "greater-than": (scan.greater_than, 1),
    "decreased": (scan.decreased, 0),
    "increased": (scan.increased, 0),
    "changed": (scan.changed, 0),
    "unchanged": (scan.unchanged, 0),
    "decreased-by": (scan.decreased_by, 1),
    "increased-by": (scan.increased_by, 1),
}

# Filters that compare against the previous round, and so can't start a search.
RELATIVE = {
    "decreased",
    "increased",
    "changed",
    "unchanged",
    "decreased-by",
    "increased-by",
}


class Search:
    """The one search this server is running.

    Single-session on purpose. It's a tool for the person sitting at the
    machine, and a second concurrent search would be two people fighting over
    one emulator.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8484) -> None:
        self.host = host
        self.port = port
        self.session = scan.ScanSession(width="u8")
        self.frozen: list[dict] = []
        #: The guided search in progress, if any.
        self.recipe: recipes.Recipe | None = None
        self.step = 0
        #: The bytes the last step measured, to notice a frozen emulator.
        self.last_bytes = None
        self.stale = False
        #: Addresses found in earlier sessions, per game.
        self.library = saved.Library()
        #: What is currently held, per recipe, so one can be released alone.
        self.active: dict[str, dict] = {}
        self.game = ""

    def connection(self) -> Live:
        """A fresh connection per request.

        Cheap over loopback, and it means a browser left open overnight doesn't
        hold a socket against an emulator that has since quit.
        """
        try:
            return Live(self.host, self.port, timeout=5.0).connect()
        except NotConnected as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    def reset(self, width: str) -> None:
        self.session = scan.ScanSession(width=width)
        self.recipe = None
        self.step = 0
        self.last_bytes = None
        self.stale = False


search = Search()
app = FastAPI(title="Dowser", docs_url=None, redoc_url=None)


class NewSearch(BaseModel):
    width: str = Field("u8", description="a key from /api/widths")


class ScanRequest(BaseModel):
    filter: str
    value: int | None = None
    second: int | None = None


class RecipeStep(BaseModel):
    #: Absent for steps that need no answer ("press this after you spend some").
    value: int | None = None


class FreezeRequest(BaseModel):
    value: int
    #: Absent freezes every surviving candidate.
    address: int | None = None


def _candidates(limit: int = 200) -> list[dict]:
    return [
        {
            "region": c.region,
            "bank": c.bank,
            "address": c.address,
            "hex": f"{c.address:04X}",
            "value": c.value,
            "label": f"{c.region}:{c.bank}" if c.region != "hram" else "hram",
        }
        for c in search.session.candidates(limit=limit)
    ]


def _recipe_state() -> dict | None:
    if search.recipe is None:
        return None

    recipe = search.recipe
    done = search.step >= len(recipe.steps)
    return {
        "id": recipe.id,
        "name": recipe.name,
        "blurb": recipe.blurb,
        "applies": recipe.applies,
        "applyHint": recipe.apply_hint,
        "caution": recipe.caution,
        "width": recipe.width,
        "maximum": resolve(recipe.width).maximum,
        "selfErasing": recipe.self_erasing,
        "remembered": _remembered(recipe.id),
        "held": search.active.get(recipe.id),
        "stepNumber": search.step + 1,
        "stepCount": len(recipe.steps),
        "done": done,
        "step": None
        if done
        else {
            "prompt": recipe.steps[search.step].prompt,
            "answer": recipe.steps[search.step].answer,
            "hint": recipe.steps[search.step].hint,
        },
    }


def _state(extra: dict | None = None) -> dict:
    payload = {
        "recipe": _recipe_state(),
        "stale": search.stale,
        "width": search.session.width,
        "started": search.session.started,
        "remaining": search.session.remaining,
        "history": [
            {"filter": r.filter_name, "remaining": r.remaining} for r in search.session.history
        ],
        "candidates": _candidates() if 0 < search.session.remaining <= 200 else [],
        "frozen": search.frozen,
        "game": search.game,
        "active": search.active,
        "knownIds": sorted(search.library.for_game(search.game)),
    }
    payload.update(extra or {})
    return payload


@app.get("/api/status")
def status() -> dict:
    """Whether the emulator is there, and what it's running."""
    try:
        with Live(search.host, search.port, timeout=2.0) as live:
            title = live.title()
            running = live.running()
        if title and title != search.game:
            # A different cartridge means a different set of addresses.
            search.game = title
        return _state({"connected": True, "title": title, "running": running})
    except (NotConnected, HTTPException):
        return _state({"connected": False, "title": None, "running": None})


@app.get("/api/recipes")
def list_recipes() -> dict:
    return {
        "recipes": [
            {
                "id": r.id,
                "name": r.name,
                "blurb": r.blurb,
                "tags": r.tags,
                "steps": len(r.steps),
                "caution": r.caution,
            }
            for r in recipes.RECIPES
        ]
    }


@app.post("/api/recipes/{recipe_id}/start")
def start_recipe(recipe_id: str) -> dict:
    recipe = recipes.BY_ID.get(recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail=f"no recipe {recipe_id!r}")

    search.reset(recipe.width)
    search.recipe = recipe
    # Already found on this cartridge? Then there is nothing to search for, and
    # for the one-shot cheats there would be no way to search again anyway.
    search.step = len(recipe.steps) if search.library.get(search.game, recipe.id) else 0
    return _state()


@app.post("/api/recipes/step")
def run_step(body: RecipeStep) -> dict:
    if search.recipe is None:
        raise HTTPException(status_code=400, detail="no guided search in progress")
    if search.step >= len(search.recipe.steps):
        raise HTTPException(status_code=400, detail="this search is already finished")

    step = search.recipe.steps[search.step]
    factory, arity = recipes.ASK[step.filter]
    if arity and body.value is None:
        raise HTTPException(status_code=400, detail="that step needs a number")

    live = search.connection()
    try:
        space = live.address_space()
    finally:
        live.close()

    # A byte-for-byte identical snapshot means the console did not advance a
    # single frame between two steps, which no running game does. Every filter
    # still "works" against it and every answer it gives is meaningless, so say
    # so rather than let the search quietly collapse to nothing.
    import numpy as np

    search.stale = search.last_bytes is not None and np.array_equal(space.values, search.last_bytes)
    search.last_bytes = space.values.copy()

    try:
        search.session.scan(space, factory(body.value) if arity else factory())
    except scan.NeedsPrevious as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    search.step += 1
    return _state()


@app.post("/api/recipes/exit")
def exit_recipe() -> dict:
    """Leave the guided search and go back to the menu.

    The page polls /api/status every few seconds and takes it as authoritative,
    so clearing the recipe in the browser alone lasts until the next poll puts
    it straight back. The session is left alone: starting any recipe resets it
    anyway, and leaving it here means going back to look at the menu doesn't
    throw away a search in progress.
    """
    search.recipe = None
    search.step = 0
    return _state()


@app.post("/api/recipes/skip")
def skip_rest() -> dict:
    """Stop early. Two rounds is often enough, and the third is a formality."""
    if search.recipe is None:
        raise HTTPException(status_code=400, detail="no guided search in progress")
    if not search.session.started:
        raise HTTPException(status_code=400, detail="do at least one step first")
    search.step = len(search.recipe.steps)
    return _state()


@app.get("/api/names")
def names(kind: str, q: str = "", limit: int = 40) -> dict:
    """The picker's list: type `pid`, get Pidgey.

    Ranked so that a prefix match beats a match in the middle, because typing
    `mew` should not offer Mewtwo first.
    """
    table = gen2.SPECIES if kind == "species" else gen2.ITEMS if kind == "item" else None
    if table is None:
        raise HTTPException(status_code=400, detail="kind must be species or item")

    notable = gen2.NOTABLE_SPECIES if kind == "species" else gen2.NOTABLE_ITEMS
    query = q.strip().lower()

    if not query:
        chosen = [(n, table[n]) for n in notable if n in table]
        chosen += [(n, name) for n, name in table.items() if n not in notable]
    else:
        matches = [(n, name) for n, name in table.items() if query in name.lower()]
        # Exact, then prefix, then shortest. Without the length term, typing
        # "mew" offers Mewtwo first, because it also starts with "mew" and has
        # the lower number.
        matches.sort(
            key=lambda pair: (
                pair[1].lower() != query,
                not pair[1].lower().startswith(query),
                len(pair[1]),
                pair[0],
            )
        )
        chosen = matches
        if query.isdigit() and int(query) in table:
            chosen.insert(0, (int(query), table[int(query)]))

    return {
        "names": [{"number": n, "name": name} for n, name in chosen[:limit]],
        "total": len(table),
    }


@app.get("/api/widths")
def widths() -> dict:
    """How a number can be read. The page builds its own picker from this."""
    return {
        "widths": [
            {
                "key": w.key,
                "label": w.label,
                "bytes": w.size,
                "maximum": w.maximum,
                "description": w.description,
            }
            for w in WIDTHS.values()
        ]
    }


@app.get("/api/filters")
def filters() -> dict:
    return {
        "filters": [
            {"name": name, "arity": arity, "relative": name in RELATIVE}
            for name, (_factory, arity) in FILTERS.items()
        ]
    }


@app.post("/api/session")
def new_session(body: NewSearch) -> dict:
    try:
        resolve(body.width)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    search.reset(body.width)
    return _state()


@app.post("/api/scan")
def run_scan(body: ScanRequest) -> dict:
    if body.filter not in FILTERS:
        raise HTTPException(status_code=400, detail=f"unknown filter {body.filter!r}")

    factory, arity = FILTERS[body.filter]
    supplied = [v for v in (body.value, body.second) if v is not None]
    if len(supplied) != arity:
        raise HTTPException(
            status_code=400, detail=f"{body.filter} needs {arity} value(s), got {len(supplied)}"
        )

    live = search.connection()
    try:
        # Snapshot taken now, at the moment the claim is made — the same reason
        # the live prompt beats save files.
        space = live.address_space()
    except NotConnected as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    finally:
        live.close()

    try:
        search.session.scan(space, factory(*supplied))
    except scan.NeedsPrevious as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    return _state()


def _push_cheats() -> None:
    """Send the whole active set, replacing whatever Cartridge was holding.

    The emulator holds a flat list with no idea which cheat owns what, so the
    authority lives here and the full set is rewritten on every change. That is
    what makes "release just this one" possible without a per-address protocol.
    """
    live = search.connection()
    try:
        live.clear()
        for entry in search.active.values():
            for spot in entry["addresses"]:
                live.freeze(spot["address"], entry["value"], bank=spot["bank"])
    finally:
        live.close()


def _remembered(recipe_id: str) -> list[dict]:
    return [
        {"address": f.address, "hex": f.hex, "bank": f.bank, "value": f.value}
        for f in search.library.get(search.game, recipe_id)
    ]


@app.post("/api/recipes/{recipe_id}/apply")
def apply_recipe(recipe_id: str, body: FreezeRequest) -> dict:
    """Hold a recipe's remembered addresses at a value.

    This is the path that makes a found address worth keeping: no search, no
    steps, just pick a different Pokémon and press the button.
    """
    recipe = recipes.BY_ID.get(recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail=f"no recipe {recipe_id!r}")

    spots = _remembered(recipe_id)
    if body.address is not None:
        spots = [s for s in spots if s["address"] == body.address]
    if not spots:
        raise HTTPException(status_code=400, detail="nothing remembered for this one yet")

    maximum = resolve(recipe.width).maximum
    if not 0 <= body.value <= maximum:
        raise HTTPException(status_code=400, detail=f"value must be between 0 and {maximum}")

    search.active[recipe_id] = {"value": body.value, "addresses": spots}
    _push_cheats()
    return _state()


@app.post("/api/recipes/{recipe_id}/release")
def release_recipe(recipe_id: str) -> dict:
    """Stop holding this one, leaving any others alone."""
    search.active.pop(recipe_id, None)
    _push_cheats()
    return _state()


@app.post("/api/recipes/{recipe_id}/forget")
def forget_recipe(recipe_id: str) -> dict:
    """Throw away the remembered address so the search can be run again."""
    search.active.pop(recipe_id, None)
    search.library.forget(search.game, recipe_id)
    _push_cheats()
    if search.recipe and search.recipe.id == recipe_id:
        search.reset(search.recipe.width)
        search.recipe = recipes.BY_ID[recipe_id]
        search.step = 0
    return _state()


@app.post("/api/freeze")
def freeze(body: FreezeRequest) -> dict:
    found = search.session.candidates(limit=64)
    if body.address is not None:
        found = [c for c in found if c.address == body.address]
    if not found:
        raise HTTPException(status_code=400, detail="nothing to freeze")
    if len(found) > 8:
        raise HTTPException(status_code=400, detail="narrow to 8 or fewer first")

    search.frozen = [
        {"address": c.address, "hex": f"{c.address:04X}", "bank": c.bank, "value": body.value}
        for c in found
    ]

    # Remember it. Some searches destroy their own preconditions — hold the
    # encounter species at Mew and every encounter is Mew, so there is no
    # variation left to narrow with, ever again on this save.
    if search.recipe is not None:
        search.library.remember(
            search.game,
            search.recipe.id,
            [
                saved.Found(
                    address=c.address, bank=c.bank, width=search.session.width, value=c.value
                )
                for c in found
            ],
        )
        search.active[search.recipe.id] = {"value": body.value, "addresses": search.frozen}
    return _state()


@app.post("/api/thaw")
def thaw() -> dict:
    live = search.connection()
    try:
        live.clear()
    finally:
        live.close()
    search.frozen = []
    return _state()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


def serve(host: str = "127.0.0.1", port: int = 8585, emulator_port: int = 8484) -> None:
    import uvicorn

    search.port = emulator_port
    uvicorn.run(app, host=host, port=port, log_level="warning")
