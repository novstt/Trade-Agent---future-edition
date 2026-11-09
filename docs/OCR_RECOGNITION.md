# OCR and regions

Tesseract is used when the local executable is available; it has a lightweight Python bridge, stable Windows packaging, and word confidence/boxes. PaddleOCR remains a compatible future engine option when a model runtime is justified. `TesseractOcrEngine` uses a numeric whitelist: digits, commas and decimal points only.

For the market screen, OCR receives only two scale-independent crops: the request-price strip above and the vertical strip of the first ten listing prices. The strip is derived from the left side of the repeated light-blue Buy-button column, with a relative fallback when the buttons are unavailable. Emulator chrome, item names, avatars, buttons, offer totals and the activity feed are never sent to OCR. The extractor accepts an optional recognised `ЗАКАЗАТЬ` anchor when supplied by another engine, but the request-price crop is already structurally separate from the listing-price crop.

OpenCV first creates non-fixed candidate boxes via grayscale normalization, adaptive thresholding, morphological grouping and contour filtering. OCR output is then normalised to a Decimal, attached to a bounding box, confidence, timestamp and one of `VALID`, `LOW_CONFIDENCE`, `INVALID`, `MISSING`, or `STALE`.
