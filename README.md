# TRADE AGENT

Local Windows desktop application for analysing a visible market screen. It captures a user-selected top-level window, detects regions locally, reads price candidates through a replaceable OCR engine, validates a ten-listing market snapshot, and calculates profit or loss using `Decimal`.

No image is uploaded and no API key is required. The provided market screenshots are retained under `assets/reference/` as visual test fixtures, not hard-coded coordinate templates.

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m trade_agent
```

Tesseract is selected automatically from `C:\Program Files\Tesseract-OCR\tesseract.exe` when present, then from `PATH`. If it is unavailable, **Settings** shows a small warning and the application continues without OCR. Install [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) locally for production OCR. The engine is deliberately replaceable through `OcrEngine`.

The app starts directly in a card-style, resizable **Analyzer** window (about `430 × 360` on first launch). Its six top tabs are Analyzer, Sell Menu, Turnover, Monitor, History, and Settings. The window remembers its last size, position, and always-on-top preference; F9 remains the emergency stop.

## What is implemented

- Windows top-level-window enumeration and real selected-window GDI capture, with a live worker-thread preview, direct decimal or `0x` HWND resolution, DPI-aware sizing, recovery status and F9 global stop.
- OpenCV region detection, Tesseract word/number OCR, confidence and coordinate reporting, repeated-frame stale detection, and explicit validation states.
- Decimal market logic that requires ten valid listing prices before an average is considered complete. Existing `Cancel` listings are included when their prices are recognised.
- Separate local inventory/sticker workflow, de-duplication and session streak tracking.
- SQLite schema migrations, history, compact overlay, and a dark compact PySide6 UI with persistent top navigation.

## Operational limits

The capture backend uses Win32 GDI (`PrintWindow` first, then `BitBlt`) because it is a dependency-free Windows fallback. Some protected, minimized, or hardware-rendered windows can deny GDI capture; the monitor reports this rather than presenting a synthetic frame. Windows Graphics Capture can be added as a provider without changing the UI or recognition pipeline.

Unit tests do not claim to exercise a real external window. The live capture test is an opt-in integration test; use **Screen Capture Monitor** to verify the selected application on the target PC.

## Build

```powershell
python -m pip install -e ".[build]"
pyinstaller --noconfirm --windowed --name TradeAgent --paths src src/trade_agent/__main__.py
```

See [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md) and [docs/TEST_PLAN.md](docs/TEST_PLAN.md).
