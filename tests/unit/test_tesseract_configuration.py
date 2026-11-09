from trade_agent.recognition import TesseractOcrEngine


def test_tesseract_engine_exposes_the_checked_executable_path() -> None:
    engine = TesseractOcrEngine()
    assert engine.executable_path.endswith("tesseract.exe") or engine.executable_path.endswith("tesseract")
