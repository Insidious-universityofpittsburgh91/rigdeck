"""How many buttons does vJoy device 1 actually have?

A fresh vJoy install gives device 1 eight buttons. Rig Deck uses thirty-two, and vJoy
answers a press on a button that does not exist by quietly doing nothing -- the panel
lights up, the truck ignores it, and there is nothing anywhere that says why. So the
installer asks first and reconfigures if the answer is too small.

Prints one line: `buttons=N status=<text>`, and never raises.
"""

from __future__ import annotations

import ctypes
from pathlib import Path

DLLS = [
    Path(r"C:\Program Files\vJoy\x64\vJoyInterface.dll"),
    Path(r"C:\Program Files\vJoy\x86\vJoyInterface.dll"),
    Path(r"C:\Program Files (x86)\vJoy\x64\vJoyInterface.dll"),
]

STATUS = {0: "ours", 1: "free", 2: "in use by another program", 3: "not configured"}


def main() -> None:
    path = next((p for p in DLLS if p.is_file()), None)
    if path is None:
        print("buttons=0 status=vJoy is not installed")
        return
    try:
        dll = ctypes.WinDLL(str(path))
        dll.GetVJDButtonNumber.argtypes = [ctypes.c_uint]
        dll.GetVJDButtonNumber.restype = ctypes.c_int
        dll.GetVJDStatus.argtypes = [ctypes.c_uint]
        dll.GetVJDStatus.restype = ctypes.c_int
        if not dll.vJoyEnabled():
            print("buttons=0 status=the driver is installed but disabled")
            return
        buttons = dll.GetVJDButtonNumber(1)
        state = STATUS.get(dll.GetVJDStatus(1), "unknown")
        # "in use" is not a problem here: it means Rig Deck itself already has it.
        print(f"buttons={max(0, buttons)} status=device 1 has {max(0, buttons)} buttons, {state}")
    except Exception as exc:                       # never stop an install over this
        print(f"buttons=0 status=could not ask vJoy ({exc})")


if __name__ == "__main__":
    main()
