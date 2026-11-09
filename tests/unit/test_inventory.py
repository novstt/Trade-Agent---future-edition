from PIL import Image

from trade_agent.inventory import InventoryAnalyzer


class DeterministicDetector:
    def detect(self, _card):
        return True, 0.86


def test_sticker_streak_deduplicates_same_card() -> None:
    analyzer = InventoryAnalyzer(DeterministicDetector())
    card = Image.new("RGB", (120, 60), "purple")
    assert analyzer.analyse_card("Card 1", card) is not None
    assert analyzer.analyse_card("Card 1 repeat", card) is None
    assert analyzer.current_streak == 1
    stickers, normal, _ = analyzer.reset_session()
    assert (stickers, normal, analyzer.current_streak) == (1, 0, 0)

