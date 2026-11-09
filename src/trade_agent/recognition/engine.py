from __future__ import annotations

import os
import shutil
import subprocess
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
    OCR_SCALE = 4
    ROW_OCR_SCALE = 6
    _NUMERIC_CONFIG = "--oem 3 -c tessedit_char_whitelist=0123456789.,"

    def __init__(self, executable: Path | None = None) -> None:
        requested = executable or self.DEFAULT_WINDOWS_PATH
        found = requested if requested.is_file() else shutil.which("tesseract.exe") or shutil.which("tesseract")
        self.executable_path = str(found or requested)
        try:
            import pytesseract
            self._pytesseract = pytesseract
            if found:
                self._pytesseract.pytesseract.tesseract_cmd = str(found)
            self._hide_tesseract_console()
            self._pytesseract.get_tesseract_version()
            self._available = True
            self.language = self._choose_language()
        except Exception:
            self._pytesseract = None
            self._available = False
            self.language = "eng"

    def _hide_tesseract_console(self) -> None:
        """Prevent a transient cmd.exe/tesseract console from appearing on Windows."""
        if os.name != "nt" or self._pytesseract is None:
            return
        bridge = self._pytesseract.pytesseract
        if getattr(bridge, "_trade_agent_console_hidden", False):
            return
        original_subprocess_args = bridge.subprocess_args

        def hidden_subprocess_args(*args, **kwargs):
            options = original_subprocess_args(*args, **kwargs)
            options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            return options

        bridge.subprocess_args = hidden_subprocess_args
        bridge._trade_agent_console_hidden = True

    def _choose_language(self) -> str:
        """Use Russian button text when its local trained data is installed; otherwise stay operational in English."""
        try:
            languages = set(self._pytesseract.get_languages(config=""))
            return "eng+rus" if {"eng", "rus"}.issubset(languages) else "eng"
        except Exception:
            return "eng"

    @property
    def is_available(self) -> bool:
        # Checking `tesseract --version` for every frame spawned another child
        # process. Availability is established while this local engine is created;
        # a later OCR failure is returned to the UI normally.
        return self._available and self._pytesseract is not None

    def read_tokens(self, image: Image.Image) -> list[OcrToken]:
        if not self.is_available:
            raise RuntimeError("Исполняемый файл Tesseract не найден. Установите его локально или настройте PATH.")
        prepared = image.convert("RGB").resize(
            (image.width * self.OCR_SCALE, image.height * self.OCR_SCALE), Image.Resampling.LANCZOS,
        )
        sparse_tokens = self._read_tokens(prepared, f"{self._NUMERIC_CONFIG} --psm 11", self.OCR_SCALE)
        block_tokens = self._read_tokens(prepared, f"{self._NUMERIC_CONFIG} --psm 6", self.OCR_SCALE)
        tokens = self._merge_same_row_tokens(sparse_tokens, block_tokens)
        return self._refine_low_confidence_rows(image, tokens)

    def _read_tokens(self, image: Image.Image, config: str, scale: int) -> list[OcrToken]:
        data = self._pytesseract.image_to_data(
            np.asarray(image),
            lang=self.language,
            config=config,
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
                        round(int(data["left"][index]) / scale),
                        round(int(data["top"][index]) / scale),
                        max(1, round(int(data["width"][index]) / scale)),
                        max(1, round(int(data["height"][index]) / scale)),
                    ),
                ))
        return tokens

    def _refine_low_confidence_rows(self, image: Image.Image, tokens: list[OcrToken]) -> list[OcrToken]:
        """Retry only an uncertain price row with single-line segmentation.

        A low-resolution game glyph can make one mode confuse `9` and `3`.  The retry
        is bounded to that row and happens only below the configured confidence floor.
        """
        refined: list[OcrToken] = []
        for token in tokens:
            if token.confidence >= 55 or not any(character.isdigit() for character in token.text):
                refined.append(token)
                continue
            box = token.bounding_box
            padding = max(5, box.height // 2)
            top = max(0, box.y - padding)
            bottom = min(image.height, box.bottom + padding)
            row = image.crop((0, top, image.width, bottom)).convert("RGB").resize(
                (image.width * self.ROW_OCR_SCALE, (bottom - top) * self.ROW_OCR_SCALE), Image.Resampling.LANCZOS,
            )
            retry = self._read_tokens(row, f"{self._NUMERIC_CONFIG} --psm 7", self.ROW_OCR_SCALE)
            retry = [candidate for candidate in retry if any(character.isdigit() for character in candidate.text)]
            if retry:
                best = max(retry, key=lambda candidate: candidate.confidence)
                retry_box = best.bounding_box
                refined.append(OcrToken(
                    best.text, best.confidence,
                    BoundingBox(retry_box.x, retry_box.y + top, retry_box.width, retry_box.height),
                ))
            else:
                refined.append(token)
        return refined

    @staticmethod
    def _merge_same_row_tokens(*token_sets: list[OcrToken]) -> list[OcrToken]:
        """Use two page-segmentation modes, retaining the most confident token per row."""
        rows: list[list[OcrToken]] = []
        for token in sorted((entry for group in token_sets for entry in group), key=lambda item: item.bounding_box.y):
            center_y = token.bounding_box.y + token.bounding_box.height / 2
            for row in rows:
                reference = row[0].bounding_box
                reference_center = reference.y + reference.height / 2
                if abs(center_y - reference_center) <= 10:
                    row.append(token)
                    break
            else:
                rows.append([token])

        def rank(token: OcrToken) -> tuple[bool, float]:
            return any(character.isdigit() for character in token.text), token.confidence

        return [max(row, key=rank) for row in rows]


class UnavailableOcrEngine:
    @property
    def is_available(self) -> bool:
        return False

    def read_tokens(self, image: Image.Image) -> list[OcrToken]:
        raise RuntimeError("Локальный OCR-движок недоступен.")
