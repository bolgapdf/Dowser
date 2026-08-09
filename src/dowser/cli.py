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
        width=session.width,
        indices=session._indices if session._indices is not None else np.array([], dtype=np.int64),
        started=session.started,
        history=np.array([f"{r.filter_name}\t{r.remaining}" for r in session.history]),
        last_state=str(last_state),
    )


def _restore(path: Path) -> tuple[scan.ScanSession, Path | None]:
    if not path.exists():
        raise SystemExit(f"no session at {path}. Run `dowser new` first.")

    stored = np.load(path, allow_pickle=False)
    session = scan.ScanSession(width=int(stored["width"]))

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
    new.add_argument("--width", type=int, choices=(8, 16), default=8)
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

    code = subparsers.add_parser("code", help="write a code for an address")
    code.add_argument("address", help="hex, with or without $ or 0x")
    code.add_argument("value", type=int)
    code.add_argument("--width", type=int, choices=(8, 16), default=8)
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
