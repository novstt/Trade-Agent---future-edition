from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from PIL import Image, ImageDraw
from PySide6.QtCore import QByteArray, QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFormLayout, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QPushButton, QSpinBox, QStackedWidget, QTabBar,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from trade_agent.calculator import DEFAULT_COMMISSION, ProfitEngine
from trade_agent.capture import CaptureError, CaptureWorker, WindowsCaptureProvider
from trade_agent.core.models import CaptureFrame, PriceReading, ReliabilityState, ValidationStatus, WindowInfo
from trade_agent.interface.hotkey import GlobalF9Hotkey
from trade_agent.interface.overlay import CompactOverlay
from trade_agent.inventory import InventoryAnalyzer, SellMenuDetector
from trade_agent.market import MarketAnalyzer, MarketPriceExtractor
from trade_agent.recognition import PriceRecognizer, RecognitionResult, TesseractOcrEngine
from trade_agent.reliability import ReliabilityManager
from trade_agent.storage import Database
from trade_agent.turnover import SkinTurnoverService


def _money(value: Decimal | None) -> str:
    return "—" if value is None else f"{value.quantize(Decimal('0.01'))} G"


def _pixmap(image: Image.Image, target_size=None) -> QPixmap:
    rgba = image.convert("RGBA")
    buffer = rgba.tobytes("raw", "RGBA")
    qimage = QImage(buffer, rgba.width, rgba.height, rgba.width * 4, QImage.Format_RGBA8888).copy()
    pixmap = QPixmap.fromImage(qimage)
    return pixmap.scaled(target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation) if target_size else pixmap


def _reading_from_text(text: str) -> PriceReading:
    text = text.strip()
    if not text:
        return PriceReading("", None, None, 0, validation_status=ValidationStatus.MISSING)
    value = PriceRecognizer.parse_price(text)
    return PriceReading(text, value, None, 100, validation_status=ValidationStatus.VALID if value is not None else ValidationStatus.INVALID)


class RecognitionSignals(QObject):
    completed = Signal(object)


class RecognitionTask(QRunnable):
    def __init__(self, recognizer: PriceRecognizer, image: Image.Image, timestamp: datetime) -> None:
        super().__init__()
        self.recognizer = recognizer
        self.image = image.copy()
        self.timestamp = timestamp
        self.signals = RecognitionSignals()

    def run(self) -> None:
        self.signals.completed.emit(self.recognizer.recognize(self.image, self.timestamp))


