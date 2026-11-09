from trade_agent.interface.main_window import MainWindow


def test_compact_window_starts_on_analyzer_and_keeps_all_tabs(qtbot, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("trade_agent.interface.main_window.GlobalF9Hotkey.install", lambda _self, _application: False)
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    assert window.tabs.currentIndex() == 0
    assert [window.tabs.tabText(index) for index in range(window.tabs.count())] == [
        "Анализ", "Продажа", "Оборот", "Монитор", "История", "Настройки"
    ]
    assert 420 <= window.width() <= 470
    assert 500 <= window.height() <= 560
    assert not window.tabs.usesScrollButtons()
    assert sum(window.tabs.tabRect(index).width() for index in range(window.tabs.count())) <= window.tabs.width()
    assert len(window.market_page.listing_prices) == 10
    assert all(field.isVisible() for field in window.market_page.listing_prices)
    for index in range(window.tabs.count()):
        window.tabs.setCurrentIndex(index)
        assert window.pages.currentIndex() == index
    window.close()
