import os

import pytest

from trade_agent.capture import WindowsCaptureProvider
from trade_agent.core.models import WindowInfo


@pytest.mark.integration
def test_real_window_capture_when_hwnd_is_explicitly_provided() -> None:
    hwnd = os.getenv("TRADE_AGENT_TEST_HWND")
    if not hwnd:
        pytest.skip("Set TRADE_AGENT_TEST_HWND to run an external-window capture integration test.")
    provider = WindowsCaptureProvider()
    candidates = {candidate.hwnd: candidate for candidate in provider.enumerate_windows()}
    assert int(hwnd) in candidates
    frame = provider.capture(candidates[int(hwnd)])
    assert frame.image.width > 1 and frame.image.height > 1
