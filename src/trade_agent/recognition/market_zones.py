from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

from trade_agent.core.models import BoundingBox


@dataclass(frozen=True)
class PriceZone:
    """A scale-independent OCR crop and its position in the original window."""

    name: str
    bounding_box: BoundingBox


class MarketPriceZones:
    """The only two OCR areas used for the supported market layout.

    Ratios keep the zones aligned with a resized BlueStacks/game window.  They omit
    the emulator chrome, avatar/name column, action buttons, offer count and bottom
    activity feed.  The top zone contains only the request price; the lower one
    contains the first ten listing-price rows.
    """

    REQUEST = (0.72, 0.085, 0.83, 0.17)
    LISTINGS = (0.72, 0.20, 0.83, 0.82)

    @classmethod
    def zones_for(cls, image: Image.Image) -> tuple[PriceZone, PriceZone]:
        price_strip = cls._price_strip_from_buy_buttons(image)
        return (
            cls._zone("request", image, cls.REQUEST, price_strip),
            cls._zone("listings", image, cls.LISTINGS, price_strip),
        )

    @staticmethod
    def crop(image: Image.Image, zone: PriceZone) -> Image.Image:
        box = zone.bounding_box
        return image.crop((box.x, box.y, box.right, box.bottom))

    @staticmethod
    def _zone(
        name: str,
        image: Image.Image,
        ratios: tuple[float, float, float, float],
        price_strip: tuple[int, int] | None,
    ) -> PriceZone:
        width, height = image.size
        strip_left, strip_right = price_strip or (int(width * ratios[0]), int(width * ratios[2]))
        left = max(0, min(width - 1, strip_left))
        top = max(0, min(height - 1, int(height * ratios[1])))
        right = max(left + 1, min(width, strip_right))
        bottom = max(top + 1, min(height, int(height * ratios[3])))
        return PriceZone(name, BoundingBox(left, top, right - left, bottom - top))

    @staticmethod
    def _price_strip_from_buy_buttons(image: Image.Image) -> tuple[int, int] | None:
        """Locate the vertical light-blue BUY-button stack, then take its left price strip."""
        source = np.asarray(image.convert("RGB"), dtype=np.uint8)
        height, width, _ = source.shape
        red, green, blue = (source[:, :, index].astype(np.int16) for index in range(3))
        # Light-blue Buy buttons; the darker blue market background is deliberately excluded.
        blue_button = (red >= 100) & (green >= 140) & (blue >= 180) & (blue >= red + 20) & (blue >= green + 20)
        search_left, search_right = int(width * 0.80), int(width * 0.99)
        column_density = blue_button[:, search_left:search_right].sum(axis=0)
        active = np.flatnonzero(column_density >= max(40, int(height * 0.08)))
        if active.size == 0:
            return None

        runs: list[tuple[int, int, int]] = []
        run_start = previous = int(active[0])
        for current in active[1:]:
            current = int(current)
            if current != previous + 1:
                runs.append((run_start, previous, int(column_density[run_start:previous + 1].sum())))
                run_start = current
            previous = current
        runs.append((run_start, previous, int(column_density[run_start:previous + 1].sum())))
        start, _end, _score = max(runs, key=lambda item: item[2])
        button_left = search_left + start
        gap = max(6, round(width * 0.012))
        strip_width = max(42, round(width * 0.075))
        full_right = button_left - gap
        left = full_right - strip_width
        # The currency glyph lives at the right edge. Keep it out of numeric OCR so
        # it cannot be mistaken for a final digit (for example, G → 6).
        right = full_right - gap
        if left < 0 or right <= left:
            return None
        return left, right