class AnalyzerPage(QWidget):
    """Compact trading panel. The existing ten listing inputs live in a collapsed editor."""

    calculation_updated = Signal(object, object, int)
    start_requested = Signal()
    stop_requested = Signal()
    hwnd_requested = Signal()
    monitor_requested = Signal()

    def __init__(self, database: Database) -> None:
        super().__init__()
        self.database = database
        self.analyzer = MarketAnalyzer()
        self.profit_engine = ProfitEngine()
        self.last_result = None
        self.selected_window: WindowInfo | None = None
        self.commission = self._load_commission()
        root = QVBoxLayout(self)
        root.setContentsMargins(9, 8, 9, 8)
        root.setSpacing(5)
        header = QHBoxLayout()
        header.addWidget(QLabel("TRADE AGENT", objectName="sectionTitle"))
        self.recognition_status = QLabel("READY", objectName="statusChip")
        self.recognition_status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(self.recognition_status, 1)
        root.addLayout(header)

        self.item_name = QLineEdit("Detected item")
        self.request_price = QLineEdit()
        self.request_price.setPlaceholderText("Request price")
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 99999)
        self.quantity.setValue(1)
        self.average_value = QLabel("—", objectName="value")
        self.net_value = QLabel("—", objectName="value")
        self.profit_value = QLabel("—", objectName="neutralValue")
        self.total_value = QLabel("—", objectName="value")
        self.commission_value = QLabel(self._commission_text(), objectName="value")
        summary = QHBoxLayout()
        summary.setSpacing(6)
        item_result = QVBoxLayout()
        item_result.addWidget(QLabel("P/L PER ITEM", objectName="subtle"))
        item_result.addWidget(self.profit_value)
        total_result = QVBoxLayout()
        total_result.addWidget(QLabel("EXPECTED TOTAL", objectName="subtle"))
        total_result.addWidget(self.total_value)
        summary.addLayout(item_result, 1)
        summary.addLayout(total_result, 1)
        root.addLayout(summary)

        fields = QGridLayout()
        fields.setHorizontalSpacing(10)
        fields.setVerticalSpacing(5)
        self._add_field(fields, 0, 0, "REQUEST", self.request_price)
        self._add_field(fields, 0, 1, "AVG / 10", self.average_value)
        self._add_field(fields, 1, 0, "COMMISSION", self.commission_value)
        self._add_field(fields, 1, 1, "NET SALE", self.net_value)
        self._add_field(fields, 2, 0, "QUANTITY", self.quantity)
        root.addLayout(fields)

        hwnd_row = QHBoxLayout()
        self.hwnd_value = QLabel("HWND —", objectName="hwndValue")
        self.get_hwnd_button = QPushButton("ПОЛУЧИТЬ HWND")
        hwnd_row.addWidget(self.hwnd_value, 1)
        hwnd_row.addWidget(self.get_hwnd_button)
        root.addLayout(hwnd_row)

        start_row = QHBoxLayout()
        self.start_button = QPushButton("ЗАПУСТИТЬ ЗАХВАТ", objectName="primary")
        start_row.addWidget(self.start_button)
        root.addLayout(start_row)

        controls = QHBoxLayout()
        self.stop_button = QPushButton("СТОП")
        self.monitor_button = QPushButton("МОНИТОР")
        self.edit_listings_button = QPushButton("10 ЦЕН")
        controls.addWidget(self.stop_button)
        controls.addWidget(self.monitor_button)
        controls.addWidget(self.edit_listings_button)
        root.addLayout(controls)
        self.reason = QLabel("Waiting for 10 valid listings.", objectName="statusLine")
        self.reason.setWordWrap(False)
        root.addWidget(self.reason)

        self.listings_editor = QWidget()
        editor = QGridLayout(self.listings_editor)
        editor.setContentsMargins(4, 4, 4, 4)
        self.listing_prices: list[QLineEdit] = []
        for index in range(10):
            field = QLineEdit()
            field.setPlaceholderText(f"#{index + 1}")
            field.setMaximumWidth(105)
            self.listing_prices.append(field)
            editor.addWidget(QLabel(f"{index + 1:02}", objectName="subtle"), index // 5, (index % 5) * 2)
            editor.addWidget(field, index // 5, (index % 5) * 2 + 1)
            field.editingFinished.connect(self.calculate)
        self.listings_editor.setVisible(False)
        root.addWidget(self.listings_editor)
        self.item_name.setVisible(False)
        root.addStretch(1)

        self.start_button.clicked.connect(self.start_requested)
        self.stop_button.clicked.connect(self.stop_requested)
        self.get_hwnd_button.clicked.connect(self.hwnd_requested)
        self.monitor_button.clicked.connect(self.monitor_requested)
        self.edit_listings_button.clicked.connect(self._toggle_listings)
        self.request_price.editingFinished.connect(self.calculate)
        self.quantity.valueChanged.connect(self.calculate)

    @staticmethod
    def _add_field(layout: QGridLayout, row: int, column: int, name: str, widget: QWidget) -> None:
        layout.addWidget(QLabel(name, objectName="subtle"), row, column * 2)
        layout.addWidget(widget, row, column * 2 + 1)

    def _load_commission(self) -> Decimal:
        try:
            return Decimal(str(self.database.get_setting("commission_percent", "20"))) / Decimal("100")
        except (InvalidOperation, ValueError):
            return DEFAULT_COMMISSION

    def _commission_text(self) -> str:
        return f"{(self.commission * 100).normalize():f}%"

    def _toggle_listings(self) -> None:
        visible = not self.listings_editor.isVisible()
        self.listings_editor.setVisible(visible)
        self.edit_listings_button.setText("СКРЫТЬ ЦЕНЫ" if visible else "10 ЦЕН")

    def set_commission_percent(self, percent: Decimal) -> None:
        self.commission = percent / Decimal("100")
        self.commission_value.setText(self._commission_text())
        self.calculate()

    def set_capture_status(self, text: str) -> None:
        self.recognition_status.setText(text)

    def set_hwnd(self, window: WindowInfo) -> None:
        self.selected_window = window
        self.hwnd_value.setText(f"HWND 0x{window.hwnd:X}")

    def apply_recognition(self, request: PriceReading | None, listings: list[PriceReading], ocr_message: str) -> None:
        if request and request.parsed_value is not None:
            self.request_price.setText(str(request.parsed_value))
        for index, field in enumerate(self.listing_prices):
            field.setText(str(listings[index].parsed_value) if index < len(listings) and listings[index].parsed_value is not None else "")
        self.set_capture_status(f"OCR • {len(listings)}/10 listings")
        self.reason.setText(ocr_message if listings else f"{ocr_message} No valid listing values found.")
        self.calculate()

    def calculate(self) -> None:
        snapshot = self.analyzer.create_snapshot(
            self.item_name.text().strip() or "Unnamed item", _reading_from_text(self.request_price.text()),
            [_reading_from_text(field.text()) for field in self.listing_prices],
        )
        result = self.profit_engine.calculate(snapshot, self.quantity.value(), Decimal("5.00"), self.commission)
        self.last_result = result
        self.average_value.setText(_money(result.average_price))
        self.net_value.setText(_money(result.net_sale_price))
        self.profit_value.setText(_money(result.per_item_result))
        self.total_value.setText(_money(result.total_result))
        self.profit_value.setObjectName(
            "profit" if result.per_item_result is not None and result.per_item_result >= 0 else "loss" if result.per_item_result is not None else "neutralValue"
        )
        self.profit_value.style().unpolish(self.profit_value)
        self.profit_value.style().polish(self.profit_value)
        self.reason.setText(result.reason)
        self.database.save_snapshot(snapshot)
        self.database.save_calculation(result)
        self.calculation_updated.emit(snapshot, result, self.quantity.value())


class CaptureMonitorPage(QWidget):
    start_requested = Signal(object)
    stop_requested = Signal()
    analyze_requested = Signal()
    hwnd_ready = Signal(object)

    def __init__(self, provider: WindowsCaptureProvider | None) -> None:
        super().__init__()
        self.provider = provider
        self.last_image: Image.Image | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)
        top = QHBoxLayout()
        self.window_combo = QComboBox()
        self.refresh_button = QPushButton("Refresh")
        self.start_button = QPushButton("Start", objectName="primary")
        self.stop_button = QPushButton("Stop")
        top.addWidget(self.window_combo, 1)
        top.addWidget(self.refresh_button)
        top.addWidget(self.start_button)
        top.addWidget(self.stop_button)
        root.addLayout(top)
        hwnd_row = QHBoxLayout()
        self.hwnd_input = QLineEdit()
        self.hwnd_input.setPlaceholderText("HWND / 0x…")
        self.get_hwnd_button = QPushButton("Получить")
        self.use_hwnd_button = QPushButton("Захват по HWND", objectName="primary")
        hwnd_row.addWidget(self.hwnd_input, 1)
        hwnd_row.addWidget(self.get_hwnd_button)
        hwnd_row.addWidget(self.use_hwnd_button)
        root.addLayout(hwnd_row)
        options = QHBoxLayout()
        self.auto_analyze = QCheckBox("Auto OCR")
        self.auto_analyze.setChecked(True)
        self.show_overlay = QCheckBox("Show overlay")
        options.addWidget(self.auto_analyze)
        options.addWidget(self.show_overlay)
        options.addStretch()
        root.addLayout(options)
        self.meta = QLabel("Stopped • select a window", objectName="subtle")
        root.addWidget(self.meta)
        self.preview = QLabel("No real frame received")
        self.preview.setObjectName("capturePreview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(220)
        root.addWidget(self.preview, 1)
        bottom = QHBoxLayout()
        self.diagnostics = QLabel("Source: —\nResolution: —\nFPS: —\nOCR: waiting", objectName="subtle")
        self.analyze_button = QPushButton("Analyse frame")
        bottom.addWidget(self.diagnostics, 1)
        bottom.addWidget(self.analyze_button)
        root.addLayout(bottom)
        self.refresh_button.clicked.connect(self.refresh_windows)
        self.start_button.clicked.connect(self._start)
        self.stop_button.clicked.connect(self.stop_requested)
        self.get_hwnd_button.clicked.connect(self.get_selected_hwnd)
        self.use_hwnd_button.clicked.connect(self._start_from_hwnd)
        self.analyze_button.clicked.connect(self.analyze_requested)
        self.window_combo.currentIndexChanged.connect(self.get_selected_hwnd)
        self.refresh_windows()

    def refresh_windows(self) -> None:
        self.window_combo.clear()
        if self.provider is None:
            self.window_combo.addItem("Windows capture unavailable")
            return
        try:
            for window in self.provider.enumerate_windows():
                self.window_combo.addItem(f"{window.title}  [{window.width}×{window.height}]", window)
            self.set_status(f"Stopped • {self.window_combo.count()} windows")
        except Exception as exc:
            self.set_status(f"Error • {exc}")

    def _start(self) -> None:
        window = self.selected_window()
        if isinstance(window, WindowInfo):
            self.hwnd_ready.emit(window)
            self.start_requested.emit(window)
        else:
            self.set_status("Select a visible window first")

    def selected_window(self) -> WindowInfo | None:
        window = self.window_combo.currentData()
        return window if isinstance(window, WindowInfo) else None

    def get_selected_hwnd(self) -> WindowInfo | None:
        window = self.selected_window()
        if window is None:
            self.set_status("Select a visible window first")
            return None
        self.hwnd_input.setText(f"0x{window.hwnd:X}")
        self.hwnd_ready.emit(window)
        self.set_status(f"HWND received • 0x{window.hwnd:X}")
        return window

    def _start_from_hwnd(self) -> None:
        if self.provider is None:
            self.set_status("Windows capture unavailable")
            return
        try:
            window = self.provider.get_window_info(self.hwnd_input.text())
        except CaptureError as exc:
            self.set_status(f"HWND error • {exc}")
            return
        self.hwnd_ready.emit(window)
        self.start_requested.emit(window)

    def set_frame(self, frame: CaptureFrame, fps: float | None = None) -> None:
        self.last_image = frame.image
        self.preview.setPixmap(_pixmap(frame.image, self.preview.size()))
        self.diagnostics.setText(
            f"Source: {frame.source.title}\nResolution: {frame.source.width}×{frame.source.height}  •  FPS: {fps or 0:.1f}"
            f"\nLast frame: {frame.timestamp.astimezone().strftime('%H:%M:%S')}"
        )

    def set_annotated(self, image: Image.Image, result: RecognitionResult) -> None:
        self.preview.setPixmap(_pixmap(image, self.preview.size()))
        status = "ready" if result.ocr_available else "unavailable"
        self.diagnostics.setText(self.diagnostics.text().split("\nOCR:")[0] + f"\nOCR: {status}; {len(result.readings)} values")

    def set_status(self, text: str) -> None:
        self.meta.setText(text)


class SellMenuPage(QWidget):
    session_changed = Signal(int, int)

    def __init__(self, inventory: InventoryAnalyzer) -> None:
        super().__init__()
        self.inventory, self.detector = inventory, SellMenuDetector()
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)
        top = QHBoxLayout()
        self.analyse_button = QPushButton("Analyse current capture", objectName="primary")
        self.status = QLabel("Waiting for a Sell Menu capture", objectName="subtle")
        top.addWidget(self.analyse_button)
        top.addWidget(self.status, 1)
        root.addLayout(top)
        metrics = QHBoxLayout()
        self.streak = QLabel("0", objectName="value")
        self.sticker_count = QLabel("0", objectName="value")
        self.normal_count = QLabel("0", objectName="value")
        for label, value in (("Streak", self.streak), ("Sticker", self.sticker_count), ("Normal", self.normal_count)):
            metrics.addWidget(QLabel(label, objectName="subtle"))
            metrics.addWidget(value)
        metrics.addStretch()
        root.addLayout(metrics)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Item", "Class", "Confidence"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        root.addWidget(self.table, 1)

    def analyze_image(self, image: Image.Image | None) -> None:
        if image is None:
            self.status.setText("Capture a real Sell Menu frame first")
            return
        cards = self.detector.detect_cards(image)
        added = 0
        for index, card in enumerate(cards):
            crop = image.crop((card.x, card.y, card.right, card.bottom))
            item = self.inventory.analyse_card(f"Sell card {index + 1}", crop, card)
            if item is None:
                continue
            added += 1
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(item.name))
            self.table.setItem(row, 1, QTableWidgetItem("STICKER" if item.has_sticker else "NORMAL"))
            self.table.setItem(row, 2, QTableWidgetItem(f"{item.confidence:.0%}"))
        self._show_counts()
        self.status.setText(f"{len(cards)} candidates • {added} new items")
        self.session_changed.emit(self.inventory.current_streak, len(self.inventory.normal_items))

    def _show_counts(self) -> None:
        self.streak.setText(str(self.inventory.current_streak))
        self.sticker_count.setText(str(len(self.inventory.sticker_items)))
        self.normal_count.setText(str(len(self.inventory.normal_items)))

    def reset_display(self) -> None:
        self.table.setRowCount(0)
        self._show_counts()
        self.status.setText("Session stopped")


class TurnoverPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.service = SkinTurnoverService()
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.addWidget(QLabel("TURNOVER", objectName="sectionTitle"))
        self.text = QLabel("Run a valid market calculation to create a scenario.", objectName="subtle")
        self.text.setWordWrap(True)
        root.addWidget(self.text)
        root.addStretch()

    def update_from_calculation(self, result, quantity: int, loss: Decimal) -> None:
        scenario = self.service.simulate(result, quantity, loss)
        self.text.setText(
            f"Target: {scenario.target_quantity}\nMax loss / item: {_money(scenario.maximum_loss_per_item)}"
            f"\nProjected result: {_money(scenario.projected_total)}\n{scenario.cycle_note}"
        )


class HistoryPage(QWidget):
    def __init__(self, database: Database) -> None:
        super().__init__()
        self.database = database
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        top = QHBoxLayout()
        top.addWidget(QLabel("HISTORY", objectName="sectionTitle"))
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        top.addStretch()
        top.addWidget(refresh)
        root.addLayout(top)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["When", "Type", "Detail"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        root.addWidget(self.table, 1)
        self.refresh()

    def refresh(self) -> None:
        rows = self.database.recent_history()
        self.table.setRowCount(0)
        for entry in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(entry["happened_at"]))
            self.table.setItem(row, 1, QTableWidgetItem(entry["kind"]))
            self.table.setItem(row, 2, QTableWidgetItem(entry["detail"]))


