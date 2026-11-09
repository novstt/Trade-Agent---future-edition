from datetime import datetime, timezone
from decimal import Decimal

from trade_agent.core.models import BoundingBox, PriceReading, ValidationStatus
from trade_agent.market import MarketPriceExtractor
from trade_agent.recognition.engine import OcrToken
from trade_agent.recognition.prices import RecognitionResult


def reading(value: str, x: int, y: int) -> PriceReading:
    return PriceReading(value, Decimal(value), BoundingBox(x, y, 50, 20), 96, datetime.now(timezone.utc), ValidationStatus.VALID)


def test_request_price_is_bound_to_nearby_order_button() -> None:
    request = reading("19.93", 790, 70)
    listings = [reading(f"{20 + index}.00", 790, 200 + index * 40) for index in range(3)]
    result = RecognitionResult(
        readings=(request, *listings), regions=(), rows=(), ocr_available=True,
        tokens=(OcrToken("ЗАКАЗАТЬ", 95, BoundingBox(858, 63, 120, 30)),),
    )

    detected_request, detected_listings = MarketPriceExtractor().extract(result, 1000)

    assert detected_request is request
    assert detected_listings == listings


def test_extraction_retains_positional_fallback_without_order_button() -> None:
    first, second = reading("20.00", 790, 70), reading("21.00", 790, 200)
    result = RecognitionResult(readings=(first, second), regions=(), rows=(), ocr_available=True)

    request, listings = MarketPriceExtractor().extract(result, 1000)

    assert request is first
    assert listings == [second]
