from datetime import datetime, timezone
from decimal import Decimal

from PIL import Image, ImageChops

from trade_agent.core.models import BoundingBox, PriceReading, ValidationStatus
from trade_agent.interface.main_window import MainWindow
from trade_agent.recognition.prices import RecognitionResult
from trade_agent.recognition.regions import DetectedRegion


def test_monitor_annotation_draws_only_recognized_price_boxes() -> None:
    image = Image.new("RGBA", (100, 100), (10, 20, 30, 255))
    result = RecognitionResult(
        readings=(),
        regions=(DetectedRegion(BoundingBox(5, 5, 70, 50), 0.9),),
        rows=(),
        ocr_available=True,
    )

    annotated = MainWindow._annotate(image, result)

    assert ImageChops.difference(image, annotated).getbbox() is None


def test_monitor_annotation_marks_a_price_box() -> None:
    image = Image.new("RGBA", (100, 100), (10, 20, 30, 255))
    price = PriceReading(
        "20.00", Decimal("20.00"), BoundingBox(40, 40, 30, 15), 99,
        datetime.now(timezone.utc), ValidationStatus.VALID,
    )
    result = RecognitionResult((price,), (), (), True)

    annotated = MainWindow._annotate(image, result)

    assert annotated.getpixel((40, 40)) != image.getpixel((40, 40))
