from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

import cv2
import numpy as np
from PIL import Image

from trade_agent.core.models import BoundingBox


@dataclass(frozen=True)
class InventoryItem:
    name: str
    fingerprint: str
    has_sticker: bool
    confidence: float
    bounding_box: BoundingBox | None = None


class SellMenuDetector:
    """Finds repeated horizontal inventory-card candidates only in the explicit Sell Menu flow."""

    def detect_cards(self, image: Image.Image) -> list[BoundingBox]:
        frame = np.asarray(image.convert("RGB"))
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny(gray, 55, 130)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 5))
        joined = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(joined, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        cards: list[BoundingBox] = []
        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            if width >= frame.shape[1] * 0.12 and height >= 36 and width / max(height, 1) >= 1.4:
                cards.append(BoundingBox(x, y, width, height))
        return sorted(cards, key=lambda card: (card.y, card.x))


class StickerDetector:
    """Local visual heuristic for compact saturated sticker-like connected components."""

    def detect(self, card: Image.Image) -> tuple[bool, float]:
        frame = np.asarray(card.convert("RGB"))
        if frame.size == 0:
            return False, 0.0
        hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
        saturation = hsv[:, :, 1]
        value = hsv[:, :, 2]
        mask = cv2.inRange(hsv, (0, 105, 90), (179, 255, 255))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
        qualifying = [row[cv2.CC_STAT_AREA] for row in stats[1:count] if 25 <= row[cv2.CC_STAT_AREA] <= frame.shape[0] * frame.shape[1] * 0.20]
        colour_fraction = float(np.mean((saturation > 105) & (value > 90)))
        confidence = min(1.0, len(qualifying) * 0.28 + colour_fraction * 3.5)
        return bool(qualifying) and confidence >= 0.35, confidence


class InventoryAnalyzer:
    def __init__(self, detector: StickerDetector | None = None) -> None:
        self.detector = detector or StickerDetector()
        self.started_at = datetime.now(timezone.utc)
        self._seen: set[str] = set()
        self.sticker_items: list[InventoryItem] = []
        self.normal_items: list[InventoryItem] = []

    @staticmethod
    def fingerprint(card: Image.Image) -> str:
        reduced = card.convert("L").resize((16, 16))
        return hashlib.blake2b(np.asarray(reduced).tobytes(), digest_size=12).hexdigest()

    @property
    def current_streak(self) -> int:
        return len(self.sticker_items)

    def analyse_card(self, name: str, card: Image.Image, bounding_box: BoundingBox | None = None) -> InventoryItem | None:
        fingerprint = self.fingerprint(card)
        if fingerprint in self._seen:
            return None
        self._seen.add(fingerprint)
        has_sticker, confidence = self.detector.detect(card)
        item = InventoryItem(name, fingerprint, has_sticker, confidence, bounding_box)
        (self.sticker_items if has_sticker else self.normal_items).append(item)
        return item

    def reset_session(self) -> tuple[int, int, datetime]:
        summary = (len(self.sticker_items), len(self.normal_items), self.started_at)
        self.started_at = datetime.now(timezone.utc)
        self._seen.clear()
        self.sticker_items.clear()
        self.normal_items.clear()
        return summary
