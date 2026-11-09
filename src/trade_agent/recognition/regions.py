from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

from trade_agent.core.models import BoundingBox


@dataclass(frozen=True)
class DetectedRegion:
    bounding_box: BoundingBox
    score: float


class RegionDetector:
    """Scale-independent text-like region detector; it never relies on reference coordinates."""

    def detect(self, image: Image.Image) -> list[DetectedRegion]:
        source = np.asarray(image.convert("RGB"))
        gray = cv2.cvtColor(source, cv2.COLOR_RGB2GRAY)
        normalized = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
        binary = cv2.adaptiveThreshold(
            normalized, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 9
        )
        # A compact horizontal kernel joins glyphs into words without turning a full row/background into one box.
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 2))
        grouped = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)
        contours, _ = cv2.findContours(grouped, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        height, width = gray.shape
        regions: list[DetectedRegion] = []
        for contour in contours:
            x, y, box_width, box_height = cv2.boundingRect(contour)
            if box_width < 12 or box_height < 8 or box_height > height * 0.15:
                continue
            if box_width > width * 0.9:
                continue
            density = cv2.contourArea(contour) / max(box_width * box_height, 1)
            score = min(1.0, (box_width * box_height) / 4000) * min(1.0, density * 4 + 0.2)
            regions.append(DetectedRegion(BoundingBox(x, y, box_width, box_height), score))
        return sorted(regions, key=lambda item: (item.bounding_box.y, item.bounding_box.x))

    @staticmethod
    def group_rows(regions: list[DetectedRegion], tolerance: int = 20) -> list[list[DetectedRegion]]:
        rows: list[list[DetectedRegion]] = []
        for region in sorted(regions, key=lambda entry: (entry.bounding_box.y, entry.bounding_box.x)):
            if not rows or abs(region.bounding_box.y - rows[-1][0].bounding_box.y) > tolerance:
                rows.append([region])
            else:
                rows[-1].append(region)
        return rows

