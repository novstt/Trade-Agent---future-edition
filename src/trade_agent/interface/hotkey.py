from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND), ("message", wintypes.UINT), ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM), ("time", wintypes.DWORD), ("pt", wintypes.POINT),
    ]


class GlobalF9Hotkey(QObject, QAbstractNativeEventFilter):
    activated = Signal()
    HOTKEY_ID = 0x5441
    WM_HOTKEY = 0x0312
    VK_F9 = 0x78

    def __init__(self) -> None:
        super().__init__()
        self._registered = False

    def install(self, application) -> bool:
        if os.name != "nt":
            return False
        self._registered = bool(ctypes.windll.user32.RegisterHotKey(None, self.HOTKEY_ID, 0, self.VK_F9))
        if self._registered:
            application.installNativeEventFilter(self)
        return self._registered

    def uninstall(self, application) -> None:
        if self._registered and os.name == "nt":
            application.removeNativeEventFilter(self)
            ctypes.windll.user32.UnregisterHotKey(None, self.HOTKEY_ID)
        self._registered = False

    def nativeEventFilter(self, event_type, message):  # Qt native event contract
        if event_type == b"windows_generic_MSG":
            try:
                native = _MSG.from_address(int(message))
                if native.message == self.WM_HOTKEY and native.wParam == self.HOTKEY_ID:
                    self.activated.emit()
                    return True, 0
            except (TypeError, ValueError):
                pass
        return False, 0

