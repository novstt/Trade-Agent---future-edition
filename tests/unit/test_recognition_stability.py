from datetime import datetime, timezone
from decimal import Decimal

from trade_agent.core.models import PriceReading, ValidationStatus
from trade_agent.interface.main_window import AnalyzerPage
from trade_agent.storage import Database


def _reading(value: str) -> PriceReading:
    return PriceReading(value, Decimal(value), None, 99, datetime.now(timezone.utc), ValidationStatus.VALID)


def test_same_recognized_prices_do_not_recalculate_or_write_history(qtbot, tmp_path) -> None:
    database = Database(tmp_path / "trade.sqlite3")
    page = AnalyzerPage(database)
    qtbot.addWidget(page)
    updated = []
    page.calculation_updated.connect(lambda *_: updated.append(True))
    request = _reading("17.31")
    listings = [_reading(f"{20 + index / 100:.2f}") for index in range(10)]

    assert page.apply_recognition(request, listings, "OCR готов")
    history_count = len(database.recent_history(100))
    assert not page.apply_recognition(request, listings, "OCR готов")

    assert len(updated) == 1
    assert len(database.recent_history(100)) == history_count
    page.close()
    database.close()


def test_incomplete_or_low_confidence_ocr_cannot_replace_confirmed_prices(qtbot, tmp_path) -> None:
    database = Database(tmp_path / "trade.sqlite3")
    page = AnalyzerPage(database)
    qtbot.addWidget(page)
    request = _reading("17.31")
    listings = [_reading(f"{20 + index / 100:.2f}") for index in range(10)]
    assert page.apply_recognition(request, listings, "OCR готов")
    history_count = len(database.recent_history(100))

    uncertain = PriceReading(
        "20.53", Decimal("20.53"), None, 37, datetime.now(timezone.utc), ValidationStatus.LOW_CONFIDENCE,
    )
    assert not page.apply_recognition(request, [uncertain, *listings[1:]], "OCR готов")

    assert page.request_price.text() == "17.31"
    assert page.listing_prices[0].text() == "20.00"
    assert len(database.recent_history(100)) == history_count
    page.close()
    database.close()
