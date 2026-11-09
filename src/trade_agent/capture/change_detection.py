from __future__ import annotations

import hashlib

import numpy as np
from PIL import Image


class MarketFrameGate:
    """Lets OCR through only when the bright price text area has actually changed.

    The game view itself can animate (background, cursor, avatars), while the request
    and listing values live in the right-side price column.  Comparing only bright
    pixels from that column avoids rerunning local OCR and rewriting the UI for those
    unrelated visual changes.
    """

    def __init__(self) -> None:
        self._last_signature: bytes | None = None

    @staticmethod
    def signature(image: Image.Image) -> bytes:
        width, height = image.size
        left, right = int(width * 0.60), int(width * 0.87)
        top, bottom = int(height * 0.04), int(height * 0.96)
        price_area = image.convert("L").crop((left, top, max(left + 1, right), max(top + 1, bottom)))
        # Price glyphs are bright; dark/animated marketplace artwork is intentionally ignored.
        bright_pixels = np.asarray(price_area, dtype=np.uint8) >= 150
        return hashlib.blake2b(np.packbits(bright_pixels).tobytes(), digest_size=16).digest()

    def has_changed(self, image: Image.Image) -> bool:
        current = self.signature(image)
        if current == self._last_signature:
            return False
        self._last_signature = current
        return True
