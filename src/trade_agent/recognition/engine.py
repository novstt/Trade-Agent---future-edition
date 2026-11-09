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
        data = self._pytesseract.image_to_data(
            np.asarray(image.convert("RGB")),
            lang=self.language,
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
        raise RuntimeError("Локальный OCR-движок недоступен.")
