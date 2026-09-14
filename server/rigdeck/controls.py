"""Action registry and the command executor.

Every action maps to a vJoy button number that gets bound once in the game's
Options -> Controls. Actions whose state the telemetry reports back (`confirm`) let the
panel show a command as confirmed rather than merely sent.

Nothing here drives the game in a loop any more. The old level controls pulsed a button
and waited for telemetry to agree, which meant a control could refuse to act at all --
the retarder would not fire on a truck the game said had none, and high beam reported
"did not engage" whenever low beam was off, which is simply how the truck works. A
button now does exactly one thing: it presses the button the user bound. Whether that
was the right button to bind is answered by the read-back, not by refusing to press.
"""

from __future__ import annotations

import queue
import threading

# kind:
#   toggle    -- tap once, the game flips a state we can read back
#   momentary -- held down for as long as the finger is on the button
#   press     -- fire and forget, nothing in telemetry changes
#
# `game` is the entry to look for in Options -> Controls. Wording shifts a little
# between game versions and between ETS2 and ATS; the sense does not.
#
# `sii` is the game's own internal name for that entry, as it appears in the profile's
# controls.sii. bindwrite.py uses it to write all of these bindings in one go, which is
# the only reliable way to get them right: binding by hand means walking two lists in
# different orders at once, and one skipped entry silently shifts every binding after it
# -- which is exactly how the horn ended up on the wipers button.
#
# The button numbers are the contract between this list, the sheet, and controls.sii.
# Changing one means rebinding, so they are only ever renumbered deliberately.
CONTROLS = [
    # id                label                kind         btn  confirm            game                          sii
    ("lights_low",      "Lights",            "press",       1, None,              "Light modes",                "light"),
    ("high_beam",       "High beam",         "toggle",      2, "lights.high",     "High beam headlights",       "hblight"),
    ("beacon",          "Beacon",            "toggle",      3, "lights.beacon",   "Beacon",                     "beacon"),
    ("hazard",          "Hazard lights",     "toggle",      4, "lights.hazard",   "Hazard warning lights",      "flasher4way"),
    ("wipers",          "Wipers",            "toggle",      5, "wipers",          "Wipers",                     "wipers"),
    ("horn",            "Horn",              "momentary",   6, None,              "Horn",                       "horn"),
    ("air_horn",        "Air horn",          "momentary",   7, None,              "Air horn",                   "airhorn"),

    # Engine leads, because that is the order the job is done in: start it, then let
    # the brake off. The panel reads left to right the way the hands move.
    ("engine",          "Engine start/stop", "toggle",      8, "engine",          "Engine start/stop",          "engine"),
    ("park_brake",      "Parking brake",     "toggle",      9, "park_brake",      "Parking brake",              "parkingbrake"),
    ("trailer_brake",   "Trailer brake",     "momentary",  10, None,              "Trailer brake",              "trailerbrake"),
    ("diff_lock",       "Differential lock", "toggle",     11, "diff_lock",       "Differential lock",          "diflock"),
    ("retarder_down",   "Retarder decrease", "press",      12, None,              "Retarder decrease",          "retarderdown"),
    ("retarder_up",     "Retarder increase", "press",      13, None,              "Retarder increase",          "retarderup"),
    # engbraketog, not motorbrake. The plain "Engine brake" entry is a hold control -- it
    # engages while the button is down and lets go the moment it is released, so a 70 ms
    # pulse from a tablet switched it on and straight back off. The toggle entry is the
    # one that latches, which is what a button on a panel means.
    ("motor_brake",     "Engine brake",      "toggle",     14, "motor_brake",     "Engine brake (toggle)",      "engbraketog"),
    ("attach",          "Attach trailer",    "press",      15, None,              "Attach/detach trailer",      "attach"),

    ("cruise_set",      "Cruise set",        "toggle",     16, "cruise_on",       "Cruise control",             "cruiectrl"),
    ("cruise_down",     "Cruise slower",     "press",      17, None,              "Cruise control decrease",    "cruiectrldec"),
    ("cruise_up",       "Cruise faster",     "press",      18, None,              "Cruise control increase",    "cruiectrlinc"),

    ("display_mode",    "Dash display",      "press",      19, None,              "Dashboard display mode",     "display"),
    ("infotainment",    "Infotainment",      "press",      20, None,              "Infotainment display mode",  "infotainment"),
    ("quick_info",      "Quick info",        "press",      21, None,              "Route advisor mouse mode",   "advmouse"),
    ("virtual_mirrors", "Virtual mirrors",   "press",      22, None,              "Virtual mirrors",            "showmirrors"),
    ("hud_widgets",     "HUD widgets",       "press",      23, None,              "Show/hide HUD widgets",      "showhud"),
    ("camera",          "Camera",            "press",      24, None,              "Camera cycle",               "camcycle"),
    # Sits beside Camera on the panel but carries the last free button, because renumbering
    # the ones above it would silently invalidate every binding already in the profile.
    ("camera_interior", "Interior camera",   "press",      32, None,              "Interior camera",            "cam1"),
    ("adjust_vehicle",  "Vehicle adjust",    "press",      25, None,              "Vehicle adjustment",         "adjuster"),
    ("services",        "Services",          "press",      26, None,              "Services and adjustments",   "services"),
    ("garage",          "Garage manager",    "press",      27, None,              "Garage manager",             "gar_man"),

    ("world_map",       "World map",         "press",      28, None,              "Navigation map",             "navmap"),
    ("nav_mode",        "Navigation mode",   "press",      29, None,              "Dashboard map zoom",         "dashmapzoom"),
    ("nav_zoom_out",    "Nav zoom out",      "press",      30, None,              "Route advisor zoom out",     "advzoomout"),
    ("nav_zoom_in",     "Nav zoom in",       "press",      31, None,              "Route advisor zoom in",      "advzoomin"),

    # Interface keys, sent from the keyboard rather than vJoy -- see DEFAULT_KEYS.
    # Button 0 means "never bound", so these stay off the binding sheet.
    ("ui_enter",        "Enter",             "press",       0, None,              "",                           ""),
    ("ui_esc",          "Esc",               "press",       0, None,              "",                           ""),
]

