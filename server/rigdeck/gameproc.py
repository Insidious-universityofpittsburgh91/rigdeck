"""Is the game actually running?

Telemetry stops flowing whenever the game is not simulating -- the main menu, the
options screens, the controls binding page. That is not the same thing as the game
being closed, and the panel has to say which, because in a menu every button still
works: vJoy is a real HID device and the game reads it there just as happily.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

TH32CS_SNAPPROCESS = 0x00000002
MAX_PATH = 260

EXECUTABLES = {
    "eurotrucks2.exe": "ETS2",
    "amtrucks.exe": "ATS",
}

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * MAX_PATH),
    ]


_kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
_kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
_kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetForegroundWindow.restype = wintypes.HWND

_cached: str | None = None
_cached_pid = 0
_checked = 0.0
INTERVAL = 3.0   # the answer changes about once an hour; polling it at 20 Hz would be silly


def running_game(now: float | None = None) -> str | None:
    """"ETS2", "ATS" or None. Cheap to call on every tick -- the answer is cached."""
    global _cached, _cached_pid, _checked
    now = time.monotonic() if now is None else now
    if now - _checked < INTERVAL:
        return _cached
    _checked = now

    snapshot = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == wintypes.HANDLE(-1).value or not snapshot:
        return _cached
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        found, pid = None, 0
        if _kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            while True:
                name = EXECUTABLES.get(entry.szExeFile.lower())
                if name:
                    found, pid = name, entry.th32ProcessID
                    break
                if not _kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
        _cached, _cached_pid = found, pid
        return found
    finally:
        _kernel32.CloseHandle(snapshot)


def has_focus() -> bool:
    """Is the game the window Windows is currently sending keystrokes to?

    Keystrokes go wherever the focus is, so pressing Esc on the tablet while the game
    is behind another window sends Esc to that other window instead. vJoy buttons have
    no such problem -- the game reads the device whether it is in front or not -- which
    is why this only matters to the two keys that are keystrokes.
    """
    running_game()
    if not _cached_pid:
        return False
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return False
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value == _cached_pid
