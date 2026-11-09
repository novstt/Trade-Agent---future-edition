from __future__ import annotations

from decimal import Decimal

from trade_agent.core.models import CalculationResult, MarketSnapshot, ValidationStatus


DEFAULT_COMMISSION = Decimal("0.20")


class ProfitEngine:
    """Pure business logic. It never rounds an internal Decimal."""

    def calculate(
        self,
        snapshot: MarketSnapshot,
        target_quantity: int,
        maximum_loss_per_item: Decimal,
        commission: Decimal = DEFAULT_COMMISSION,
    ) -> CalculationResult:
        if target_quantity < 1:
            return CalculationResult(None, None, None, None, False, "Целевое количество должно быть не меньше 1.")
        if maximum_loss_per_item < 0:
            return CalculationResult(None, None, None, None, False, "Максимальный убыток на предмет не может быть отрицательным.")
        if not Decimal("0") <= commission < Decimal("1"):
            return CalculationResult(None, None, None, None, False, "Комиссия должна быть от 0% до 100%.")
        if snapshot.request_price is None or snapshot.request_price.validation_status is not ValidationStatus.VALID:
            return CalculationResult(None, None, None, None, False, "Цена запроса отсутствует или недействительна.")
        if snapshot.request_price.parsed_value is None:
            return CalculationResult(None, None, None, None, False, "Не удалось распознать цену запроса.")
        if not snapshot.is_complete:
            return CalculationResult(None, None, None, None, False, "Снимок неполный: требуется ровно 10 достоверных цен.")

        values = [reading.parsed_value for reading in snapshot.valid_listing_prices]
        average = sum(values, Decimal("0")) / Decimal("10")
        net_sale = average * (Decimal("1") - commission)
        per_item = net_sale - snapshot.request_price.parsed_value
        total = per_item * Decimal(target_quantity)
        eligible = per_item >= -maximum_loss_per_item
        reason = "Подходит" if eligible else "Превышен максимальный убыток на предмет."
        return CalculationResult(average, net_sale, per_item, total, eligible, reason)
