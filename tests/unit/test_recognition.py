from datetime import datetime, timezone
from decimal import Decimal

from PIL import Image

from trade_agent.core.models import BoundingBox, ValidationStatus
from trade_agent.recognition.engine import OcrToken
from trade_agent.recognition.prices import PriceRecognizer


class FakeEngine:
    is_available = True

    def __init__(self) -> None:
        self.crop_sizes = []

    def read_tokens(self, image):
        self.crop_sizes.append(image.size)
        if len(self.crop_sizes) == 1:
            return [OcrToken("20,00G", 92, BoundingBox(10, 10, 50, 20))]
        return [
            OcrToken("21.37", 40, BoundingBox(10, 10, 50, 20)),
            OcrToken("not-a-price", 99, BoundingBox(0, 0, 1, 1)),
        ]


def test_price_parser_normalizes_decimal_separator_and_currency() -> None:
    assert PriceRecognizer.parse_price("20,00 G") == Decimal("20.00")
    assert PriceRecognizer.parse_price("no price") is None
    assert PriceRecognizer.is_ocr_price("20,00G")
    assert PriceRecognizer.is_ocr_price("20.69")
    assert not PriceRecognizer.is_ocr_price("1731")
    assert not PriceRecognizer.is_ocr_price("20796")


def test_recognizer_keeps_low_confidence_separate_from_valid() -> None:
    engine = FakeEngine()
    result = PriceRecognizer(engine).recognize(Image.new("RGB", (800, 600)), datetime.now(timezone.utc))
    assert len(result.readings) == 2
    assert result.readings[0].validation_status is ValidationStatus.VALID
    assert result.readings[1].validation_status is ValidationStatus.LOW_CONFIDENCE
    # OCR receives only the request-price strip and the first-ten-lots price strip.
    assert engine.crop_sizes == [(88, 51), (88, 371)]
    assert result.readings[0].bounding_box == BoundingBox(586, 61, 50, 20)
    assert result.readings[1].bounding_box == BoundingBox(586, 130, 50, 20)
