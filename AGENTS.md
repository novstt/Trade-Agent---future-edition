# Contributor notes

- Keep all image processing and OCR local; do not add cloud OCR or secrets.
- Market analysis only consumes `PriceReading` objects. Sticker detection belongs only to the Sell Menu workflow.
- Preserve `Decimal` values internally. Round only in UI formatting.
- A market snapshot is complete only with exactly ten valid listing values; do not manufacture an average from fewer values.
- Test business logic before changing UI code. Hardware/window capture must be verified manually on Windows and reported honestly.
- Do not commit `data/`, local logs, generated executables, tokens, or user captures.

