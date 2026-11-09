from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

import numpy as np
from PIL import Image

from trade_agent.core.models import BoundingBox, PriceReading, ValidationStatus
from trade_agent.recognition.engine import OcrEngine, OcrToken
from trade_agent.recognition.regions import DetectedRegion, RegionDetector


PRICE_PATTERN = re.compile(r"(?<![\d.])([0-9]{1,7}(?:[.,][0-9]{1,4})?)(?![\d.])")


@dataclass(frozen=True)
class RecognitionResult:
    readings: tuple[PriceReading, ...]
    regions: tuple[DetectedRegion, ...]
    rows: tuple[tuple[DetectedRegion, ...], ...]
    ocr_available: bool
    error: Optional[str] = None


class PriceRecognizer:
    def __init__(self, engine: OcrEngine, region_detector: Optional[RegionDetector] = None, minimum_confidence: float = 55.0) -> None:
        self.engine = engine
        self.region_detector = region_detector or RegionDetector()
        self.minimum_confidence = minimum_confidence
        self._last_signature: Optional[str] = None
        self._last_change_at: Optional[datetime] = None

    @staticmethod
    def parse_price(raw_text: str) -> Optional[Decimal]:
        cleaned = raw_text.replace(" ", "").replace("G", "").replace("g", "")
        match = PRICE_PATTERN.search(cleaned)
        if not match:
            return None
        number = match.group(1).replace(",", ".")
        try:
            value = Decimal(number)
        except InvalidOperation:
            return None
        return value if value >= 0 else None

    def recognize(self, image: Image.Image, timestamp: Optional[datetime] = None) -> RecognitionResult:
        timestamp = timestamp or datetime.now(timezone.utc)
        regions = self.region_detector.detect(image)
        rows = self.region_detector.group_rows(regions)
        signature = hashlib.blake2b(np.asarray(image.convert("L")).tobytes(), digest_size=12).hexdigest()
        if signature != self._last_signature:
            self._last_signature, self._last_change_at = signature, timestamp
        is_stale = self._last_change_at is not None and (timestamp - self._last_change_at).total_seconds() > 4

        if not self.engine.is_available:
            return RecognitionResult((), tuple(regions), tuple(tuple(row) for row in rows), False, "Local OCR engine unavailable.")
        try:
            tokens = self.engine.read_tokens(image)
        except Exception as exc:
            return RecognitionResult((), tuple(regions), tuple(tuple(row) for row in rows), True, str(exc))

        readings = tuple(self._reading_from_token(token, timestamp, is_stale) for token in tokens if self.parse_price(token.text) is not None)
        return RecognitionResult(readings, tuple(regions), tuple(tuple(row) for row in rows), True)

    def _reading_from_token(self, token: OcrToken, timestamp: datetime, is_stale: bool) -> PriceReading:
        value = self.parse_price(token.text)
        if value is None:
            status = ValidationStatus.INVALID
        elif is_stale:
            status = ValidationStatus.STALE
        elif token.confidence < self.minimum_confidence:
            status = ValidationStatus.LOW_CONFIDENCE
        else:
            status = ValidationStatus.VALID
        return PriceReading(token.text, value, token.bounding_box, token.confidence, timestamp, status)

