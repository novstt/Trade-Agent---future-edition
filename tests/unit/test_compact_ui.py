from trade_agent.interface.main_window import MainWindow


def test_compact_window_starts_on_analyzer_and_keeps_all_tabs(qtbot, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    assert window.tabs.currentIndex() == 0
    assert [window.tabs.tabText(index) for index in range(window.tabs.count())] == [
        "Analyzer", "Sell Menu", "Turnover", "Monitor", "History", "Settings"
    ]
    assert window.width() <= 640 and window.height() <= 490
    for index in range(window.tabs.count()):
        window.tabs.setCurrentIndex(index)
        assert window.pages.currentIndex() == index
    window.close()
