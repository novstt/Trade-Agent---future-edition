# Screen capture

`WindowsCaptureProvider` enumerates visible top-level windows using `EnumWindows`. For the selected `HWND`, it attempts `PrintWindow` and falls back to `BitBlt` of the window DC. A failure, minimized target, invalid handle, or zero-size output is reported as an error; no placeholder image is created.

The monitor shows title, handle, resolution, FPS and the last successful frame. It runs in a `QThread` and can save the last actual frame. `WindowsGraphicsCaptureProvider` is reserved as a future native provider and implements the same contract.

