from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from trade_agent.interface.main_window import MainWindow
from trade_agent.interface.theme import APP_STYLE


def main() -> int:
    application = QApplication(sys.argv)
    application.setApplicationName("Trade Agent")
    application.setStyleSheet(APP_STYLE)
    window = MainWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())

