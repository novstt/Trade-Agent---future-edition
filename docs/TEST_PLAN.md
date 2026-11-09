# Test plan

Automated tests cover decimal precision, complete and incomplete ten-price snapshots, loss eligibility, OCR text normalisation, database migrations, sticker de-duplication and stale state logic.

Manual Windows integration checks are required for: selecting a real external window, live preview, DPI changes, protected/minimized-window failure behavior, F9 hotkey behaviour while another window is active, and actual installed-Tesseract recognition. The reference screens in `assets/reference/` support repeatable OCR/region checks, but are not a substitute for real capture.
