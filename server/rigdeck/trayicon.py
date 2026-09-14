"""A tray icon, drawn and driven straight through Win32.

The rest of the project refuses to install anything with pip, and this is no exception:
the icon is rasterised here pixel by pixel and handed to Windows as a DIB, and the menu
and message loop are the plain API. It is more code than importing a library, but it is
code that cannot stop working because a wheel was not published for a new Python.
"""

from __future__ import annotations

import ctypes
import math
import struct
from ctypes import wintypes
from typing import Callable

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)

WM_DESTROY = 0x0002
WM_COMMAND = 0x0111
WM_TIMER = 0x0113
WM_CLOSE = 0x0010
WM_TRAY = 0x0400 + 1          # our own callback message
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x01, 0x02, 0x04, 0x10
NIIF_INFO = 0x01
ERROR_ALREADY_EXISTS = 183

MF_STRING, MF_SEPARATOR, MF_CHECKED, MF_GRAYED = 0x0000, 0x0800, 0x0008, 0x0001
MF_POPUP = 0x0010
TPM_RIGHTBUTTON, TPM_RETURNCMD = 0x0002, 0x0100

IMAGE_ICON = 1
BI_RGB = 0
DIB_RGB_COLORS = 0


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_byte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", wintypes.HICON),
    ]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HANDLE),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
                ("yHotspot", wintypes.DWORD), ("hbmMask", wintypes.HBITMAP),
                ("hbmColor", wintypes.HBITMAP)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


# Every prototype is spelled out. Left to guess, ctypes assumes a C int, and a 64-bit
# handle then overflows on the way back in -- which is exactly what happens the first
# time you try to free a bitmap.
HANDLE, HWND, HMENU = wintypes.HANDLE, wintypes.HWND, wintypes.HMENU
UINT, DWORD, LPCWSTR = wintypes.UINT, wintypes.DWORD, wintypes.LPCWSTR
UINT_PTR = ctypes.c_size_t