class SettingsPage(QWidget):
    commission_changed = Signal(object)

    def __init__(self, database: Database, ocr_engine: TesseractOcrEngine) -> None:
        super().__init__()
        self.database, self.ocr_engine = database, ocr_engine
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)
        root.addWidget(QLabel("SETTINGS", objectName="sectionTitle"))
        form = QFormLayout()
        self.commission = QLineEdit(str(database.get_setting("commission_percent", "20")))
        self.frame_interval = QSpinBox()
        self.frame_interval.setRange(100, 5000)
        self.frame_interval.setValue(int(database.get_setting("capture_interval_ms", 350)))
        form.addRow("Commission (%)", self.commission)
        form.addRow("Capture interval (ms)", self.frame_interval)
        root.addLayout(form)
        self.ocr_note = QLabel(self._ocr_message(), objectName="subtle")
        self.ocr_note.setWordWrap(True)
        root.addWidget(self.ocr_note)
        save = QPushButton("Save", objectName="primary")
        save.clicked.connect(self.save)
        root.addWidget(save, alignment=Qt.AlignLeft)
        root.addStretch()

    def _ocr_message(self) -> str:
        if self.ocr_engine.is_available:
            return f"Tesseract: ready • {self.ocr_engine.executable_path}"
        return f"Tesseract not found. Checked: {self.ocr_engine.executable_path}. Install it or add it to PATH; capture remains available."

    def save(self) -> None:
        try:
            percent = Decimal(self.commission.text().strip().replace(",", "."))
            if not Decimal("0") <= percent < Decimal("100"):
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            self.ocr_note.setText("Commission must be from 0 to less than 100.")
            return
        self.database.set_setting("commission_percent", str(percent))
        self.database.set_setting("capture_interval_ms", self.frame_interval.value())
        self.commission_changed.emit(percent)
        self.ocr_note.setText(f"Saved • {self._ocr_message()}")


