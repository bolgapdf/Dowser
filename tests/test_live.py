"""The live protocol, against a stand-in for Cartridge.

The fake speaks the same wire format the Swift side does, which is the only way
to test this without an emulator and a ROM in CI.
"""

from __future__ import annotations

import plistlib
import socket
import threading

import numpy as np
import pytest

from dowser.cli import _live_filter
from dowser.live import Live, NotConnected
from tests.test_snapshot import apple_compress

RNG = np.random.default_rng(31337)


def state_bytes(hp: int = 47, *, title: str = "POKEMON SILVER") -> bytes:
    ram = bytearray(RNG.integers(0, 256, size=0x8000, dtype=np.uint8).tobytes())
    ram[0x1123] = hp
    return apple_compress(
        plistlib.dumps(
            {
                "title": title,
                "workRAM": bytes(ram),
                "highRAM": bytes(0x7F),
                "unmappedIO": bytes(16),
                "mapper": {"romBank": 1, "ramBank": 0, "ramEnabled": True, "ram": b""},
                "carriedCycles": 0,
                "colorMode": True,
                "workRAMBank": 1,
            },
            fmt=plistlib.FMT_BINARY,
        )
    )


class FakeCartridge:
    """A loopback server speaking Cartridge's scan protocol."""

    def __init__(self, payload: bytes | None = None, title: str = "POKEMON SILVER") -> None:
        self.payload = payload if payload is not None else state_bytes()
        self.title = title
        self.frozen: list[str] = []
        self.socket = socket.socket()
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen(1)
        self.port = self.socket.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        # Serves connections one after another rather than just one: the web
        # server opens a fresh connection per request, so a single-shot fake
        # made every request after the first look like a dead emulator.
        while True:
            try:
                connection, _ = self.socket.accept()
            except OSError:
                return
            self._handle(connection)

    def _handle(self, connection) -> None:
        with connection:
            buffer = b""
            while True:
                try:
                    chunk = connection.recv(4096)
                except OSError:
                    return
                if not chunk:
                    return
                buffer += chunk

                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    command = line.decode("ascii", "replace").strip().upper()

                    if command == "PING":
                        connection.sendall(b"PONG\n")
                    elif command == "INFO":
                        connection.sendall(f"OK {self.title}\n".encode())
                    elif command == "SNAP":
                        connection.sendall(f"OK {len(self.payload)}\n".encode())
                        connection.sendall(self.payload)
                    elif command.startswith("FREEZE"):
                        self.frozen.append(command)
                        connection.sendall(f"OK {len(self.frozen)}\n".encode())
                    elif command == "CLEAR":
                        self.frozen.clear()
                        connection.sendall(b"OK 0\n")
                    elif command == "HELD":
                        connection.sendall(b"OK\n")
                    elif command == "BYE":
                        connection.sendall(b"OK\n")
                        return
                    else:
                        connection.sendall(b"ERR unknown command\n")

    def close(self) -> None:
        self.socket.close()


@pytest.fixture
def fake():
    server = FakeCartridge()
    yield server
    server.close()


def test_ping_and_title(fake):
    with Live(port=fake.port) as live:
        assert live.ping()
        assert live.title() == "POKEMON SILVER"


def test_snapshot_arrives_whole(fake):
    """A save state is bigger than one recv, so the length prefix earns its keep."""
    with Live(port=fake.port) as live:
        snapshot = live.snapshot()

    assert snapshot.title == "POKEMON SILVER"
    assert len(snapshot.work_ram) == 0x8000
    assert snapshot.work_ram[0x1123] == 47


def test_address_space_from_a_live_snapshot(fake):
    with Live(port=fake.port) as live:
        space = live.address_space()
    assert len(space) == 8 * 0x1000 + 0x7F


def test_a_closed_port_explains_how_to_open_it():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    port = server.getsockname()[1]
    server.close()

    with pytest.raises(NotConnected, match="Cheat Search"):
        Live(port=port, timeout=1.0).connect()


def test_a_server_that_hangs_up_mid_reply():
    class Truncating(FakeCartridge):
        def _handle(self, connection):
            with connection:
                connection.recv(4096)
                connection.sendall(b"OK 999999\n")  # promises far more than it sends
                connection.sendall(b"short")

    server = Truncating()
    try:
        with (
            pytest.raises(NotConnected, match="closed the connection"),
            Live(port=server.port, timeout=2.0) as live,
        ):
            live.snapshot()
    finally:
        server.close()


def test_error_replies_surface_as_exceptions():
    server = FakeCartridge()
    try:
        with Live(port=server.port) as live:
            live._send("NONSENSE")
            with pytest.raises(NotConnected, match="unknown command"):
                live._expect_ok(live._read_line())
    finally:
        server.close()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("47", "equals 47"),
        ("<", "decreased"),
        (">", "increased"),
        ("=", "unchanged"),
        ("!", "changed"),
        ("-12", "decreased by 12"),
        ("+100", "increased by 100"),
        ("<47", "less than 47"),
        (">47", "greater than 47"),
    ],
)
def test_live_shorthand(text, expected):
    assert _live_filter(text).name == expected


def test_live_shorthand_rejects_nonsense():
    with pytest.raises(ValueError, match="don't know"):
        _live_filter("banana")
