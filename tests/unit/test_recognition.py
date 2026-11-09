from datetime import datetime, timezone
from decimal import Decimal

from PIL import Image

from trade_agent.core.models import BoundingBox, ValidationStatus
from trade_agent.recognition.engine import OcrToken
from trade_agent.recognition.prices import PriceRecognizer


class FakeEngine:
    is_available = True

    def read_tokens(self, _image):
        return [
            OcrToken("20,00G", 92, BoundingBox(700, 20, 50, 20)),
            OcrToken("21.37", 40, BoundingBox(700, 80, 50, 20)),
            OcrToken("not-a-price", 99, BoundingBox(0, 0, 1, 1)),
        ]


def test_price_parser_normalizes_decimal_separator_and_currency() -> None:
    assert PriceRecognizer.parse_price("20,00 G") == Decimal("20.00")
    assert PriceRecognizer.parse_price("no price") is None


def test_recognizer_keeps_low_confidence_separate_from_valid() -> None:
    result = PriceRecognizer(FakeEngine()).recognize(Image.new("RGB", (800, 600)), datetime.now(timezone.utc))
    assert len(result.readings) == 2
    assert result.readings[0].validation_status is ValidationStatus.VALID
    assert result.readings[1].validation_status is ValidationStatus.LOW_CONFIDENCE
