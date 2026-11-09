from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from trade_agent.core.models import CalculationResult


class OrderState(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


class InventoryState(str, Enum):
    EXPECTED = "EXPECTED"
    HELD = "HELD"
    LISTED = "LISTED"
    SOLD = "SOLD"


@dataclass(frozen=True)
class TurnoverScenario:
    target_quantity: int
    maximum_loss_per_item: Decimal
    eligible: bool
    projected_total: Decimal | None
    cycle_note: str


class SkinTurnoverService:
    def simulate(self, result: CalculationResult, target_quantity: int, maximum_loss: Decimal) -> TurnoverScenario:
        return TurnoverScenario(
            target_quantity=target_quantity,
            maximum_loss_per_item=maximum_loss,
            eligible=result.eligible,
            projected_total=result.total_result,
            cycle_note="Ready to place orders" if result.eligible else "Hold: loss threshold exceeded or snapshot incomplete",
        )

