# Architecture

| Layer | Responsibility |
| --- | --- |
| `capture` | Enumerate Windows, obtain real pixels and run a capture worker. |
| `recognition` | Detect candidate text regions and convert locally OCR'd tokens to validated price readings. |
| `market`, `calculator` | Build complete snapshots and calculate precise business results. |
| `inventory` | Analyse Sell Menu cards only, classify sticker items, and manage one-session streaks. |
| `turnover` | Model order states and simulate a target quantity. |
| `storage`, `reliability` | Migrations/history and stale/error/recovery states. |
| `interface` | PySide6 presentation, overlay and global emergency stop. |

Providers and engines are Protocol-compatible, so Windows Graphics Capture or PaddleOCR can be introduced independently later.
