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
    assert 390 <= window.width() <= 430
    assert 320 <= window.height() <= 360
    for index in range(window.tabs.count()):
        window.tabs.setCurrentIndex(index)
        assert window.pages.currentIndex() == index
    window.close()
