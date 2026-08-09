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

from . import scan
from .live import Live, NotConnected

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
        self.session = scan.ScanSession(width=8)
        self.frozen: list[dict] = []

    def connection(self) -> Live:
        """A fresh connection per request.

        Cheap over loopback, and it means a browser left open overnight doesn't
        hold a socket against an emulator that has since quit.
        """
        try:
            return Live(self.host, self.port, timeout=5.0).connect()
        except NotConnected as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    def reset(self, width: int) -> None:
        self.session = scan.ScanSession(width=width)


search = Search()
app = FastAPI(title="Dowser", docs_url=None, redoc_url=None)


class NewSearch(BaseModel):
    width: int = Field(8, description="8 or 16")


class ScanRequest(BaseModel):
    filter: str
    value: int | None = None
    second: int | None = None


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


def _state(extra: dict | None = None) -> dict:
    payload = {
        "width": search.session.width,
        "started": search.session.started,
        "remaining": search.session.remaining,
        "history": [
            {"filter": r.filter_name, "remaining": r.remaining} for r in search.session.history
        ],
        "candidates": _candidates() if 0 < search.session.remaining <= 200 else [],
        "frozen": search.frozen,
    }
    payload.update(extra or {})
    return payload


@app.get("/api/status")
def status() -> dict:
    """Whether the emulator is there, and what it's running."""
    try:
        with Live(search.host, search.port, timeout=2.0) as live:
            title = live.title()
        return _state({"connected": True, "title": title})
    except (NotConnected, HTTPException):
        return _state({"connected": False, "title": None})


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
    if body.width not in (8, 16):
        raise HTTPException(status_code=400, detail="width must be 8 or 16")
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


@app.post("/api/freeze")
def freeze(body: FreezeRequest) -> dict:
    found = search.session.candidates(limit=64)
    if body.address is not None:
        found = [c for c in found if c.address == body.address]
    if not found:
        raise HTTPException(status_code=400, detail="nothing to freeze")
    if len(found) > 8:
        raise HTTPException(status_code=400, detail="narrow to 8 or fewer first")

    live = search.connection()
    try:
        for candidate in found:
            live.freeze(candidate.address, body.value, bank=candidate.bank)
    except NotConnected as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    finally:
        live.close()

    search.frozen = [
        {"address": c.address, "hex": f"{c.address:04X}", "bank": c.bank, "value": body.value}
        for c in found
    ]
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
