from __future__ import annotations

import re

from trade_agent.core.models import PriceReading
from trade_agent.recognition.engine import OcrToken
from trade_agent.recognition.prices import RecognitionResult


class MarketPriceExtractor:
    """Infers a price column relative to the captured frame, not fixed reference coordinates."""

    _ORDER_TEXT = re.compile(r"[^A-ZА-Я0-9]")

    def extract(self, result: RecognitionResult, frame_width: int) -> tuple[PriceReading | None, list[PriceReading]]:
        # Prices occupy a common right-side column. First bind the request price to its nearby
        # `ЗАКАЗАТЬ` control; only use the old positional fallback when the control is absent.
        candidates = [
            value for value in result.readings
            if value.bounding_box is not None and value.bounding_box.x >= frame_width * 0.58
        ]
        candidates.sort(key=lambda value: (value.bounding_box.y if value.bounding_box else 0,
                                           value.bounding_box.x if value.bounding_box else 0))
        request = self._request_next_to_order_button(candidates, result.tokens)
        if request is None:
            request = candidates[0] if candidates else None
        listings = [value for value in candidates if value is not request]
        return request, listings[:10]

    @classmethod
    def _request_next_to_order_button(cls, candidates: list[PriceReading], tokens: tuple[OcrToken, ...]) -> PriceReading | None:
        order_buttons = [token for token in tokens if cls._is_order_button(token)]
        pairs: list[tuple[int, PriceReading]] = []
        for button in order_buttons:
            button_box = button.bounding_box
            button_center = button_box.y + button_box.height / 2
            for value in candidates:
                if value.bounding_box is None or value.parsed_value is None:
                    continue
                price_box = value.bounding_box
                price_center = price_box.y + price_box.height / 2
                horizontal_gap = button_box.x - price_box.right
                vertical_gap = abs(button_center - price_center)
                # A request value is directly left of its button on the same visual row.
                if -8 <= horizontal_gap <= 260 and vertical_gap <= max(button_box.height, price_box.height, 20) * 1.5:
                    pairs.append((max(horizontal_gap, 0) + int(vertical_gap * 8), value))
        return min(pairs, key=lambda pair: pair[0])[1] if pairs else None

    @classmethod
    def _is_order_button(cls, token: OcrToken) -> bool:
        normalized = cls._ORDER_TEXT.sub("", token.text.upper())
        # Tesseract can confuse Cyrillic З with 3 and may output a Latin transliteration.
        return "ЗАКАЗ" in normalized or "3AKA3" in normalized or "ZAKAZ" in normalized
