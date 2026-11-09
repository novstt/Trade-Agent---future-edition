from __future__ import annotations

from trade_agent.core.models import PriceReading
from trade_agent.recognition.prices import RecognitionResult


class MarketPriceExtractor:
    """Infers a price column relative to the captured frame, not fixed reference coordinates."""

    def extract(self, result: RecognitionResult, frame_width: int) -> tuple[PriceReading | None, list[PriceReading]]:
        # Prices in the provided market layout occupy a common right-side column. Infer it from the
        # actual frame width and then retain reading order; the top price is the purchase request.
        candidates = [
            value for value in result.readings
            if value.bounding_box is not None and value.bounding_box.x >= frame_width * 0.58
        ]
        candidates.sort(key=lambda value: (value.bounding_box.y if value.bounding_box else 0,
                                           value.bounding_box.x if value.bounding_box else 0))
        return (candidates[0] if candidates else None, candidates[1:11])
