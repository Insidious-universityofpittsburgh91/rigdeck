"""Smoke test: start the mock feed and the server, connect a websocket, check a frame.

    python selftest.py

Exits non-zero with a description of what failed.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rigdeck import config as cfgmod  # noqa: E402
from rigdeck.telemetry import TelemetryReader  # noqa: E402

PORT = 8399
FAILURES = []


def check(label, condition, detail=""):
    mark = "ok  " if condition else "FAIL"
    print(f"  [{mark}] {label}{'  -- ' + str(detail) if detail else ''}")
    if not condition:
        FAILURES.append(label)


def ws_connect(host, port, path="/ws"):
    sock = socket.create_connection((host, port), timeout=5)
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall(
        f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
        f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n\r\n".encode()
    )
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("handshake failed")
        buf += chunk
    if b"101" not in buf.split(b"\r\n")[0]:
        raise ConnectionError(f"no upgrade: {buf.split(chr(13).encode())[0]!r}")
    return sock, buf.split(b"\r\n\r\n", 1)[1]


def ws_send(sock, text):
    payload = text.encode()
    mask = os.urandom(4)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    header = bytes([0x81, 0x80 | len(payload)]) if len(payload) < 126 else \
        bytes([0x81, 254]) + struct.pack(">H", len(payload))
    sock.sendall(header + mask + masked)


def ws_read(sock, leftover=b""):
    buf = leftover

    def need(n):
        nonlocal buf
        while len(buf) < n:
            chunk = sock.recv(65536)
            if not chunk:
                raise ConnectionError("closed")
            buf += chunk
        out, buf = buf[:n], buf[n:]
        return out

    b0, b1 = need(2)
    length = b1 & 0x7F
    if length == 126:
        length = struct.unpack(">H", need(2))[0]
    elif length == 127:
        length = struct.unpack(">Q", need(8))[0]
    payload = need(length) if length else b""
    return payload.decode("utf-8", "replace"), buf


def main() -> int:
    print("\nRig Deck self test\n")

    cfgmod.use_scratch_file(os.path.join(tempfile.gettempdir(), "rigdeck-selftest.json"))
    cfgmod.load()
    cfgmod.update({"port": PORT})

    # Before anything writes telemetry: the reader must not conjure the block into
    # existence. A read-only one left behind by the panel stops the game's plugin from
    # creating its read-write one, and the panel then sees nothing for the whole session.
    # The mock feed writes the same block the game's plugin does, so running this with
    # a game open would feed the game's own dashboard invented numbers. Refuse instead.
    from rigdeck import gameproc
    playing = gameproc.running_game()
    if playing:
        print(f"  {playing} is running. Close it first -- the mock feed would overwrite")
        print("  the telemetry block the game's plugin is using.\n")
        return 2

    from rigdeck.telemetry import _mapping_exists
    if _mapping_exists():
        check("shared memory is free before the test", False, "something is already writing it")
    else:
        probe = TelemetryReader()
        check("with no game, the reader reports offline", probe.read().online is False)
        check("with no game, the reader creates nothing", not _mapping_exists())
        probe.close()

    from rigdeck.mockfeed import run as mock_run
    threading.Thread(target=mock_run, daemon=True).start()
    time.sleep(0.6)

    reader = TelemetryReader()
    snap = reader.read()
    check("shared memory reads as online", snap.online)
    check("game identified", snap.game == "ETS2", snap.game)
    check("plugin revision", snap.plugin_rev == 12, snap.plugin_rev)
    speed = snap.data.get("speed_ms", 0)
    check("speed is plausible", 15 < speed < 30, f"{speed:.2f} m/s")
    check("destination string decoded", snap.data["job"]["city_dst"] == "Rotterdam",
          snap.data["job"]["city_dst"])
    check("cargo string decoded", snap.data["job"]["cargo"] == "Cement",
          snap.data["job"]["cargo"])
    check("trailer attached flag", snap.data["job"]["trailer_attached"] is True)
    check("income read", snap.data["job"]["income"] == 3480, snap.data["job"]["income"])
    check("low beam reported", snap.data["lights"]["beam"] == 2, snap.data["lights"]["beam"])
    check("wear decoded", abs(snap.data["wear"]["cabin"] - 0.11) < 0.001,
          snap.data["wear"]["cabin"])
    check("heading in 0..1", 0 <= snap.data["world"]["heading"] <= 1,
          snap.data["world"]["heading"])
    check("retarder steps reported", snap.data["retarder_steps"] == 3,
          snap.data["retarder_steps"])

    # American trucks usually have no retarder at all, and the panel has to say so
    # rather than pulse a binding that was never going to move anything.
    from rigdeck.controls import Executor
    bare = Executor(None, {}, lambda: {"data": {"retarder_steps": 0, "retarder": 0}})
    ok, detail = bare._set_retarder(2, 70)
    check("no-retarder truck refused clearly", not ok and "no retarder" in detail, detail)

    from rigdeck.app import RigDeck
    deck = RigDeck()
    threading.Thread(target=deck._loop, daemon=True).start()
    deck.server.start_background()
    time.sleep(0.5)

    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/status", timeout=5) as resp:
        status = json.loads(resp.read())
    check("http /api/status", status.get("online") is True, status.get("game"))

    sock, leftover = ws_connect("127.0.0.1", PORT)
    hello, leftover = ws_read(sock, leftover)
    hello = json.loads(hello)
    check("websocket hello", hello.get("type") == "hello", hello.get("type"))
    check("binding sheet sent", len(hello.get("controls") or []) >= 30,
          len(hello.get("controls") or []))

    frame = None
    for _ in range(8):
        text, leftover = ws_read(sock, leftover)
        message = json.loads(text)
        if message.get("type") == "tel":
            frame = message
            break
    check("telemetry frame over websocket", frame is not None)
    if frame:
        check("frame marked online", frame.get("online") is True)
        check("units resolved for ETS2", frame.get("units") == "metric", frame.get("units"))
        check("currency resolved for ETS2", frame.get("currency") == "EUR", frame.get("currency"))
        check("frame carries speed", "speed_ms" in frame.get("data", {}))

    ws_send(sock, json.dumps({"type": "cmd", "id": "beacon", "seq": 1}))
    ack = None
    for _ in range(40):
        text, leftover = ws_read(sock, leftover)
        message = json.loads(text)
        if message.get("type") == "ack":
            ack = message
            break
    check("command acknowledged", ack is not None, ack)
    if ack:
        # vJoy is not installed on this machine yet, so a refusal with a reason is correct
        check("ack explains itself", bool(ack.get("detail")), ack.get("detail"))

    ws_send(sock, json.dumps({"type": "config", "changes": {"units": "imperial"}}))
    time.sleep(0.4)
    for _ in range(40):
        text, leftover = ws_read(sock, leftover)
        message = json.loads(text)
        if message.get("type") == "tel" and message.get("units") == "imperial":
            break
    check("unit switch takes effect", message.get("units") == "imperial", message.get("units"))
    cfgmod.update({"units": "auto"})

    sock.close()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed: {', '.join(FAILURES)}\n")
        return 1
    print("all checks passed\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
