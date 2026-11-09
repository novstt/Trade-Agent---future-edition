from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic, sleep
from typing import Protocol

from PIL import Image
from PySide6.QtCore import QThread, Signal

from trade_agent.core.models import CaptureFrame, WindowInfo


class CaptureError(RuntimeError):
    pass


class ScreenCaptureProvider(Protocol):
    def enumerate_windows(self) -> list[WindowInfo]: ...
    def capture(self, window: WindowInfo) -> CaptureFrame: ...


if os.name == "nt":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    # ctypes defaults pointer-returning Win32 calls to c_int, which truncates HWND/HDC values on 64-bit Windows.
    user32.GetWindowDC.restype = wintypes.HDC
    user32.ReleaseDC.restype = ctypes.c_int
    user32.PrintWindow.restype = wintypes.BOOL
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsIconic.restype = wintypes.BOOL
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteDC.restype = wintypes.BOOL
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.BitBlt.restype = wintypes.BOOL
    gdi32.GetDIBits.restype = ctypes.c_int

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    PW_RENDERFULLCONTENT = 0x00000002
    SRCCOPY = 0x00CC0020
    DIB_RGB_COLORS = 0


class WindowsCaptureProvider:
    """Dependency-free Win32 capture provider. It always returns actual target pixels or errors."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("WindowsCaptureProvider requires Windows.")
        # Logical pixels are a poor fit for a physical screenshot; this makes the process DPI-aware.
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass

    def enumerate_windows(self) -> list[WindowInfo]:
        windows: list[WindowInfo] = []

        @EnumWindowsProc
        def visitor(hwnd: int, _: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title, len(title))
            rect = wintypes.RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return True
            width, height = rect.right - rect.left, rect.bottom - rect.top
            if width > 1 and height > 1:
                windows.append(WindowInfo(int(hwnd), title.value.strip(), width, height))
            return True

        if not user32.EnumWindows(visitor, 0):
            raise CaptureError(f"EnumWindows failed: {ctypes.get_last_error()}")
        return sorted(windows, key=lambda entry: entry.title.casefold())

    def capture(self, window: WindowInfo) -> CaptureFrame:
        hwnd = wintypes.HWND(window.hwnd)
        if not user32.IsWindow(hwnd):
            raise CaptureError("Selected window no longer exists.")
        if user32.IsIconic(hwnd):
            raise CaptureError("Selected window is minimized; restore it before capture.")
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise CaptureError(f"Could not read selected window size: {ctypes.get_last_error()}")
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width <= 1 or height <= 1:
            raise CaptureError("Selected window has no capturable area.")

        window_dc = user32.GetWindowDC(hwnd)
        if not window_dc:
            raise CaptureError(f"GetWindowDC failed: {ctypes.get_last_error()}")
        mem_dc = bitmap = old = None
        try:
            mem_dc = gdi32.CreateCompatibleDC(window_dc)
            bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
            if not mem_dc or not bitmap:
                raise CaptureError(f"Could not allocate capture bitmap: {ctypes.get_last_error()}")
            old = gdi32.SelectObject(mem_dc, bitmap)
            # Modern windows often render better through PrintWindow. BitBlt is a real-pixel fallback.
            rendered = bool(user32.PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT))
            if not rendered and not gdi32.BitBlt(mem_dc, 0, 0, width, height, window_dc, 0, 0, SRCCOPY):
                raise CaptureError(f"Window capture failed: {ctypes.get_last_error()}")

            info = BITMAPINFO()
            info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            info.bmiHeader.biWidth = width
            info.bmiHeader.biHeight = -height  # top-down image
            info.bmiHeader.biPlanes = 1
            info.bmiHeader.biBitCount = 32
            info.bmiHeader.biCompression = 0
            pixels = (ctypes.c_ubyte * (width * height * 4))()
            rows = gdi32.GetDIBits(mem_dc, bitmap, 0, height, pixels, ctypes.byref(info), DIB_RGB_COLORS)
            if rows != height:
                raise CaptureError(f"Could not read captured pixels: {ctypes.get_last_error()}")
            image = Image.frombuffer("RGBA", (width, height), pixels, "raw", "BGRA", 0, 1).copy()
            actual_window = WindowInfo(window.hwnd, window.title, width, height)
            return CaptureFrame(image=image, source=actual_window, timestamp=datetime.now(timezone.utc))
        finally:
            if old and mem_dc:
                gdi32.SelectObject(mem_dc, old)
            if bitmap:
                gdi32.DeleteObject(bitmap)
            if mem_dc:
                gdi32.DeleteDC(mem_dc)
            user32.ReleaseDC(hwnd, window_dc)


class WindowsGraphicsCaptureProvider:
    """Reserved provider seam for a WinRT Windows Graphics Capture implementation."""

    def enumerate_windows(self) -> list[WindowInfo]:
        return WindowsCaptureProvider().enumerate_windows()

    def capture(self, window: WindowInfo) -> CaptureFrame:
        raise CaptureError("Windows Graphics Capture provider is not installed; select Win32 GDI capture.")


class CaptureWorker(QThread):
    frame_captured = Signal(object)
    capture_error = Signal(str)
    status_changed = Signal(str)
    metrics_changed = Signal(float, object)

    def __init__(self, provider: ScreenCaptureProvider, window: WindowInfo, interval_ms: int = 350) -> None:
        super().__init__()
        self.provider = provider
        self.window = window
        self.interval_seconds = max(interval_ms, 100) / 1000
        self._stopping = False

    def stop(self) -> None:
        self._stopping = True
        self.requestInterruption()

    def run(self) -> None:
        self.status_changed.emit("CAPTURING")
        last_time = monotonic()
        rolling_fps = 0.0
        failures = 0
        while not self._stopping and not self.isInterruptionRequested():
            try:
                frame = self.provider.capture(self.window)
                elapsed = max(monotonic() - last_time, 0.001)
                last_time = monotonic()
                instantaneous = 1 / elapsed
                rolling_fps = instantaneous if rolling_fps == 0 else (rolling_fps * 0.8) + (instantaneous * 0.2)
                failures = 0
                self.frame_captured.emit(frame)
                self.metrics_changed.emit(rolling_fps, frame.timestamp)
            except Exception as exc:
                failures += 1
                self.capture_error.emit(str(exc))
                if failures >= 3:
                    self.status_changed.emit("DEGRADED")
                    break
            sleep(self.interval_seconds)
        self.status_changed.emit("STOPPED")
