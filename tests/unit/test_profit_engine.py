from decimal import Decimal

from trade_agent.calculator import ProfitEngine
from trade_agent.core.models import MarketSnapshot, PriceReading, ValidationStatus


def reading(value: str) -> PriceReading:
    return PriceReading(value, Decimal(value), None, 99, validation_status=ValidationStatus.VALID)


def snapshot(request: str = "20.00", listings=None) -> MarketSnapshot:
    return MarketSnapshot("G22 Briar", reading(request), tuple(listings or [reading("25.00") for _ in range(10)]))


def test_complete_snapshot_uses_decimal_and_commission() -> None:
    result = ProfitEngine().calculate(snapshot(), 20, Decimal("5.00"))
    assert result.average_price == Decimal("25.00")
    assert result.net_sale_price == Decimal("20.0000")
    assert result.per_item_result == Decimal("0.0000")
    assert result.total_result == Decimal("0.0000")
    assert result.eligible is True


def test_incomplete_snapshot_has_no_average() -> None:
    result = ProfitEngine().calculate(snapshot(listings=[reading("25.00")] * 9), 1, Decimal("5.00"))
    assert result.average_price is None
    assert result.eligible is False
    assert "непол" in result.reason.lower()


def test_per_item_loss_threshold_is_inclusive() -> None:
    listings = [reading("18.75") for _ in range(10)]  # net 15.00 against a request of 20.00
    allowed = ProfitEngine().calculate(snapshot(listings=listings), 100, Decimal("5.00"))
    rejected = ProfitEngine().calculate(snapshot(listings=listings), 100, Decimal("4.99"))
    assert allowed.per_item_result == Decimal("-5.0000")
    assert allowed.eligible is True
    assert rejected.eligible is False
