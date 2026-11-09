from PIL import Image, ImageDraw

from trade_agent.recognition import MarketPriceZones


def test_market_price_zones_use_the_strip_immediately_left_of_buy_buttons() -> None:
    image = Image.new("RGB", (1000, 900), (18, 28, 42))
    draw = ImageDraw.Draw(image)
    for y in range(220, 720, 45):
        draw.rectangle((850, y, 960, y + 25), fill=(110, 150, 220))

    request, listings = MarketPriceZones.zones_for(image)

    assert (request.bounding_box.x, request.bounding_box.width) == (763, 63)
    assert (listings.bounding_box.x, listings.bounding_box.width) == (763, 63)
    assert (request.bounding_box.y, request.bounding_box.height) == (76, 77)
    assert (listings.bounding_box.y, listings.bounding_box.height) == (180, 558)


def test_market_price_zones_fall_back_to_relative_strip_when_buy_buttons_are_not_found() -> None:
    image = Image.new("RGB", (1000, 900), (18, 28, 42))

    request, listings = MarketPriceZones.zones_for(image)

    assert (request.bounding_box.x, request.bounding_box.width) == (720, 110)
    assert (listings.bounding_box.x, listings.bounding_box.width) == (720, 110)
