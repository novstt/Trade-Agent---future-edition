from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget


def money(value: Decimal | None) -> str:
    return "—" if value is None else f"{value.quantize(Decimal('0.01'))} G"


class CompactOverlay(QWidget):
    stop_requested = Signal()

    def __init__(self) -> None:
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("Trade Agent Overlay")
        self.setMinimumWidth(280)
        self._drag_origin: QPoint | None = None
        frame = QFrame(objectName="card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        title = QLabel("TRADE AGENT  •  LIVE")
        title.setObjectName("brand")
        title.setStyleSheet("font-size: 13px;")
        layout.addWidget(title)
        self.grid = QGridLayout()
        self.labels: dict[str, QLabel] = {}
        for row, name in enumerate(("Item", "Request", "Average", "Net", "Result", "Quantity", "Sticker streak", "Status")):
            name_label = QLabel(name)
            name_label.setObjectName("subtle")
            value = QLabel("—")
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.grid.addWidget(name_label, row, 0)
            self.grid.addWidget(value, row, 1)
            self.labels[name] = value
        layout.addLayout(self.grid)
        stop = QPushButton("Emergency stop (F9)", objectName="danger")
        stop.clicked.connect(self.stop_requested)
        layout.addWidget(stop)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)

    def update_market(self, item: str, request: Decimal | None, average: Decimal | None, net: Decimal | None,
                      result: Decimal | None, quantity: int, streak: int, status: str) -> None:
        values = {
            "Item": item or "—", "Request": money(request), "Average": money(average), "Net": money(net),
            "Result": money(result), "Quantity": str(quantity), "Sticker streak": str(streak), "Status": status,
        }
        for name, value in values.items():
            self.labels[name].setText(value)
        result_label = self.labels["Result"]
        if result is not None:
            result_label.setStyleSheet("color: #55dc9a; font-weight: 700;" if result >= 0 else "color: #ff727d; font-weight: 700;")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_origin is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_origin)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_origin = None

