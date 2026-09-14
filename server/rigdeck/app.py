"""Wires telemetry, the control executor and the web server together."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from . import config as cfgmod
from . import controls as controlsmod
from . import gameproc
from . import mapstate
from .telemetry import TelemetryReader
from .vjoy import VJoy
from .wsserver import Hub, RigDeckServer, lan_addresses

WEB_ROOT = Path(__file__).resolve().parent.parent.parent / "web"


class RigDeck:
    def __init__(self) -> None:
        self.cfg = cfgmod.load()
        self.hub = Hub()
        self.reader = TelemetryReader()
        self.vjoy = VJoy(int(self.cfg.get("vjoy_device", 1)))
        self.vjoy.start()

        self._snapshot: dict = {"online": False, "data": {}}
        self._map_game, self._map_checked, self._map_note = None, 0.0, ""
        self._lock = threading.Lock()
        self._stop = threading.Event()

        self.executor = controlsmod.Executor(self.vjoy, self.cfg, self.get_snapshot)
        self.hub.on_command = self._on_command
        self.hub.on_connect = self._on_connect

        self.server = RigDeckServer(self.hub, WEB_ROOT, self, int(self.cfg["port"]))

    # -- snapshot -----------------------------------------------------------
    def get_snapshot(self) -> dict:
        with self._lock:
            return self._snapshot

    # -- http api -----------------------------------------------------------
    def status(self) -> dict:
        snap = self.get_snapshot()
        return {
            "online": snap.get("online", False),
            "running": snap.get("running"),
            "game": snap.get("game", "unknown"),
            "vjoy": self.vjoy.status(),
            "clients": self.hub.client_count,
            "addresses": lan_addresses(),
            "config": self.cfg,
        }

    def get_config(self) -> dict:
        return {"config": self.cfg, "controls": controlsmod.binding_sheet()}

    def set_config(self, changes: dict) -> dict:
        self.cfg = cfgmod.update(changes)
        self.executor.cfg = self.cfg
        return {"config": self.cfg}

    # -- websocket ----------------------------------------------------------
    def _on_connect(self, client) -> None:
        import json

        client.send_text(json.dumps({
            "type": "hello",
            "config": self.cfg,
            "controls": controlsmod.binding_sheet(),
            "vjoy": self.vjoy.status(),
        }))

    def _on_command(self, message: dict, client) -> None:
        import json

        kind = message.get("type")
        if kind == "cmd":
            self.executor.submit(message, lambda payload: client.send_text(json.dumps(payload)))
        elif kind == "config":
            self.set_config(message.get("changes") or {})
            client.send_text(json.dumps({"type": "hello", "config": self.cfg,
                                         "controls": controlsmod.binding_sheet(),
                                         "vjoy": self.vjoy.status()}))
        elif kind == "ping":
            client.send_text(json.dumps({"type": "pong", "t": message.get("t")}))

    # -- map freshness ------------------------------------------------------
    def map_warning(self, game: str) -> str:
        """One sentence if the exported map has fallen behind the game, else "".

        Cached hard: this reads a log file that runs to megabytes, and the answer only
        changes when the game is restarted with different mods -- which cannot happen
        while it is running and being watched.
        """
        if game in (None, "unknown"):
            return ""
        now = time.monotonic()
        if game == self._map_game and now - self._map_checked < 300:
            return self._map_note
        self._map_game, self._map_checked = game, now
        try:
            self._map_note = mapstate.check(game).get("note", "")
        except Exception:
            self._map_note = ""   # never let a missing folder take the telemetry down
        return self._map_note

    # -- telemetry loop -----------------------------------------------------
    def _loop(self) -> None:
        period = 1.0 / max(1, int(self.cfg.get("tick_hz", 20)))
        while not self._stop.is_set():
            started = time.monotonic()
            running = None
            try:
                # Inside the guard: anything that throws out here kills the telemetry
                # thread for the rest of the session, and the panel just goes quiet.
                running = gameproc.running_game()
                snap = self.reader.read()
                game = snap.game if snap.game != "unknown" else (running or "unknown")
                units, currency = cfgmod.resolve_units(self.cfg, game)
                payload = {
                    "type": "tel",
                    "t": int(time.time() * 1000),
                    "online": snap.online,
                    # Telemetry stops in every menu, so "no data" and "no game" are
                    # different things and the panel has to be able to tell them apart.
                    "running": running,
                    "paused": snap.paused,
                    "game": snap.game,
                    "plugin_rev": snap.plugin_rev,
                    "units": units,
                    "currency": currency,
                    "vjoy": self.vjoy.available,
                    "data": snap.data,
                }
                warning = self.map_warning(game)
                if warning:
                    payload["map_warning"] = warning
            except Exception as exc:
                payload = {"type": "tel", "t": int(time.time() * 1000), "online": False,
                           "running": running, "error": str(exc), "data": {}}
            with self._lock:
                self._snapshot = payload
            self.hub.broadcast(payload)
            time.sleep(max(0.0, period - (time.monotonic() - started)))

    # -- lifecycle ----------------------------------------------------------
    def run(self) -> None:
        threading.Thread(target=self._loop, daemon=True).start()
        self.server.start_background()
        self._banner()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nshutting down")
        finally:
            self._stop.set()
            self.vjoy.stop()
            self.reader.close()

    def _banner(self) -> None:
        port = self.cfg["port"]
        addresses = lan_addresses()
        print("\n  RIG DECK\n")
        print(f"  panel      http://{addresses[0]}:{port}")
        print(f"  pairing    http://localhost:{port}/pair.html   (scan this from the tablet)")
        if len(addresses) > 1:
            print(f"  also on    {', '.join(f'{a}:{port}' for a in addresses[1:])}")
        vj = self.vjoy.status()
        print(f"  vJoy       {'ready, device %d' % vj['device'] if vj['available'] else vj['reason']}")
        print(f"  telemetry  waiting for the game...\n")


def main() -> None:
    RigDeck().run()
