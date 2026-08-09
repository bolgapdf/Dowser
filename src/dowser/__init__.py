"""Dowser: find the address behind a number, and write the code that pins it.

    >>> from dowser import ScanSession, load, equals, decreased
    >>> session = ScanSession(width=8)
    >>> session.scan(load("before.state").address_space(), equals(47))
    312
    >>> session.scan(load("after.state").address_space(), decreased())
    2

Named after the Dowsing Machine, which also finds things that are definitely
there and refuses to say exactly where.
"""

from .codes import Code, encode, parse
from .live import Live, NotConnected, connect
from .memory import AddressSpace, Region, build_address_space
from .scan import (
    Candidate,
    Filter,
    NeedsPrevious,
    ScanSession,
    between,
    changed,
    decreased,
    decreased_by,
    equals,
    greater_than,
    increased,
    increased_by,
    less_than,
    not_equals,
    unchanged,
)
from .snapshot import NotASaveState, Snapshot, load, load_all

__version__ = "0.1.0"

__all__ = [
    "AddressSpace",
    "Candidate",
    "Code",
    "Filter",
    "Live",
    "NotConnected",
    "NeedsPrevious",
    "NotASaveState",
    "Region",
    "ScanSession",
    "Snapshot",
    "between",
    "build_address_space",
    "changed",
    "connect",
    "decreased",
    "decreased_by",
    "encode",
    "equals",
    "greater_than",
    "increased",
    "increased_by",
    "less_than",
    "load",
    "load_all",
    "not_equals",
    "parse",
    "unchanged",
]
