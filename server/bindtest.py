"""Hold one vJoy button, on and off, long enough to bind it by hand.

    python bindtest.py [button] [seconds]

The panel pulses a button for about 70 ms, which is right for driving and wrong for
the game's "press a button" dialog if that dialog wants a longer press. This holds
button 7 for over a second at a time so there is nothing subtle left to blame, and
prints what Windows sees so the game's silence can be told apart from vJoy's.

Goes through the running server rather than vJoy directly -- the server owns the
device, and two feeders cannot hold it at once.
"""

from __future__ import annotations

import ctypes
import json
import sys
import time
from ctypes import wintypes

from rigdeck import config as cfgmod
from selftest import ws_connect, ws_send

JOY_RETURNBUTTONS = 0x00000080


class JOYINFOEX(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("dwXpos", wintypes.DWORD), ("dwYpos", wintypes.DWORD),
                ("dwZpos", wintypes.DWORD), ("dwRpos", wintypes.DWORD),
                ("dwUpos", wintypes.DWORD), ("dwVpos", wintypes.DWORD),
                ("dwButtons", wintypes.DWORD), ("dwButtonNumber", wintypes.DWORD),
                ("dwPOV", wintypes.DWORD), ("dwReserved1", wintypes.DWORD),
                ("dwReserved2", wintypes.DWORD)]


def find_vjoy() -> int | None:
    """The winmm joystick id of the vJoy device -- what the game reads, not what we send."""
    class JOYCAPSW(ctypes.Structure):
        _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD),
                    ("szPname", wintypes.WCHAR * 32),
                    ("wXmin", wintypes.UINT), ("wXmax", wintypes.UINT),
                    ("wYmin", wintypes.UINT), ("wYmax", wintypes.UINT),
                    ("wZmin", wintypes.UINT), ("wZmax", wintypes.UINT),
                    ("wNumButtons", wintypes.UINT),
                    ("wPeriodMin", wintypes.UINT), ("wPeriodMax", wintypes.UINT),
                    ("wRmin", wintypes.UINT), ("wRmax", wintypes.UINT),
                    ("wUmin", wintypes.UINT), ("wUmax", wintypes.UINT),
                    ("wVmin", wintypes.UINT), ("wVmax", wintypes.UINT),
                    ("wCaps", wintypes.UINT), ("wMaxAxes", wintypes.UINT),
                    ("wNumAxes", wintypes.UINT), ("wMaxButtons", wintypes.UINT),
                    ("szRegKey", wintypes.WCHAR * 32), ("szOEMVxD", wintypes.WCHAR * 260)]

    caps = JOYCAPSW()
    for index in range(16):
        if winmm.joyGetDevCapsW(index, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
            if caps.wMid == 0x1234 and caps.wPid == 0xBEAD:
                return index
    return None


winmm = ctypes.WinDLL("winmm")


def main() -> int:
    button = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 90.0

    joy = find_vjoy()
    if joy is None:
        print("  vJoy is not among the joysticks Windows lists. Nothing to test.")
        return 2

    port = int(cfgmod.load().get("port", 8384))
    try:
        sock, _ = ws_connect("127.0.0.1", port)
    except OSError as exc:
        print(f"  Rig Deck is not running on port {port} ({exc}). Open it first.")
        return 2

    info = JOYINFOEX()
    info.dwSize = ctypes.sizeof(info)
    info.dwFlags = JOY_RETURNBUTTONS
    mask = 1 << (button - 1)

    print(f"\n  Holding vJoy button {button} for {seconds:.0f} s: 1.2 s down, 0.8 s up.\n")
    print("  In the game: Options -> Controls, click the action you want, and watch.\n")

    deadline = time.monotonic() + seconds
    presses = 0
    while time.monotonic() < deadline:
        ws_send(sock, json.dumps({"type": "cmd", "id": "horn", "seq": presses, "down": True}))
        time.sleep(0.15)
        winmm.joyGetPosEx(joy, ctypes.byref(info))
        held = bool(info.dwButtons & mask)
        presses += 1
        print(f"  press {presses:3}  Windows sees button {button}: "
              f"{'DOWN' if held else 'not down -- the server never set it'}")
        time.sleep(1.05)
        ws_send(sock, json.dumps({"type": "cmd", "id": "horn", "seq": presses, "down": False}))
        time.sleep(0.8)

    sock.close()
    print("\n  Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
