# OCR and regions

Tesseract is used when the local executable is available; it has a lightweight Python bridge, stable Windows packaging, and word confidence/boxes. PaddleOCR remains a compatible future engine option when a model runtime is justified. `TesseractOcrEngine` uses a whitelist suitable for numeric values and accepts `G`, commas and decimal points.

OpenCV first creates non-fixed candidate boxes via grayscale normalization, adaptive thresholding, morphological grouping and contour filtering. OCR output is then normalised to a Decimal, attached to a bounding box, confidence, timestamp and one of `VALID`, `LOW_CONFIDENCE`, `INVALID`, `MISSING`, or `STALE`.
