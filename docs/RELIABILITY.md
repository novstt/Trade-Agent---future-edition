# Reliability

`ReliabilityManager` uses bounded consecutive-error counts, time-based staleness, and explicit states: `NORMAL`, `DEGRADED`, `RECOVERY`, and `SAFE_STOP`. The capture worker stops on request and emits errors rather than retrying indefinitely. F9 invokes the app emergency stop: capture is stopped, the session is persisted and the active sticker streak is reset.

