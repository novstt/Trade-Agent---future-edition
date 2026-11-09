from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image

from trade_agent.core.models import BoundingBox


@dataclass(frozen=True)
class OcrToken:
    text: str
    confidence: float
    bounding_box: BoundingBox


class OcrEngine(Protocol):
    @property
    def is_available(self) -> bool: ...
    def read_tokens(self, image: Image.Image) -> list[OcrToken]: ...


class TesseractOcrEngine:
    """Local Tesseract bridge; importing it does not require a cloud service or API key."""

    DEFAULT_WINDOWS_PATH = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")

    def __init__(self, executable: Path | None = None) -> None:
        requested = executable or self.DEFAULT_WINDOWS_PATH
        found = requested if requested.is_file() else shutil.which("tesseract.exe") or shutil.which("tesseract")
        self.executable_path = str(found or requested)
        try:
            import pytesseract
            self._pytesseract = pytesseract
            if found:
                self._pytesseract.pytesseract.tesseract_cmd = str(found)
            self._available = True
        except Exception:
            self._pytesseract = None
            self._available = False

    @property
    def is_available(self) -> bool:
        if not self._available or self._pytesseract is None:
            return False
        try:
            self._pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

    def read_tokens(self, image: Image.Image) -> list[OcrToken]:
        if not self.is_available:
            raise RuntimeError("Tesseract executable was not found. Install it locally or configure PATH.")
        data = self._pytesseract.image_to_data(
            np.asarray(image.convert("RGB")),
            config="--oem 3 --psm 6",
            output_type=self._pytesseract.Output.DICT,
        )
        tokens: list[OcrToken] = []
        for index, text in enumerate(data["text"]):
            text = text.strip()
            try:
                confidence = float(data["conf"][index])
            except (ValueError, TypeError):
                confidence = -1.0
            if text and confidence >= 0:
                tokens.append(OcrToken(
                    text=text,
                    confidence=confidence,
                    bounding_box=BoundingBox(
                        int(data["left"][index]), int(data["top"][index]),
                        int(data["width"][index]), int(data["height"][index]),
                    ),
                ))
        return tokens


class UnavailableOcrEngine:
    @property
    def is_available(self) -> bool:
        return False

    def read_tokens(self, image: Image.Image) -> list[OcrToken]:
        raise RuntimeError("No local OCR engine is available.")
