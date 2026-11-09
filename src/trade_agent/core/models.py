from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ValidationStatus(str, Enum):
    VALID = "VALID"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    INVALID = "INVALID"
    MISSING = "MISSING"
    STALE = "STALE"


class ReliabilityState(str, Enum):
    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"
    RECOVERY = "RECOVERY"
    SAFE_STOP = "SAFE_STOP"


@dataclass(frozen=True)
class BoundingBox:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height


@dataclass(frozen=True)
class PriceReading:
    raw_text: str
    parsed_value: Optional[Decimal]
    bounding_box: Optional[BoundingBox]
    confidence: float
    timestamp: datetime = field(default_factory=utc_now)
    validation_status: ValidationStatus = ValidationStatus.MISSING


@dataclass(frozen=True)
class MarketSnapshot:
    item_name: str
    request_price: Optional[PriceReading]
    listing_prices: tuple[PriceReading, ...]
    captured_at: datetime = field(default_factory=utc_now)

    @property
    def valid_listing_prices(self) -> tuple[PriceReading, ...]:
        return tuple(
            reading
            for reading in self.listing_prices
            if reading.validation_status is ValidationStatus.VALID and reading.parsed_value is not None
        )

    @property
    def is_complete(self) -> bool:
        return len(self.valid_listing_prices) == 10


@dataclass(frozen=True)
class CalculationResult:
    average_price: Optional[Decimal]
    net_sale_price: Optional[Decimal]
    per_item_result: Optional[Decimal]
    total_result: Optional[Decimal]
    eligible: bool
    reason: str


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    width: int
    height: int


@dataclass(frozen=True)
class CaptureFrame:
    image: object
    source: WindowInfo
    timestamp: datetime = field(default_factory=utc_now)

