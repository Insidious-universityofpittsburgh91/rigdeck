"""Checks that the panel, the pairing page and their assets are actually served."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rigdeck import config as cfgmod  # noqa: E402

PORT = 8398
failures = []


def check(label, ok, detail=""):
    print(f"  [{'ok  ' if ok else 'FAIL'}] {label}{'  -- ' + str(detail) if detail else ''}")
    if not ok:
        failures.append(label)


def get(path):
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=5) as resp:
        return resp.status, resp.headers.get("Content-Type", ""), resp.read()


def main() -> int:
    print("\nRig Deck serving test\n")
    cfgmod.use_scratch_file(os.path.join(tempfile.gettempdir(), "rigdeck-servetest.json"))
    cfgmod.load()
    cfgmod.update({"port": PORT})

    from rigdeck import gameproc
    playing = gameproc.running_game()
    if playing:
        print(f"  {playing} is running. Close it first -- the mock feed writes the same")
        print("  shared memory block the game's plugin is using.\n")
        return 2

    from rigdeck.mockfeed import run as mock_run
    threading.Thread(target=mock_run, daemon=True).start()
    time.sleep(0.4)

    from rigdeck.app import RigDeck
    deck = RigDeck()
    threading.Thread(target=deck._loop, daemon=True).start()
    deck.server.start_background()
    time.sleep(0.5)

    for path, needle, ctype in [
        ("/", b'id="deck"', "text/html"),
        ("/index.html", b'data-cmd="light_modes"', "text/html"),
        ("/style.css", b"--accent", "text/css"),
        ("/app.js", b"resolvePending", "javascript"),
        ("/mapdata.js", b"window.MapData", "javascript"),
        ("/qr.js", b"window.QR", "javascript"),
        ("/pair.html", b"Pair your tablet", "text/html"),
        ("/manifest.webmanifest", b'"orientation": "landscape"', "manifest"),
        ("/icon.svg", b"<svg", "svg"),
        ("/sw.js", b"rigdeck-v2", "javascript"),
    ]:
        try:
            status, got_type, body = get(path)
            check(f"GET {path}", status == 200 and needle in body and ctype in got_type,
                  f"{status} {got_type} {len(body)}B")
        except Exception as exc:
            check(f"GET {path}", False, exc)

    # The exported map: served from disk, cacheable, and honestly 404 when a cell is
    # missing -- the tablet parses these as JSON and cannot be fed the panel instead.
    web = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
    for game in ("ets2", "ats"):
        meta = os.path.join(web, "maps", game, "meta.json")
        if not os.path.isfile(meta):
            check(f"{game} map exported", False, "run export_maps.ps1")
            continue
        try:
            status, ctype, body = get(f"/maps/{game}/meta.json")
            payload = json.loads(body)
            check(f"GET /maps/{game}/meta.json", status == 200 and "json" in ctype
                  and payload["counts"]["roads"] > 1000, payload.get("counts"))
        except Exception as exc:
            check(f"GET /maps/{game}/meta.json", False, exc)

    try:
        get("/maps/ets2/cells/99999_99999.json")
        check("a missing map cell 404s", False, "it served something")
    except urllib.error.HTTPError as exc:
        check("a missing map cell 404s", exc.code == 404, exc.code)

    status, _, body = get("/api/status")
    payload = json.loads(body)
    check("/api/status reports addresses", bool(payload.get("addresses")), payload.get("addresses"))
    check("/api/status carries the port", payload["config"]["port"] == PORT)
    check("/api/status shows the game", payload.get("game") == "ETS2", payload.get("game"))

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}\n")
        return 1
    print("all checks passed\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
