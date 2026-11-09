from trade_agent.core.models import BoundingBox
from trade_agent.recognition import OcrToken, TesseractOcrEngine


def test_tesseract_engine_exposes_the_checked_executable_path() -> None:
    engine = TesseractOcrEngine()
    assert engine.executable_path.endswith("tesseract.exe") or engine.executable_path.endswith("tesseract")


def test_two_segmentation_modes_keep_the_more_confident_value_on_one_row() -> None:
    sparse = OcrToken("20.53", 37, BoundingBox(10, 40, 30, 9))
    block = OcrToken("20.59", 94, BoundingBox(10, 41, 30, 9))

    merged = TesseractOcrEngine._merge_same_row_tokens([sparse], [block])

    assert merged == [block]
