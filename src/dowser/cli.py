"""Command line for a search that happens over several sittings.

A real hunt is: play until something changes, save a state, run one filter, go
back to the game. That's minutes apart, so the session lives in a file rather
than in memory, and each command picks up where the last one left off.

    dowser new --width 8
    dowser scan before.state equals 47
    dowser scan after.state decreased
    dowser scan after2.state equals 31
    dowser code C123 255
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from . import codes, scan
from .snapshot import NotASaveState, load
from .widths import WIDTHS

DEFAULT_SESSION = Path(".dowser-session.npz")

# Each filter's name, its constructor, and how many numbers it takes.
FILTERS: dict[str, tuple] = {
    "equals": (scan.equals, 1),
    "not-equals": (scan.not_equals, 1),
    "less-than": (scan.less_than, 1),
    "greater-than": (scan.greater_than, 1),
    "between": (scan.between, 2),
    "decreased": (scan.decreased, 0),
    "increased": (scan.increased, 0),
    "changed": (scan.changed, 0),
    "unchanged": (scan.unchanged, 0),
    "decreased-by": (scan.decreased_by, 1),
    "increased-by": (scan.increased_by, 1),
}


def _save(path: Path, session: scan.ScanSession, last_state: Path) -> None:
    np.savez(
        path,
        width=str(session.width),
        indices=session._indices if session._indices is not None else np.array([], dtype=np.int64),
        started=session.started,
        history=np.array([f"{r.filter_name}\t{r.remaining}" for r in session.history]),
        last_state=str(last_state),
    )


def _restore(path: Path) -> tuple[scan.ScanSession, Path | None]:
    if not path.exists():
        raise SystemExit(f"no session at {path}. Run `dowser new` first.")

    stored = np.load(path, allow_pickle=False)
    session = scan.ScanSession(width=str(stored["width"]))

    if bool(stored["started"]):
        session._indices = stored["indices"]
        for line in stored["history"]:
            name, remaining = str(line).split("\t")
            session.history.append(scan.Round(name, int(remaining)))

    last = str(stored["last_state"])
    return session, Path(last) if last else None


def _address_space(path: Path):
    try:
        return load(path).address_space()
    except NotASaveState as error:
        raise SystemExit(f"{path}: {error}") from error
    except OSError as error:
        raise SystemExit(f"{path}: {error}") from error


def _report(session: scan.ScanSession, limit: int = 20) -> None:
    count = session.remaining
    noun = "candidate" if count == 1 else "candidates"
    print(f"{count} {noun}")

    if 0 < count <= limit:
        for candidate in session.candidates():
            print(f"  {candidate}")
    elif count > limit:
        print(f"  (showing none; narrow below {limit} or run `dowser list`)")


def cmd_new(args: argparse.Namespace) -> int:
    session = scan.ScanSession(width=args.width)
    _save(args.session, session, Path(""))
    print(f"new {args.width}-bit search at {args.session}")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    session, previous_state = _restore(args.session)

    factory, arity = FILTERS[args.filter]
    if len(args.values) != arity:
        raise SystemExit(f"{args.filter} takes {arity} value(s), got {len(args.values)}")
    filter_ = factory(*args.values)

    # A relative filter compares against the state the last round measured, so
    # replay it rather than storing a copy of every byte in the session file.
    if previous_state and previous_state.name and session.started:
        session._previous = _address_space(previous_state).read(session.width)

    space = _address_space(args.state)
    try:
        session.scan(space, filter_)
    except scan.NeedsPrevious as error:
        raise SystemExit(f"{error}. Start with an absolute filter such as `equals`.") from error
    except ValueError as error:
        raise SystemExit(str(error)) from error

    _save(args.session, session, args.state)
    _report(session)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    session, last_state = _restore(args.session)
    if not session.started or not last_state:
        raise SystemExit("nothing scanned yet")

    session._space = _address_space(last_state)
    found = session.candidates(limit=args.limit)

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "region": c.region,
                        "bank": c.bank,
                        "address": c.address,
                        "value": c.value,
                        "width": c.width,
                    }
                    for c in found
                ],
                indent=2,
            )
        )
    else:
        for candidate in found:
            print(candidate)
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    session, _ = _restore(args.session)
    if not session.history:
        print("nothing scanned yet")
        return 0

    width = max(len(r.filter_name) for r in session.history)
    for index, round_ in enumerate(session.history, start=1):
        print(f"  {index}. {round_.filter_name:<{width}}  {round_.remaining:>8,} left")
    return 0


def cmd_code(args: argparse.Namespace) -> int:
    try:
        address = int(args.address, 16)
        for code in codes.encode(address, args.value, bank=args.bank, width=args.width):
            print(code)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    return 0


# The live prompt trades words for keystrokes: a search is a dozen rounds and
# typing "decreased" a dozen times is how a good idea becomes a chore.
LIVE_HELP = """\
  47        the value is 47 now        <   it went down
  -12       it went down by 12         >   it went up
  +100      it went up by 100          =   it didn't change
  <47       less than 47               !   it changed
  >47       greater than 47

  list      show candidates            code [value]  write a code
  freeze N [addr]   hold candidates at N in the emulator (one, if named)
  thaw      release everything         reset  start over        quit