user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [HWND, UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wintypes.ATOM
user32.CreateWindowExW.restype = HWND
user32.CreateWindowExW.argtypes = [DWORD, LPCWSTR, LPCWSTR, DWORD, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, HWND,
                                   HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
user32.RegisterWindowMessageW.restype = UINT
user32.RegisterWindowMessageW.argtypes = [LPCWSTR]
user32.CreatePopupMenu.restype = HMENU
user32.AppendMenuW.argtypes = [HMENU, UINT, UINT_PTR, LPCWSTR]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.TrackPopupMenu.argtypes = [HMENU, UINT, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, HWND, ctypes.c_void_p]
user32.DestroyMenu.argtypes = [HMENU]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.SetForegroundWindow.argtypes = [HWND]
user32.SetTimer.restype = UINT_PTR
user32.SetTimer.argtypes = [HWND, UINT_PTR, UINT, ctypes.c_void_p]
user32.PostMessageW.argtypes = [HWND, UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.GetMessageW.restype = ctypes.c_int
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), HWND, UINT, UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.CreateIconIndirect.restype = wintypes.HICON
user32.CreateIconIndirect.argtypes = [ctypes.POINTER(ICONINFO)]
user32.DestroyIcon.argtypes = [wintypes.HICON]

gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.CreateDIBSection.argtypes = [HANDLE, ctypes.POINTER(BITMAPINFO), UINT,
                                   ctypes.POINTER(ctypes.c_void_p), HANDLE, DWORD]
gdi32.CreateBitmap.restype = wintypes.HBITMAP
gdi32.CreateBitmap.argtypes = [ctypes.c_int, ctypes.c_int, UINT, UINT, ctypes.c_void_p]
gdi32.DeleteObject.argtypes = [HANDLE]

shell32.Shell_NotifyIconW.restype = wintypes.BOOL
shell32.Shell_NotifyIconW.argtypes = [DWORD, ctypes.POINTER(NOTIFYICONDATAW)]

kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = [LPCWSTR]
kernel32.CreateMutexW.restype = HANDLE
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, LPCWSTR]


def claim_single_instance(name: str):
    """A handle if we are the first, None if a copy is already running.

    Windows lets two sockets bind the same port when SO_REUSEADDR is set, so without
    this a second double-click starts a second server that quietly answers half the
    tablet's requests. Keep the returned handle for the life of the process.
    """
    handle = kernel32.CreateMutexW(None, False, name)
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return None
    return handle


# ── the picture ────────────────────────────────────────────────────────────────

GROUND = (0x10, 0x0E, 0x0B)


def _blend(bg, fg, a):
    return tuple(int(round(b + (f - b) * a)) for b, f in zip(bg, fg))


def gauge_pixels(size: int, rgb: tuple) -> bytes:
    """The panel's gauge mark at `size` px, as top-down BGRA.

    Supersampled three ways in each direction, because a 16 px tray icon with hard
    edges looks like a mistake rather than a dial.
    """
    cx = cy = (size - 1) / 2.0
    outer = size * 0.46
    inner = size * 0.30
    needle_len = size * 0.34
    needle_w = size * 0.055
    nx, ny = math.cos(math.radians(-50)), math.sin(math.radians(-50))

    out = bytearray()
    for y in range(size):
        for x in range(size):
            hits_ring = 0
            hits_needle = 0
            for sy in range(3):
                for sx in range(3):
                    px = x + (sx + 0.5) / 3.0 - 0.5
                    py = y + (sy + 0.5) / 3.0 - 0.5
                    dx, dy = px - cx, py - cy
                    r = math.hypot(dx, dy)
                    # the dial: a ring, open at the bottom like the panel's own
                    if inner <= r <= outer and not (dy > 0 and abs(dx) < r * 0.62):
                        hits_ring += 1
                    # the needle: distance to a segment from the centre outwards
                    t = max(0.0, min(needle_len, dx * nx + dy * ny))
                    if math.hypot(dx - nx * t, dy - ny * t) <= needle_w:
                        hits_needle += 1
            ring_a = hits_ring / 9.0
            needle_a = hits_needle / 9.0
            colour = _blend(GROUND, rgb, ring_a)
            colour = _blend(colour, (0xF3, 0xEE, 0xE4), needle_a)
            alpha = int(round(255 * min(1.0, ring_a + needle_a)))
            out += bytes((colour[2], colour[1], colour[0], alpha))
    return bytes(out)


def make_icon(size: int, rgb: tuple) -> int:
    """An HICON, owned by the caller -- destroy it with DestroyIcon."""
    header = BITMAPINFOHEADER()
    header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    header.biWidth = size
    header.biHeight = -size          # negative: rows run top-down
    header.biPlanes = 1
    header.biBitCount = 32
    header.biCompression = BI_RGB

    info = BITMAPINFO()
    info.bmiHeader = header
    bits = ctypes.c_void_p()
    colour = gdi32.CreateDIBSection(None, ctypes.byref(info), DIB_RGB_COLORS,
                                    ctypes.byref(bits), None, 0)
    pixels = gauge_pixels(size, rgb)
    ctypes.memmove(bits, pixels, len(pixels))

    mask = gdi32.CreateBitmap(size, size, 1, 1, None)
    icon_info = ICONINFO(True, 0, 0, mask, colour)
    hicon = user32.CreateIconIndirect(ctypes.byref(icon_info))
    gdi32.DeleteObject(colour)
    gdi32.DeleteObject(mask)
    return hicon


def write_ico(path: str, rgb: tuple, sizes=(16, 32, 48, 256)) -> None:
    """The same drawing as a .ico on disk, for shortcuts and the Start menu."""
    images = []
    for size in sizes:
        top_down = gauge_pixels(size, rgb)
        rows = [top_down[y * size * 4:(y + 1) * size * 4] for y in range(size)]
        xor = b"".join(reversed(rows))                 # .ico stores rows bottom-up
        and_mask = b"\x00" * (((size + 31) // 32) * 4 * size)
        head = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0,
                           len(xor) + len(and_mask), 0, 0, 0, 0)
        images.append(head + xor + and_mask)

    offset = 6 + 16 * len(images)
    out = bytearray(struct.pack("<HHH", 0, 1, len(images)))
    for size, blob in zip(sizes, images):
        out += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32,
                           len(blob), offset)
        offset += len(blob)
    for blob in images:
        out += blob
    with open(path, "wb") as fh:
        fh.write(bytes(out))


# ── the icon in the tray ───────────────────────────────────────────────────────

class TrayIcon:
    """One tray icon with a right-click menu, plus a once-a-second tick.

    `build_menu` is asked for a fresh list of (id, label, flags) every time the menu
    opens, so items can appear checked or greyed according to what is happening.
    A `None` item draws a separator, and an item whose id is a list instead of a
    number becomes a submenu holding those items, nested as deeply as you like.
    """

    def __init__(self, title: str, on_command: Callable[[int], None],
                 build_menu: Callable[[], list], on_tick: Callable[[], None] = None,
                 on_double_click: Callable[[], None] = None) -> None:
        self.title = title
        self.on_command = on_command
        self.build_menu = build_menu
        self.on_tick = on_tick
        self.on_double_click = on_double_click
        self._icons: dict = {}
        self._current = None
        self._proc = WNDPROC(self._wndproc)
        self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")

        instance = kernel32.GetModuleHandleW(None)
        cls = WNDCLASSW()
        cls.lpfnWndProc = self._proc
        cls.hInstance = instance
        cls.lpszClassName = "RigDeckTray"
        if not user32.RegisterClassW(ctypes.byref(cls)):
            raise ctypes.WinError(ctypes.get_last_error())
        self._cls = cls   # keep it alive; the class holds our callback

        self.hwnd = user32.CreateWindowExW(0, "RigDeckTray", title, 0,
                                           0, 0, 0, 0, None, None, instance, None)
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())

        self._data = NOTIFYICONDATAW()
        self._data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        self._data.hWnd = self.hwnd
        self._data.uID = 1
        self._data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        self._data.uCallbackMessage = WM_TRAY
        self._data.hIcon = self._icon_for((0x8C, 0x83, 0x78))
        self._data.szTip = title
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._data))

        user32.SetTimer(self.hwnd, 1, 1000, None)

    def _icon_for(self, rgb: tuple) -> int:
        if rgb not in self._icons:
            self._icons[rgb] = make_icon(32, rgb)
        self._current = rgb
        return self._icons[rgb]

    def update(self, rgb: tuple, tip: str) -> None:
        self._data.hIcon = self._icon_for(rgb)
        self._data.szTip = tip[:127]
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._data))

    def notify(self, title: str, text: str) -> None:
        """A balloon. Windows 11 files new tray icons away under the chevron, so without
        this the app looks like it did not start at all."""
        self._data.uFlags |= NIF_INFO
        self._data.szInfoTitle = title[:63]
        self._data.szInfo = text[:255]
        self._data.dwInfoFlags = NIIF_INFO
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._data))
        # Leaving the flag set would re-fire the balloon on every status change.
        self._data.uFlags &= ~NIF_INFO

    def _build(self, items: list):
        # DestroyMenu on the popup takes its submenus with it, so the handles
        # appended here need no separate bookkeeping.
        menu = user32.CreatePopupMenu()
        for item in items:
            if item is None:
                user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
                continue
            ident, label, flags = item
            if isinstance(ident, list):
                user32.AppendMenuW(menu, MF_POPUP | flags, self._build(ident), label)
            else:
                user32.AppendMenuW(menu, MF_STRING | flags, ident, label)
        return menu

    def _show_menu(self) -> None:
        menu = self._build(self.build_menu())
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        # Without this the menu refuses to close when you click elsewhere.
        user32.SetForegroundWindow(self.hwnd)
        chosen = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD,
                                       point.x, point.y, 0, self.hwnd, None)
        user32.DestroyMenu(menu)
        if chosen:
            self.on_command(chosen)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAY:
            if lparam == WM_RBUTTONUP:
                self._show_menu()
            elif lparam == WM_LBUTTONDBLCLK and self.on_double_click:
                self.on_double_click()
            return 0
        if msg == WM_TIMER and self.on_tick:
            self.on_tick()
            return 0
        if msg == WM_COMMAND:
            self.on_command(wparam & 0xFFFF)
            return 0
        if msg == self._taskbar_created:
            # Explorer restarted and took the tray with it.
            shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._data))
            return 0
        if msg in (WM_CLOSE, WM_DESTROY):
            self.remove()
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def remove(self) -> None:
        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._data))
        for icon in self._icons.values():
            user32.DestroyIcon(icon)
        self._icons.clear()

    def quit(self) -> None:
        user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    def loop(self) -> None:
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
