from PIL import Image, ImageDraw

from trade_agent.capture import MarketFrameGate


def test_market_frame_gate_ignores_changes_outside_the_price_column() -> None:
    base = Image.new("RGB", (1000, 700), (18, 24, 36))
    unrelated_change = base.copy()
    ImageDraw.Draw(unrelated_change).rectangle((0, 0, 500, 300), fill=(255, 255, 255))

    gate = MarketFrameGate()

    assert gate.has_changed(base)
    assert not gate.has_changed(unrelated_change)


def test_market_frame_gate_detects_a_price_glyph_change() -> None:
    base = Image.new("RGB", (1000, 700), (18, 24, 36))
    changed_price = base.copy()
    ImageDraw.Draw(changed_price).rectangle((760, 120, 790, 140), fill=(255, 220, 120))

    gate = MarketFrameGate()

    assert gate.has_changed(base)
    assert gate.has_changed(changed_price)