"""


def _live_filter(line: str):
    """Parse one line of the live prompt into a filter, or None."""
    line = line.strip()
    if not line:
        return None

    simple = {"<": scan.decreased, ">": scan.increased, "=": scan.unchanged, "!": scan.changed}
    if line in simple:
        return simple[line]()

    if line[0] in "<>" and line[1:].strip().lstrip("-+").isdigit():
        value = int(line[1:])
        return scan.less_than(value) if line[0] == "<" else scan.greater_than(value)

    if line[0] in "-+" and line[1:].isdigit():
        value = int(line[1:])
        return scan.decreased_by(value) if line[0] == "-" else scan.increased_by(value)

    if line.isdigit():
        return scan.equals(int(line))

    raise ValueError(f"don't know what {line!r} means")


def cmd_live(args: argparse.Namespace) -> int:
    from .live import Live, NotConnected

    session = scan.ScanSession(width=args.width)
    connection = Live(args.host, args.port)

    try:
        connection.connect()
        title = connection.title()
    except NotConnected as error:
        raise SystemExit(str(error)) from error

    print(f"connected to {title or 'a running game'} at {args.host}:{args.port}")
    print(f"{args.width}-bit search. `?` for help, `quit` to stop.\n")

    try:
        while True:
            try:
                line = input(f"[{session.remaining if session.started else '-'}] ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            lowered = line.lower()

            if lowered in ("quit", "q", "exit"):
                break
            if lowered in ("?", "help", "h"):
                print(LIVE_HELP)
                continue
            if lowered in ("reset", "r"):
                session.reset()
                print("started over")
                continue
            if lowered in ("list", "l"):
                session._space = connection.address_space()
                for candidate in session.candidates(limit=args.limit):
                    print(f"  {candidate}")
                continue
            if lowered.startswith("code"):
                _live_code(session, line)
                continue
            if lowered in ("thaw", "clear"):
                connection.clear()
                print("  released")
                continue
            if lowered.startswith("freeze"):
                _live_freeze(session, connection, line)
                continue

            try:
                filter_ = _live_filter(line)
            except ValueError as error:
                print(f"  {error}. `?` for help.")
                continue
            if filter_ is None:
                continue

            try:
                # The snapshot is taken now, at the moment you say the thing is
                # true — which is the whole reason this beats save files.
                remaining = session.scan(connection.address_space(), filter_)
            except scan.NeedsPrevious:
                print("  start with a value, like `47`.")
                continue
            except (ValueError, NotConnected) as error:
                print(f"  {error}")
                continue

            noun = "candidate" if remaining == 1 else "candidates"
            print(f"  {filter_.name}: {remaining} {noun}")
            if 0 < remaining <= 10:
                for candidate in session.candidates():
                    print(f"    {candidate}")
    finally:
        connection.close()

    return 0


# Freezing more than this at once stops being an experiment and starts being a
# way to corrupt a save, since every extra address is one more place the game
# didn't expect to change.
MAX_FREEZE = 8


def _live_freeze(session: scan.ScanSession, connection, line: str) -> None:
    """Hold the found address (or addresses) in the running emulator.

        freeze 16          every surviving candidate
        freeze 16 D0EF     just that one, for bisecting

    Freezing the whole set at once answers "is any of these the real one" in a
    single walk through the grass. Several addresses hold the same value and
    only one of them usually drives anything, so the fast path is to confirm the
    set works and then halve it.
    """
    parts = line.split()
    if len(parts) not in (2, 3) or not parts[1].isdigit():
        print("  usage: freeze <value> [address]")
        return

    value = int(parts[1])
    found = session.candidates(limit=MAX_FREEZE + 1)

    if not found:
        print("  nothing found yet")
        return

    if len(parts) == 3:
        wanted = parts[2].lstrip("$").removeprefix("0x").upper()
        found = [c for c in found if f"{c.address:04X}" == wanted]
        if not found:
            print(f"  ${wanted} isn't one of the candidates")
            return

    if len(found) > MAX_FREEZE:
        print(f"  {session.remaining} candidates; narrow to {MAX_FREEZE} or fewer first")
        return

    for candidate in found:
        connection.freeze(candidate.address, value, bank=candidate.bank)
        print(f"  holding {candidate.region}:{candidate.bank} ${candidate.address:04X} = {value}")
    print("  `thaw` to release")


def _live_code(session: scan.ScanSession, line: str) -> None:
    parts = line.split()
    if len(parts) != 2 or not parts[1].lstrip("-").isdigit():
        print("  usage: code <value>")
        return

    found = session.candidates(limit=2)
    if len(found) != 1:
        print(f"  {session.remaining} candidates; narrow to one first")
        return

    candidate = found[0]
    try:
        for code in codes.encode(
            candidate.address, int(parts[1]), bank=candidate.bank, width=session.width
        ):
            print(f"  {code}")
    except ValueError as error:
        print(f"  {error}")


def cmd_web(args: argparse.Namespace) -> int:
    try:
        from .web import serve
    except ImportError as error:
        raise SystemExit("the browser interface needs FastAPI: pip install -e '.[web]'") from error

    url = f"http://127.0.0.1:{args.port}"
    print(f"Dowser is at {url}   (ctrl-C to stop)")

    if not args.no_open:
        import threading
        import webbrowser

        # After a beat, so the server is answering by the time the tab opens.
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    serve(port=args.port, emulator_port=args.emulator_port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dowser",
        description="Find the Game Boy memory address behind a number.",
    )
    parser.add_argument(
        "--session",
        type=Path,
        default=DEFAULT_SESSION,
        help=f"where the search state lives (default: {DEFAULT_SESSION})",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    new = subparsers.add_parser("new", help="start a search, discarding any in progress")
    new.add_argument("--width", choices=sorted(WIDTHS), default="u8")
    new.set_defaults(func=cmd_new)

    scan_parser = subparsers.add_parser("scan", help="apply one filter to a save state")
    scan_parser.add_argument("state", type=Path)
    scan_parser.add_argument("filter", choices=sorted(FILTERS))
    scan_parser.add_argument("values", type=int, nargs="*")
    scan_parser.set_defaults(func=cmd_scan)

    list_parser = subparsers.add_parser("list", help="show surviving candidates")
    list_parser.add_argument("--limit", type=int, default=50)
    list_parser.add_argument("--json", action="store_true", help="machine-readable output")
    list_parser.set_defaults(func=cmd_list)

    history = subparsers.add_parser("history", help="what has been asked so far")
    history.set_defaults(func=cmd_history)

    live = subparsers.add_parser("live", help="search a running emulator, one keystroke a round")
    live.add_argument("--width", choices=sorted(WIDTHS), default="u8")
    live.add_argument("--host", default="127.0.0.1")
    live.add_argument("--port", type=int, default=8484)
    live.add_argument("--limit", type=int, default=50)
    live.set_defaults(func=cmd_live)

    web = subparsers.add_parser("web", help="open the search in a browser")
    web.add_argument("--port", type=int, default=8585)
    web.add_argument("--emulator-port", type=int, default=8484)
    web.add_argument("--no-open", action="store_true", help="don't launch a browser")
    web.set_defaults(func=cmd_web)

    code = subparsers.add_parser("code", help="write a code for an address")
    code.add_argument("address", help="hex, with or without $ or 0x")
    code.add_argument("value", type=int)
    code.add_argument("--width", type=int, choices=(8, 16), default=8)  # code bytes, not a reading
    code.add_argument("--bank", type=int, default=0)
    code.set_defaults(func=cmd_code)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if hasattr(args, "address"):
        args.address = args.address.lstrip("$").removeprefix("0x").removeprefix("0X")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
