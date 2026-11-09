from __future__ import annotations

from typing import Iterable, Optional

from trade_agent.core.models import MarketSnapshot, PriceReading


class MarketAnalyzer:
    """Keeps market extraction separate from the profit calculation."""

    LISTING_COUNT = 10

    def create_snapshot(
        self,
        item_name: str,
        request_price: Optional[PriceReading],
        listing_prices: Iterable[PriceReading],
    ) -> MarketSnapshot:
        # First ten screen-order values are intentionally preserved, including Cancel listings.
        return MarketSnapshot(item_name=item_name, request_price=request_price, listing_prices=tuple(listing_prices)[:self.LISTING_COUNT])

