"""Scancode keystrokes via SendInput, for game functions that refuse a joystick binding.

Interface shortcuts (tow to road, quick save, world map) live in the game's UI layer and
are not always bindable to a controller button. Scancodes are used rather than virtual
keys because the game reads raw input; a keystroke only lands if the game has focus.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001
INPUT_KEYBOARD = 1

# set 1 make codes
SCANCODES = {
    "f1": 0x3B, "f2": 0x3C, "f3": 0x3D, "f4": 0x3E, "f5": 0x3F, "f6": 0x40,
    "f7": 0x41, "f8": 0x42, "f9": 0x43, "f10": 0x44, "f11": 0x57, "f12": 0x58,
    "escape": 0x01, "space": 0x39, "enter": 0x1C, "tab": 0x0F,
    "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06,
    "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B,
    "a": 0x1E, "b": 0x30, "c": 0x2E, "d": 0x20, "e": 0x12, "f": 0x21,
    "g": 0x22, "h": 0x23, "i": 0x17, "j": 0x24, "k": 0x25, "l": 0x26,
    "m": 0x32, "n": 0x31, "o": 0x18, "p": 0x19, "q": 0x10, "r": 0x13,
    "s": 0x1F, "t": 0x14, "u": 0x16, "v": 0x2F, "w": 0x11, "x": 0x2D,
    "y": 0x15, "z": 0x2C,
}


# SendInput checks the size it is handed against its own INPUT and does nothing at all
# if they differ, so the union has to be as wide as its widest member -- MOUSEINPUT,
# not KEYBDINPUT. Declaring only the keyboard arm made INPUT 32 bytes where Windows
# wants 40, and every keystroke was rejected silently: the call returned 0, the panel
# was told the key had been sent, and nothing reached the game.
ULONG_PTR = wintypes.WPARAM


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTunion(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTunion)]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT


def _event(scan: int, keyup: bool) -> INPUT:
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if keyup else 0)
    return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(0, scan, flags, 0, 0))


def _send(event: INPUT) -> bool:
    return user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT)) == 1


def tap(name: str, hold_ms: int = 45) -> bool:
    """Press and release a key by name.

    False means the keystroke did not happen -- either the name is not one we know, or
    Windows refused the injection. A keystroke also only reaches the game while the game
    has focus; that much this cannot see, and does not claim to.
    """
    scan = SCANCODES.get(str(name).strip().lower())
    if scan is None:
        return False
    if not _send(_event(scan, False)):
        return False
    time.sleep(hold_ms / 1000.0)
    return _send(_event(scan, True))
