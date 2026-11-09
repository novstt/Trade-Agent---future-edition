import pytest

from trade_agent.capture import CaptureError, parse_hwnd


def test_parse_hwnd_accepts_decimal_and_hexadecimal() -> None:
    assert parse_hwnd("12345") == 12345
    assert parse_hwnd("0x2A") == 42
    assert parse_hwnd(99) == 99


@pytest.mark.parametrize("value", ("", "window", "0", "-5"))
def test_parse_hwnd_rejects_invalid_or_null_values(value: str) -> None:
    with pytest.raises(CaptureError):
        parse_hwnd(value)
