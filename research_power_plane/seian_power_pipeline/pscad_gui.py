"""Windows helpers for locating and foregrounding the real PSCAD editor."""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PscadWindow:
    handle: int
    title: str
    left: int
    top: int
    right: int
    bottom: int


def find_pscad_pid(port: int) -> int:
    """Return the PSCAD process listening on the supplied automation port."""

    import psutil

    port_argument = f"/port:{port}"
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = str(process.info.get("name", "")).lower()
            command = [str(value) for value in (process.info.get("cmdline") or [])]
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
        if name == "pscad.exe" and port_argument in command:
            return int(process.info["pid"])
    return 0


def find_pscad_window(pid: int) -> PscadWindow | None:
    """Find PSCAD's visible, titled, full-size top-level editor window."""

    if os.name != "nt" or pid <= 0:
        return None

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    matches: list[PscadWindow] = []

    class Rect(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(Rect)]
    user32.EnumWindows.argtypes = [enum_proc, wintypes.LPARAM]

    @enum_proc
    def visit(window: int, _context: int) -> bool:
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(process_id))
        if process_id.value != pid or not user32.IsWindowVisible(window):
            return True

        title_length = user32.GetWindowTextLengthW(window)
        if title_length <= 0:
            return True
        title_buffer = ctypes.create_unicode_buffer(title_length + 1)
        user32.GetWindowTextW(window, title_buffer, title_length + 1)
        title = title_buffer.value.strip()
        if not title.lower().startswith("pscad "):
            return True

        rect = Rect()
        if not user32.GetWindowRect(window, ctypes.byref(rect)):
            return True
        if not user32.IsIconic(window) and (
            rect.right - rect.left < 300 or rect.bottom - rect.top < 200
        ):
            return True
        matches.append(
            PscadWindow(
                handle=int(window),
                title=title,
                left=rect.left,
                top=rect.top,
                right=rect.right,
                bottom=rect.bottom,
            )
        )
        return True

    user32.EnumWindows(visit, 0)
    return matches[0] if matches else None


def wait_for_pscad_window(pid: int, *, timeout_s: float = 30.0) -> PscadWindow | None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() <= deadline:
        window = find_pscad_window(pid)
        if window is not None:
            return window
        time.sleep(0.25)
    return None


def show_pscad_window(pid: int) -> bool:
    """Restore and foreground PSCAD's main editor when it exists."""

    window = find_pscad_window(pid)
    if window is None:
        return False

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    handle = wintypes.HWND(window.handle)
    user32.ShowWindow(handle, 9)  # SW_RESTORE, including minimized editor windows.
    window = find_pscad_window(pid) or window

    virtual_left = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
    virtual_top = user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
    virtual_right = virtual_left + user32.GetSystemMetrics(78)
    virtual_bottom = virtual_top + user32.GetSystemMetrics(79)
    is_offscreen = (
        window.right <= virtual_left
        or window.left >= virtual_right
        or window.bottom <= virtual_top
        or window.top >= virtual_bottom
    )
    if is_offscreen:
        width = min(1600, max(900, virtual_right - virtual_left))
        height = min(1000, max(650, virtual_bottom - virtual_top))
        user32.SetWindowPos(handle, 0, 20, 20, width, height, 0x0040)

    user32.SetForegroundWindow(handle)
    return True
