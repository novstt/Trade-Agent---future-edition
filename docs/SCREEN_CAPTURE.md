# Screen capture

`WindowsCaptureProvider` enumerates visible top-level windows using `EnumWindows`. For the selected `HWND`, it attempts `PrintWindow` and falls back to `BitBlt` of the window DC. A failure, minimized target, invalid handle, or zero-size output is reported as an error; no placeholder image is created.

The Monitor supports two source routes: choose an enumerated window and use **Get**, or paste a decimal/hexadecimal (`0x…`) HWND and use **Capture by HWND**. Both routes call `get_window_info()` to validate the live handle and construct the exact `WindowInfo` passed to the capture worker.

The monitor shows title, handle, resolution, FPS and the last successful frame. It runs in a `QThread` and can save the last actual frame. `WindowsGraphicsCaptureProvider` is reserved as a future native provider and implements the same contract.
