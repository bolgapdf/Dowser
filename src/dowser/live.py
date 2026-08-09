"""Pulling snapshots from a running emulator instead of from files.

Cartridge serves save states over loopback when Cheat Search is switched on in
Settings. That turns each round of a search from "pause, save a state, name it,
run a command" into one keystroke while the game keeps playing, which is the
difference between a five-minute hunt and a thirty-second one.

The protocol is deliberately small. Commands are ASCII lines; replies start with
a status line, and `SNAP` follows its line with that many bytes of save state:

    -> SNAP
    <- OK 104213
    <- <104213 bytes>

Using the save-state format rather than inventing a leaner one means the parser
in `snapshot.py` already understands what comes back.
"""

from __future__ import annotations

import socket
from contextlib import contextmanager

from .memory import AddressSpace, build_address_space
from .snapshot import Snapshot, _plist_from

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8484


class NotConnected(Exception):
    """The emulator isn't listening, or stopped part-way through a reply."""


class Live:
    """A connection to a running emulator.

    Usable as a context manager, which is the only way worth using it — a
    half-closed socket leaves the server holding a connection until it notices.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        *,
        timeout: float = 5.0,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._socket: socket.socket | None = None
        self._buffer = b""

    # MARK: connection

    def connect(self) -> Live:
        try:
            self._socket = socket.create_connection((self.host, self.port), self.timeout)
            self._socket.settimeout(self.timeout)
        except OSError as error:
            raise NotConnected(
                f"nothing listening on {self.host}:{self.port} — "
                "switch on Settings > Advanced > Cheat Search in Cartridge"
            ) from error
        return self

    def close(self) -> None:
        if self._socket is not None:
            try:
                self._send("BYE")
                self._read_line()
            except (OSError, NotConnected):
                pass  # Going away regardless.
            self._socket.close()
            self._socket = None

    def __enter__(self) -> Live:
        return self.connect()

    def __exit__(self, *_exc) -> None:
        self.close()

    # MARK: wire

    def _send(self, command: str) -> None:
        if self._socket is None:
            raise NotConnected("not connected")
        self._socket.sendall(f"{command}\n".encode("ascii"))

    def _read_exactly(self, count: int) -> bytes:
        while len(self._buffer) < count:
            try:
                chunk = self._socket.recv(65536)  # type: ignore[union-attr]
            except OSError as error:
                raise NotConnected(str(error)) from error
            if not chunk:
                raise NotConnected("emulator closed the connection")
            self._buffer += chunk

        taken, self._buffer = self._buffer[:count], self._buffer[count:]
        return taken

    def _read_line(self) -> str:
        while b"\n" not in self._buffer:
            try:
                chunk = self._socket.recv(65536)  # type: ignore[union-attr]
            except OSError as error:
                raise NotConnected(str(error)) from error
            if not chunk:
                raise NotConnected("emulator closed the connection")
            self._buffer += chunk

        line, self._buffer = self._buffer.split(b"\n", 1)
        return line.decode("ascii", errors="replace").strip()

    def _expect_ok(self, reply: str) -> str:
        if reply.startswith("OK"):
            return reply[2:].strip()
        if reply.startswith("ERR"):
            raise NotConnected(reply[3:].strip() or "emulator refused")
        raise NotConnected(f"unexpected reply: {reply!r}")

    # MARK: commands

    def ping(self) -> bool:
        self._send("PING")
        return self._read_line() == "PONG"

    def title(self) -> str:
        self._send("INFO")
        return self._expect_ok(self._read_line())

    def snapshot(self) -> Snapshot:
        """The running console, right now."""
        self._send("SNAP")
        size = int(self._expect_ok(self._read_line()) or 0)
        plist = _plist_from(self._read_exactly(size))
        mapper = plist.get("mapper") or {}

        return Snapshot(
            title=plist.get("title", ""),
            work_ram=bytes(plist["workRAM"]),
            high_ram=bytes(plist["highRAM"]),
            cartridge_ram=bytes(mapper.get("ram", b"")),
            color_mode=bool(plist.get("colorMode", False)),
            work_ram_bank=int(plist.get("workRAMBank", 1)),
        )

    def address_space(self) -> AddressSpace:
        snapshot = self.snapshot()
        return build_address_space(
            snapshot.work_ram,
            snapshot.high_ram,
            snapshot.cartridge_ram,
            color_mode=snapshot.color_mode,
        )


@contextmanager
def connect(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, *, timeout: float = 5.0):
    live = Live(host, port, timeout=timeout)
    try:
        yield live.connect()
    finally:
        live.close()
