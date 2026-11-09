from pathlib import Path

from PIL import Image

from trade_agent.recognition import RegionDetector


def test_reference_market_fixture_has_detectable_regions() -> None:
    source = Path(__file__).parents[2] / "assets" / "reference" / "market-listings-1.png"
    regions = RegionDetector().detect(Image.open(source))
    assert len(regions) > 10