BY_ID = {row[0]: {"id": row[0], "label": row[1], "kind": row[2], "button": row[3],
                  "confirm": row[4], "game": row[5], "sii": row[6]}
         for row in CONTROLS}

# Actions sent as a keystroke instead of a vJoy button. Enter and Esc are here because
# they drive menus, where a controller binding is the wrong tool and the game may refuse
# one outright. Anything given a key here bypasses vJoy entirely.
DEFAULT_KEYS = {
    "ui_enter": "enter",
    "ui_esc": "escape",
}


def dig(data: dict, path: str):
    node = data
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


class Executor:
    """Runs commands off the socket thread so pulses never block the telemetry feed."""

    def __init__(self, vjoy, cfg: dict, snapshot_fn) -> None:
        self.vjoy = vjoy
        self.cfg = cfg
        self.snapshot = snapshot_fn
        self.keys = dict(DEFAULT_KEYS)
        self.keys.update(cfg.get("keys") or {})
        self._queue: queue.Queue = queue.Queue()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    # -- public -------------------------------------------------------------
    def submit(self, message: dict, reply) -> None:
        self._queue.put((message, reply))

    # -- worker -------------------------------------------------------------
    def _run(self) -> None:
        while True:
            message, reply = self._queue.get()
            try:
                ok, detail = self._dispatch(message)
            except Exception as exc:  # a bad command must never kill the worker
                ok, detail = False, str(exc)
            if reply is not None:
                reply({"type": "ack", "seq": message.get("seq"), "id": message.get("id"),
                       "ok": ok, "detail": detail})

    def _dispatch(self, message: dict) -> tuple[bool, str]:
        action = BY_ID.get(message.get("id"))
        if action is None:
            return False, "unknown action"

        key = self.keys.get(action["id"])
        if key:
            from . import gameproc, keyboard
            # A keystroke lands on whatever window has focus. Saying so beats sending it
            # into the void and reporting success, which is indistinguishable from a
            # dead button at the other end.
            if not gameproc.has_focus():
                running = gameproc.running_game()
                return False, ("the game window is not in front -- a keystroke goes "
                               "wherever the focus is" if running else "no game running")
            if not keyboard.tap(key):
                return False, f"Windows would not send the {key} key"
            return True, f"key {key}"

        if not action["button"]:
            return False, f"{action['label']} needs a key set under \"keys\" in config.json"

        if not self.vjoy.available:
            return False, self.vjoy.reason

        pulse_ms = int(self.cfg.get("pulse_ms", 70))

        if action["kind"] == "momentary":
            self.vjoy.set_button(action["button"], bool(message.get("down")))
            return True, "held" if message.get("down") else "released"

        self.vjoy.pulse(action["button"], pulse_ms)
        return True, "pulsed"

    def _current(self, path: str):
        snap = self.snapshot()
        return dig(snap.get("data") or {}, path)


def binding_sheet() -> list[dict]:
    """What the user has to bind once in Options -> Controls."""
    return [
        {"button": row[3], "label": row[1], "id": row[0], "kind": row[2], "game": row[5],
         "sii": row[6],
         # a key set here wins over the button, so the sheet has to say so or the
         # binding looks broken when it is simply not the thing being used
         "key": DEFAULT_KEYS.get(row[0]) or ""}
        for row in sorted(CONTROLS, key=lambda r: r[3])
        if row[3] > 0
    ]