class MainWindow(QMainWindow):
    TAB_NAMES = ("Analyzer", "Sell Menu", "Turnover", "Monitor", "History", "Settings")
    COMPACT_UI_VERSION = 2

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Trade Agent")
        self.setMinimumSize(390, 320)
        self.resize(430, 360)
        app_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "TradeAgent"
        self.database = Database(app_data / "trade_agent.sqlite3")
        self.reliability = ReliabilityManager()
        self.inventory = InventoryAnalyzer()
        self.ocr_engine = TesseractOcrEngine()
        self.recognizer = PriceRecognizer(self.ocr_engine)
        self.extractor = MarketPriceExtractor()
        try:
            self.provider: WindowsCaptureProvider | None = WindowsCaptureProvider()
        except Exception as exc:
            self.provider = None
            self.database.log("ERROR", f"Capture provider unavailable: {exc}")
        self.capture_worker: CaptureWorker | None = None
        self.last_frame: CaptureFrame | None = None
        self.current_fps: float | None = None
        self.recognition_busy = False
        self.thread_pool = QThreadPool.globalInstance()
        self.overlay = CompactOverlay()
        self.overlay.stop_requested.connect(self.emergency_stop)
        self.hotkey = GlobalF9Hotkey()
        self.hotkey.activated.connect(self.emergency_stop)
        self.hotkey_active = self.hotkey.install(QApplication.instance())
        self._build_ui()
        self._restore_window_state()

    def _build_ui(self) -> None:
        root_widget = QWidget()
        root = QVBoxLayout(root_widget)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)
        nav = QWidget(objectName="topNav")
        nav_layout = QHBoxLayout(nav)
        nav_layout.setContentsMargins(5, 3, 5, 3)
        nav_layout.setSpacing(4)
        self.tabs = QTabBar()
        self.tabs.setExpanding(True)
        self.tabs.setDrawBase(False)
        for name in self.TAB_NAMES:
            self.tabs.addTab(name)
        nav_layout.addWidget(self.tabs, 1)
        self.always_on_top = QCheckBox("⇧")
        self.always_on_top.setToolTip("Always on top")
        nav_layout.addWidget(self.always_on_top)
        root.addWidget(nav)
        self.pages = QStackedWidget()
        self.market_page = AnalyzerPage(self.database)
        self.sell_page = SellMenuPage(self.inventory)
        self.turnover_page = TurnoverPage()
        self.capture_page = CaptureMonitorPage(self.provider)
        self.history_page = HistoryPage(self.database)
        self.settings_page = SettingsPage(self.database, self.ocr_engine)
        for page in (self.market_page, self.sell_page, self.turnover_page, self.capture_page, self.history_page, self.settings_page):
            self.pages.addWidget(page)
        root.addWidget(self.pages, 1)
        self.setCentralWidget(root_widget)
        self.tabs.currentChanged.connect(self._navigate)
        self.tabs.setCurrentIndex(0)
        self.always_on_top.toggled.connect(self._apply_always_on_top)
        self.market_page.start_requested.connect(self._start_from_monitor_selection)
        self.market_page.stop_requested.connect(self.stop_capture)
        self.market_page.hwnd_requested.connect(self._get_selected_hwnd)
        self.market_page.monitor_requested.connect(lambda: self.tabs.setCurrentIndex(3))
        self.market_page.calculation_updated.connect(self._calculation_updated)
        self.capture_page.start_requested.connect(self.start_capture)
        self.capture_page.stop_requested.connect(self.stop_capture)
        self.capture_page.analyze_requested.connect(self.analyze_current_frame)
        self.capture_page.hwnd_ready.connect(self.market_page.set_hwnd)
        self.capture_page.show_overlay.toggled.connect(self.overlay.setVisible)
        self.sell_page.analyse_button.clicked.connect(lambda: self.sell_page.analyze_image(self.last_frame.image if self.last_frame else None))
        self.sell_page.session_changed.connect(self._inventory_changed)
        self.settings_page.commission_changed.connect(self.market_page.set_commission_percent)

    def _restore_window_state(self) -> None:
        geometry = self.database.get_setting("window_geometry")
        if self.database.get_setting("compact_ui_version") == self.COMPACT_UI_VERSION and isinstance(geometry, str):
            self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
        else:
            self.database.set_setting("compact_ui_version", self.COMPACT_UI_VERSION)
        self.always_on_top.setChecked(bool(self.database.get_setting("always_on_top", False)))

    def _apply_always_on_top(self, enabled: bool) -> None:
        self.setWindowFlag(Qt.WindowStaysOnTopHint, enabled)
        self.show()
        self.database.set_setting("always_on_top", enabled)

    def _navigate(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        if index == 4:
            self.history_page.refresh()

    def _start_from_monitor_selection(self) -> None:
        if self.provider is None:
            self.market_page.set_capture_status("Capture unavailable")
            return
        if self.market_page.selected_window is not None:
            try:
                self.start_capture(self.provider.get_window_info(self.market_page.selected_window.hwnd))
            except CaptureError as exc:
                self.market_page.set_capture_status(f"HWND error • {exc}")
            return
        window = self.capture_page.get_selected_hwnd()
        if isinstance(window, WindowInfo):
            self.start_capture(window)
        else:
            self.market_page.set_capture_status("Select source in Monitor")
            self.tabs.setCurrentIndex(3)

    def _get_selected_hwnd(self) -> None:
        window = self.capture_page.get_selected_hwnd()
        if window is None:
            self.market_page.set_capture_status("Select source in Monitor")
            self.tabs.setCurrentIndex(3)
        else:
            self.market_page.set_hwnd(window)
            self.market_page.set_capture_status("HWND ready")

    def start_capture(self, window: WindowInfo) -> None:
        self.stop_capture()
        if self.provider is None:
            self.capture_page.set_status("Error • Windows capture unavailable")
            self.market_page.set_capture_status("Capture unavailable")
            return
        interval = int(self.database.get_setting("capture_interval_ms", 350))
        self.capture_worker = CaptureWorker(self.provider, window, interval)
        self.capture_worker.frame_captured.connect(self._frame_received)
        self.capture_worker.capture_error.connect(self._capture_error)
        self.capture_worker.status_changed.connect(self._capture_status)
        self.capture_worker.metrics_changed.connect(self._capture_metrics)
        self.capture_worker.start()
        self.capture_page.set_status(f"Capturing • {window.title}")
        self.market_page.set_capture_status("Capturing • waiting for frame")

    def stop_capture(self) -> None:
        if self.capture_worker and self.capture_worker.isRunning():
            self.capture_worker.stop()
            self.capture_worker.wait(1800)
        self.capture_worker = None
        self.capture_page.set_status("Stopped")
        self.market_page.set_capture_status("Stopped")

    def _capture_status(self, status: str) -> None:
        self.capture_page.set_status(status.title())
        self.market_page.set_capture_status(status.title())

    def _capture_metrics(self, fps: float, _timestamp) -> None:
        self.current_fps = fps

    def _capture_error(self, message: str) -> None:
        state = self.reliability.record_error(message)
        self.database.log("WARNING", message)
        self.capture_page.set_status(f"{state.value} • {message}")
        self.market_page.set_capture_status(f"{state.value} • capture error")
        if state is ReliabilityState.SAFE_STOP:
            self.stop_capture()

    def _frame_received(self, frame: CaptureFrame) -> None:
        self.last_frame = frame
        self.reliability.record_success(frame.timestamp)
        self.capture_page.set_frame(frame, self.current_fps)
        self.market_page.set_capture_status("Live frame • OCR queued")
        if self.capture_page.auto_analyze.isChecked() and not self.recognition_busy:
            self.analyze_current_frame()

    def analyze_current_frame(self) -> None:
        if self.last_frame is None:
            self.capture_page.set_status("No frame available for OCR")
            return
        if self.recognition_busy:
            return
        self.recognition_busy = True
        task = RecognitionTask(self.recognizer, self.last_frame.image, self.last_frame.timestamp)
        task.signals.completed.connect(self._recognition_completed)
        self.thread_pool.start(task)
        self.market_page.set_capture_status("Analysing • local OCR")

    def _recognition_completed(self, result: RecognitionResult) -> None:
        self.recognition_busy = False
        if self.last_frame is None:
            return
        self.capture_page.set_annotated(self._annotate(self.last_frame.image, result), result)
        request, listings = self.extractor.extract(result, self.last_frame.source.width)
        message = result.error or ("Local OCR complete" if result.ocr_available else "Local OCR unavailable")
        self.market_page.apply_recognition(request, listings, message)
        self.capture_page.set_status("Capturing • OCR updated" if self.capture_worker else "Stopped • OCR updated")

    @staticmethod
    def _annotate(image: Image.Image, result: RecognitionResult) -> Image.Image:
        copy = image.convert("RGBA").copy()
        draw = ImageDraw.Draw(copy)
        for region in result.regions:
            box = region.bounding_box
            draw.rectangle((box.x, box.y, box.right, box.bottom), outline=(125, 80, 215, 210), width=1)
        for reading in result.readings:
            if reading.bounding_box:
                box = reading.bounding_box
                color = (76, 220, 144, 255) if reading.validation_status is ValidationStatus.VALID else (255, 177, 70, 255)
                draw.rectangle((box.x, box.y, box.right, box.bottom), outline=color, width=2)
        return copy

    def _calculation_updated(self, snapshot, result, quantity: int) -> None:
        request = snapshot.request_price.parsed_value if snapshot.request_price else None
        self.turnover_page.update_from_calculation(result, quantity, Decimal("5.00"))
        self.overlay.update_market(
            snapshot.item_name, request, result.average_price, result.net_sale_price,
            result.per_item_result, quantity, self.inventory.current_streak, self.reliability.state.value,
        )

    def _inventory_changed(self, _streak: int, _normal: int) -> None:
        if self.market_page.last_result:
            self._calculation_updated(
                self.market_page.analyzer.create_snapshot(
                    self.market_page.item_name.text(), _reading_from_text(self.market_page.request_price.text()),
                    [_reading_from_text(field.text()) for field in self.market_page.listing_prices],
                ), self.market_page.last_result, self.market_page.quantity.value(),
            )

    def emergency_stop(self) -> None:
        self.stop_capture()
        sticker_count, normal_count, started = self.inventory.reset_session()
        if sticker_count or normal_count:
            self.database.save_sticker_session(started, datetime.now(timezone.utc), sticker_count, normal_count)
        self.reliability.safe_stop()
        self.sell_page.reset_display()
        self.capture_page.set_status("Safe stop • F9 completed")
        self.market_page.set_capture_status("Safe stop • F9 completed")
        self.overlay.hide()

    def closeEvent(self, event) -> None:
        self.database.set_setting("window_geometry", bytes(self.saveGeometry().toBase64()).decode("ascii"))
        self.emergency_stop()
        self.hotkey.uninstall(QApplication.instance())
        self.database.close()
        super().closeEvent(event)
