"""vJoy output through ctypes.

The game only ever sees a plain joystick, so every function that can be bound in
Options -> Controls can be driven from the panel -- including the ones that have no
default key and are therefore unreachable by keystroke emulation.
"""

from __future__ import annotations

import ctypes
import threading
import time
from pathlib import Path

DLL_CANDIDATES = [
    Path(r"C:\Program Files\vJoy\x64\vJoyInterface.dll"),
    Path(r"C:\Program Files\vJoy\x86\vJoyInterface.dll"),
    Path(r"C:\Program Files (x86)\vJoy\x64\vJoyInterface.dll"),
]

STATUS_OWN, STATUS_FREE, STATUS_BUSY, STATUS_MISS, STATUS_UNKNOWN = range(5)
STATUS_TEXT = {
    STATUS_OWN: "owned by us",
    STATUS_FREE: "free",
    STATUS_BUSY: "in use by another program",
    STATUS_MISS: "device not configured",
    STATUS_UNKNOWN: "unknown",
}


class VJoy:
    def __init__(self, device: int = 1) -> None:
        self.device = device
        self.dll = None
        self.available = False
        self.reason = "not initialised"
        self._lock = threading.Lock()
        self._held: set[int] = set()

    def start(self) -> bool:
        dll_path = next((p for p in DLL_CANDIDATES if p.is_file()), None)
        if dll_path is None:
            self.reason = "vJoy is not installed"
            return False
        try:
            self.dll = ctypes.WinDLL(str(dll_path))
        except OSError as exc:
            self.reason = f"could not load vJoyInterface.dll ({exc})"
            return False

        self.dll.SetBtn.argtypes = [ctypes.c_int, ctypes.c_uint, ctypes.c_ubyte]
        self.dll.SetBtn.restype = ctypes.c_int
        self.dll.GetVJDStatus.argtypes = [ctypes.c_uint]
        self.dll.GetVJDStatus.restype = ctypes.c_int
        self.dll.AcquireVJD.argtypes = [ctypes.c_uint]
        self.dll.AcquireVJD.restype = ctypes.c_int
        self.dll.RelinquishVJD.argtypes = [ctypes.c_uint]
        self.dll.ResetVJD.argtypes = [ctypes.c_uint]

        if not self.dll.vJoyEnabled():
            self.reason = "the vJoy driver is installed but disabled"
            return False

        status = self.dll.GetVJDStatus(self.device)
        if status not in (STATUS_OWN, STATUS_FREE):
            self.reason = f"vJoy device {self.device} is {STATUS_TEXT.get(status, 'unavailable')}"
            return False
        if not self.dll.AcquireVJD(self.device):
            self.reason = f"could not acquire vJoy device {self.device}"
            return False

        self.dll.ResetVJD(self.device)
        self.available = True
        self.reason = "ready"
        return True

    def stop(self) -> None:
        if self.available and self.dll is not None:
            for button in list(self._held):
                self.set_button(button, False)
            self.dll.RelinquishVJD(self.device)
        self.available = False

    def set_button(self, button: int, pressed: bool) -> bool:
        if not self.available or button < 1 or button > 128:
            return False
        with self._lock:
            ok = bool(self.dll.SetBtn(1 if pressed else 0, self.device, button))
            if pressed:
                self._held.add(button)
            else:
                self._held.discard(button)
            return ok

    def pulse(self, button: int, ms: int = 70) -> bool:
        """Press and release, the joystick equivalent of tapping a key."""
        if not self.set_button(button, True):
            return False
        time.sleep(ms / 1000.0)
        self.set_button(button, False)
        return True

    def status(self) -> dict:
        return {"available": self.available, "device": self.device, "reason": self.reason}
