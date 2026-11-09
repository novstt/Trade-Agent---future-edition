from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from PIL import Image, ImageDraw
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QPushButton, QScrollArea, QSpinBox,
    QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from trade_agent.calculator import DEFAULT_COMMISSION, ProfitEngine
from trade_agent.capture import CaptureWorker, WindowsCaptureProvider
from trade_agent.core.models import BoundingBox, CaptureFrame, PriceReading, ReliabilityState, ValidationStatus, WindowInfo
from trade_agent.inventory import InventoryAnalyzer, SellMenuDetector
from trade_agent.market import MarketAnalyzer, MarketPriceExtractor
from trade_agent.recognition import PriceRecognizer, RecognitionResult, TesseractOcrEngine
from trade_agent.reliability import ReliabilityManager
from trade_agent.storage import Database
from trade_agent.turnover import SkinTurnoverService
from trade_agent.interface.hotkey import GlobalF9Hotkey
from trade_agent.interface.overlay import CompactOverlay


def _money(value: Decimal | None) -> str:
    return "—" if value is None else f"{value.quantize(Decimal('0.01'))} G"


def _pixmap(image: Image.Image, target_size=None) -> QPixmap:
    rgba = image.convert("RGBA")
    buffer = rgba.tobytes("raw", "RGBA")
    qimage = QImage(buffer, rgba.width, rgba.height, rgba.width * 4, QImage.Format_RGBA8888).copy()
    pixmap = QPixmap.fromImage(qimage)
    if target_size and target_size.width() > 0 and target_size.height() > 0:
        return pixmap.scaled(target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return pixmap


def _card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame(objectName="card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(9)
    return frame, layout


def _heading(title: str, description: str) -> QVBoxLayout:
    layout = QVBoxLayout()
    label = QLabel(title, objectName="pageTitle")
    detail = QLabel(description, objectName="subtle")
    detail.setWordWrap(True)
    layout.addWidget(label)
    layout.addWidget(detail)
    return layout


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


class DashboardPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addLayout(_heading("Dashboard", "Live state for source, recognition, trading calculation, and Sell Menu session."))
        layout.addSpacing(10)
        grid = QGridLayout()
        self.metrics: dict[str, QLabel] = {}
        for index, title in enumerate(("Application", "Image source", "Recognition", "Current item", "Result / item", "Target quantity", "Sticker streak", "Recent activity")):
            card, card_layout = _card()
            name = QLabel(title, objectName="subtle")
            value = QLabel("—", objectName="metric")
            value.setWordWrap(True)
            card_layout.addWidget(name)
            card_layout.addWidget(value)
            self.metrics[title] = value
            grid.addWidget(card, index // 2, index % 2)
        layout.addLayout(grid)
        layout.addStretch()

    def update(self, **values: str) -> None:
        for name, value in values.items():
            if name in self.metrics:
                self.metrics[name].setText(value)


class CaptureMonitorPage(QWidget):
    start_requested = Signal(object)
    stop_requested = Signal()
    analyze_requested = Signal()

    def __init__(self, provider: WindowsCaptureProvider | None) -> None:
        super().__init__()
        self.provider = provider
        self.last_image: Image.Image | None = None
        root = QVBoxLayout(self)
        root.addLayout(_heading("Screen Capture Monitor", "Choose an allowed visible Windows source, confirm its real pixels, then inspect local OCR regions."))
        top, top_layout = _card()
        source_row = QHBoxLayout()
        self.window_combo = QComboBox()
        self.refresh_button = QPushButton("Refresh windows")
        self.start_button = QPushButton("Start capture", objectName="primary")
        self.stop_button = QPushButton("Stop")
        self.save_button = QPushButton("Save frame")
        source_row.addWidget(self.window_combo, 1)
        source_row.addWidget(self.refresh_button)
        source_row.addWidget(self.start_button)
        source_row.addWidget(self.stop_button)
        source_row.addWidget(self.save_button)
        top_layout.addLayout(source_row)
        self.auto_analyze = QCheckBox("Automatically analyse a sampled frame")
        self.auto_analyze.setChecked(True)
        self.show_overlay = QCheckBox("Show compact always-on-top overlay")
        option_row = QHBoxLayout()
        option_row.addWidget(self.auto_analyze)
        option_row.addWidget(self.show_overlay)
        option_row.addStretch()
        top_layout.addLayout(option_row)
        self.meta = QLabel("Status: STOPPED  •  No source selected", objectName="subtle")
        top_layout.addWidget(self.meta)
        root.addWidget(top)
        split = QHBoxLayout()
        preview_card, preview_layout = _card()
        preview_layout.addWidget(QLabel("Real capture preview"))
        self.preview = QLabel("No frame received yet")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(500, 360)
        self.preview.setStyleSheet("background:#0b0c12; border-radius: 7px; color:#8e8c9b;")
        preview_layout.addWidget(self.preview, 1)
        split.addWidget(preview_card, 3)
        diag_card, diag_layout = _card()
        diag_layout.addWidget(QLabel("Capture diagnostics"))
        self.diagnostics = QLabel("Title: —\nHWND: —\nResolution: —\nFPS: —\nLast successful frame: —\nOCR: waiting")
        self.diagnostics.setObjectName("subtle")
        self.diagnostics.setWordWrap(True)
        diag_layout.addWidget(self.diagnostics)
        diag_layout.addStretch()
        analyze = QPushButton("Analyse current frame", objectName="primary")
        analyze.clicked.connect(self.analyze_requested)
        diag_layout.addWidget(analyze)
        split.addWidget(diag_card, 1)
        root.addLayout(split, 1)
        self.refresh_button.clicked.connect(self.refresh_windows)
        self.start_button.clicked.connect(self._start)
        self.stop_button.clicked.connect(self.stop_requested)
        self.save_button.clicked.connect(self.save_frame)
        self.refresh_windows()

    def refresh_windows(self) -> None:
        self.window_combo.clear()
        if self.provider is None:
            self.window_combo.addItem("Windows capture unavailable")
            return
        try:
            windows = self.provider.enumerate_windows()
            for window in windows:
                self.window_combo.addItem(f"{window.title}  [{window.width}×{window.height}]", window)
            self.meta.setText(f"Status: STOPPED  •  {len(windows)} windows available")
        except Exception as exc:
            self.meta.setText(f"Status: ERROR  •  {exc}")

    def _start(self) -> None:
        window = self.window_combo.currentData()
        if isinstance(window, WindowInfo):
            self.start_requested.emit(window)
        else:
            self.meta.setText("Status: ERROR  •  Select a visible application window first.")

    def set_frame(self, frame: CaptureFrame, fps: float | None = None) -> None:
        self.last_image = frame.image
        self.preview.setPixmap(_pixmap(frame.image, self.preview.size()))
        fps_label = f"{fps:.1f}" if fps is not None else "—"
        self.diagnostics.setText(
            f"Title: {frame.source.title}\nHWND: {frame.source.hwnd}\nResolution: {frame.source.width}×{frame.source.height}"
            f"\nFPS: {fps_label}\nLast successful frame: {frame.timestamp.astimezone().strftime('%H:%M:%S')}\nOCR: waiting"
        )

    def set_annotated(self, image: Image.Image, result: RecognitionResult) -> None:
        self.preview.setPixmap(_pixmap(image, self.preview.size()))
        ocr = "ready" if result.ocr_available else "engine unavailable"
        suffix = f"\nOCR: {ocr}; {len(result.readings)} numeric candidates; {len(result.regions)} regions"
        self.diagnostics.setText(self.diagnostics.text().split("\nOCR:")[0] + suffix)

    def set_status(self, text: str) -> None:
        self.meta.setText(f"Status: {text}")

    def save_frame(self) -> None:
        if self.last_image is None:
            self.set_status("No real frame is available to save.")
            return
        folder = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "TradeAgent" / "captures"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"capture-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
        self.last_image.save(target)
        self.set_status(f"Saved real frame: {target}")


class MarketPage(QWidget):
    calculation_updated = Signal(object, object, int)

    def __init__(self, database: Database) -> None:
        super().__init__()
        self.database, self.analyzer, self.profit_engine = database, MarketAnalyzer(), ProfitEngine()
        root = QVBoxLayout(self)
        root.addLayout(_heading("Market Analyzer", "Only a complete set of ten valid listing values produces a market average. Cancel rows remain included."))
        controls, control_layout = _card()
        form = QFormLayout()
        self.item_name = QLineEdit("Detected item")
        self.request_price = QLineEdit()
        self.request_price.setPlaceholderText("Purchase request price")
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 99999)
        self.quantity.setValue(1)
        self.maximum_loss = QLineEdit("5.00")
        form.addRow("Item", self.item_name)
        form.addRow("Request price", self.request_price)
        form.addRow("Target quantity", self.quantity)
        form.addRow("Maximum loss / item", self.maximum_loss)
        control_layout.addLayout(form)
        self.calculate_button = QPushButton("Validate and calculate", objectName="primary")
        self.calculate_button.clicked.connect(self.calculate)
        control_layout.addWidget(self.calculate_button)
        root.addWidget(controls)
        listings, listing_layout = _card()
        listing_layout.addWidget(QLabel("Listing values (screen order; own Cancel rows are not excluded)"))
        grid = QGridLayout()
        self.listing_prices: list[QLineEdit] = []
        for index in range(10):
            box = QLineEdit()
            box.setPlaceholderText(f"Listing {index + 1}")
            self.listing_prices.append(box)
            grid.addWidget(QLabel(f"{index + 1:02}"), index // 2, (index % 2) * 2)
            grid.addWidget(box, index // 2, (index % 2) * 2 + 1)
        listing_layout.addLayout(grid)
        self.recognition_note = QLabel("No recognition result yet.", objectName="subtle")
        self.recognition_note.setWordWrap(True)
        listing_layout.addWidget(self.recognition_note)
        root.addWidget(listings)
        output, output_layout = _card()
        metric_grid = QGridLayout()
        self.outputs: dict[str, QLabel] = {}
        for index, title in enumerate(("Average price", "Net sale price", "Result / item", "Total hypothetical result", "Eligibility")):
            label = QLabel("—", objectName="metric")
            self.outputs[title] = label
            metric_grid.addWidget(QLabel(title, objectName="subtle"), index // 2, (index % 2) * 2)
            metric_grid.addWidget(label, index // 2, (index % 2) * 2 + 1)
        output_layout.addLayout(metric_grid)
        self.reason = QLabel("Awaiting ten prices.", objectName="subtle")
        output_layout.addWidget(self.reason)
        root.addWidget(output)
        root.addStretch()
        self.last_result = None

    def apply_recognition(self, request: PriceReading | None, listings: list[PriceReading], ocr_message: str) -> None:
        if request and request.parsed_value is not None:
            self.request_price.setText(str(request.parsed_value))
        for index, field in enumerate(self.listing_prices):
            field.setText(str(listings[index].parsed_value) if index < len(listings) and listings[index].parsed_value is not None else "")
        self.recognition_note.setText(
            f"{ocr_message} Extracted {len(listings)} listing candidates. Values marked low-confidence or stale remain invalid until re-read or corrected."
        )
        self.calculate()

    def calculate(self) -> None:
        try:
            max_loss = Decimal(self.maximum_loss.text().strip().replace(",", "."))
            if max_loss < 0:
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            self.reason.setText("Maximum loss must be a non-negative decimal number.")
            return
        snapshot = self.analyzer.create_snapshot(
            self.item_name.text().strip() or "Unnamed item", _reading_from_text(self.request_price.text()),
            [_reading_from_text(field.text()) for field in self.listing_prices],
        )
        result = self.profit_engine.calculate(snapshot, self.quantity.value(), max_loss, DEFAULT_COMMISSION)
        self.last_result = result
        self.outputs["Average price"].setText(_money(result.average_price))
        self.outputs["Net sale price"].setText(_money(result.net_sale_price))
        self.outputs["Result / item"].setText(_money(result.per_item_result))
        self.outputs["Total hypothetical result"].setText(_money(result.total_result))
        self.outputs["Eligibility"].setText("ELIGIBLE" if result.eligible else "NOT ELIGIBLE")
        result_label = self.outputs["Result / item"]
        result_label.setObjectName("profit" if result.per_item_result is not None and result.per_item_result >= 0 else "loss")
        result_label.style().unpolish(result_label)
        result_label.style().polish(result_label)
        self.reason.setText(result.reason)
        self.database.save_snapshot(snapshot)
        self.database.save_calculation(result)
        self.calculation_updated.emit(snapshot, result, self.quantity.value())


class SellMenuPage(QWidget):
    session_changed = Signal(int, int)

    def __init__(self, inventory: InventoryAnalyzer) -> None:
        super().__init__()
        self.inventory, self.detector = inventory, SellMenuDetector()
        root = QVBoxLayout(self)
        root.addLayout(_heading("Sell Menu", "This is an independent workflow. Sticker analysis is only performed after you explicitly analyse a Sell Menu capture."))
        card, card_layout = _card()
        self.analyse_button = QPushButton("Analyse current capture as Sell Menu", objectName="primary")
        self.status = QLabel("No Sell Menu frame analysed.", objectName="subtle")
        card_layout.addWidget(self.analyse_button)
        card_layout.addWidget(self.status)
        root.addWidget(card)
        stats = QGridLayout()
        self.streak = QLabel("0", objectName="metric")
        self.sticker_count = QLabel("0", objectName="metric")
        self.normal_count = QLabel("0", objectName="metric")
        for i, (title, label) in enumerate((("Current streak", self.streak), ("Sticker items", self.sticker_count), ("Normal items", self.normal_count))):
            box, box_layout = _card()
            box_layout.addWidget(QLabel(title, objectName="subtle"))
            box_layout.addWidget(label)
            stats.addWidget(box, 0, i)
        root.addLayout(stats)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Item", "Classification", "Confidence", "Source"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        root.addWidget(self.table, 1)

    def analyze_image(self, image: Image.Image | None) -> None:
        if image is None:
            self.status.setText("Capture a real Sell Menu frame first.")
            return
        cards = self.detector.detect_cards(image)
        added = 0
        for index, card in enumerate(cards):
            crop = image.crop((card.x, card.y, card.right, card.bottom))
            item = self.inventory.analyse_card(f"Sell card {index + 1}", crop, card)
            if item is not None:
                added += 1
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(item.name))
                self.table.setItem(row, 1, QTableWidgetItem("STICKER_ITEM" if item.has_sticker else "NORMAL_ITEM"))
                self.table.setItem(row, 2, QTableWidgetItem(f"{item.confidence:.0%}"))
                self.table.setItem(row, 3, QTableWidgetItem("Sell Menu capture"))
        self.streak.setText(str(self.inventory.current_streak))
        self.sticker_count.setText(str(len(self.inventory.sticker_items)))
        self.normal_count.setText(str(len(self.inventory.normal_items)))
        self.status.setText(f"Detected {len(cards)} card candidates; added {added} unique items. Market captures are never processed here automatically.")
        self.session_changed.emit(self.inventory.current_streak, len(self.inventory.normal_items))


class TurnoverPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.service = SkinTurnoverService()
        root = QVBoxLayout(self)
        root.addLayout(_heading("Skin Turnover", "Order and inventory-cycle planning remains distinct from the profit calculator."))
        card, layout = _card()
        self.text = QLabel("Run a valid market calculation to create a turnover scenario.")
        self.text.setWordWrap(True)
        self.text.setObjectName("subtle")
        layout.addWidget(self.text)
        root.addWidget(card)
        root.addStretch()

    def update_from_calculation(self, result, quantity: int, loss: Decimal) -> None:
        scenario = self.service.simulate(result, quantity, loss)
        self.text.setText(
            f"Target quantity: {scenario.target_quantity}\nMaximum loss per item: {_money(scenario.maximum_loss_per_item)}"
            f"\nProjected total: {_money(scenario.projected_total)}\nState: {scenario.cycle_note}"
        )


class HistoryPage(QWidget):
    def __init__(self, database: Database) -> None:
        super().__init__()
        self.database = database
        root = QVBoxLayout(self)
        root.addLayout(_heading("History", "Persisted local market snapshots and calculations."))
        refresh = QPushButton("Refresh history")
        refresh.clicked.connect(self.refresh)
        root.addWidget(refresh, alignment=Qt.AlignLeft)
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
    def __init__(self, database: Database) -> None:
        super().__init__()
        self.database = database
        root = QVBoxLayout(self)
        root.addLayout(_heading("Settings", "Local defaults. OCR and capture remain isolated providers."))
        card, layout = _card()
        form = QFormLayout()
        self.commission = QLineEdit(str(DEFAULT_COMMISSION * 100))
        self.frame_interval = QSpinBox()
        self.frame_interval.setRange(100, 5000)
        self.frame_interval.setValue(int(database.get_setting("capture_interval_ms", 350)))
        form.addRow("Commission (%)", self.commission)
        form.addRow("Capture interval (ms)", self.frame_interval)
        layout.addLayout(form)
        save = QPushButton("Save settings", objectName="primary")
        save.clicked.connect(self.save)
        layout.addWidget(save)
        self.note = QLabel("F9 is registered globally where Windows allows it.", objectName="subtle")
        layout.addWidget(self.note)
        root.addWidget(card)
        root.addStretch()

    def save(self) -> None:
        self.database.set_setting("capture_interval_ms", self.frame_interval.value())
        self.note.setText("Saved. The capture interval is applied when the next capture starts.")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Trade Agent")
        self.resize(1320, 850)
        app_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "TradeAgent"
        self.database = Database(app_data / "trade_agent.sqlite3")
        self.reliability = ReliabilityManager()
        self.inventory = InventoryAnalyzer()
        self.recognizer = PriceRecognizer(TesseractOcrEngine())
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
        self.statusBar().showMessage("Ready. Choose Screen Capture Monitor to select a source.")
        self.dashboard.update(**{"Application": "READY", "Recognition": "LOCAL OCR", "Recent activity": "Awaiting capture"})

    def _build_ui(self) -> None:
        container = QWidget()
        root = QHBoxLayout(container)
        root.setContentsMargins(0, 0, 0, 0)
        sidebar = QFrame(objectName="sidebar")
        sidebar.setFixedWidth(220)
        side_layout = QVBoxLayout(sidebar)
        brand = QLabel("TRADE AGENT", objectName="brand")
        side_layout.addWidget(brand)
        side_layout.addWidget(QLabel("LOCAL MARKET INTELLIGENCE", objectName="subtle"))
        self.navigation = QListWidget()
        self.navigation.addItems(["Dashboard", "Market Analyzer", "Sell Menu", "Skin Turnover", "Screen Capture Monitor", "History", "Settings"])
        side_layout.addWidget(self.navigation, 1)
        emergency = QPushButton("Emergency stop  F9", objectName="danger")
        emergency.clicked.connect(self.emergency_stop)
        side_layout.addWidget(emergency)
        side_layout.addWidget(QLabel("F9 global: active" if self.hotkey_active else "F9 global: unavailable", objectName="subtle"))
        root.addWidget(sidebar)
        self.pages = QStackedWidget()
        self.dashboard = DashboardPage()
        self.market_page = MarketPage(self.database)
        self.sell_page = SellMenuPage(self.inventory)
        self.turnover_page = TurnoverPage()
        self.capture_page = CaptureMonitorPage(self.provider)
        self.history_page = HistoryPage(self.database)
        self.settings_page = SettingsPage(self.database)
        for page in (self.dashboard, self.market_page, self.sell_page, self.turnover_page, self.capture_page, self.history_page, self.settings_page):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setWidget(page)
            self.pages.addWidget(scroll)
        root.addWidget(self.pages, 1)
        self.setCentralWidget(container)
        self.navigation.currentRowChanged.connect(self._navigate)
        self.navigation.setCurrentRow(0)
        self.capture_page.start_requested.connect(self.start_capture)
        self.capture_page.stop_requested.connect(self.stop_capture)
        self.capture_page.analyze_requested.connect(self.analyze_current_frame)
        self.capture_page.show_overlay.toggled.connect(self.overlay.setVisible)
        self.market_page.calculation_updated.connect(self._calculation_updated)
        self.sell_page.analyse_button.clicked.connect(lambda: self.sell_page.analyze_image(self.last_frame.image if self.last_frame else None))
        self.sell_page.session_changed.connect(self._inventory_changed)

    def _navigate(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        if index == 5:
            self.history_page.refresh()

    def start_capture(self, window: WindowInfo) -> None:
        self.stop_capture()
        if self.provider is None:
            self.capture_page.set_status("ERROR • Windows capture provider unavailable")
            return
        interval = int(self.database.get_setting("capture_interval_ms", 350))
        self.capture_worker = CaptureWorker(self.provider, window, interval)
        self.capture_worker.frame_captured.connect(self._frame_received)
        self.capture_worker.capture_error.connect(self._capture_error)
        self.capture_worker.status_changed.connect(self._capture_status)
        self.capture_worker.metrics_changed.connect(self._capture_metrics)
        self.capture_worker.start()
        self.capture_page.set_status(f"CAPTURING • {window.title}")
        self.dashboard.update(**{"Application": "CAPTURING", "Image source": window.title})

    def stop_capture(self) -> None:
        if self.capture_worker and self.capture_worker.isRunning():
            self.capture_worker.stop()
            self.capture_worker.wait(1800)
        self.capture_worker = None
        self.capture_page.set_status("STOPPED")
        self.dashboard.update(**{"Application": "STOPPED"})

    def _capture_status(self, status: str) -> None:
        self.capture_page.set_status(status)
        self.dashboard.update(**{"Application": status})

    def _capture_metrics(self, fps: float, _timestamp) -> None:
        self.current_fps = fps

    def _capture_error(self, message: str) -> None:
        state = self.reliability.record_error(message)
        self.database.log("WARNING", message)
        self.capture_page.set_status(f"{state.value} • {message}")
        self.dashboard.update(**{"Application": state.value, "Recent activity": message})
        if state is ReliabilityState.SAFE_STOP:
            self.stop_capture()

    def _frame_received(self, frame: CaptureFrame) -> None:
        self.last_frame = frame
        self.reliability.record_success(frame.timestamp)
        self.capture_page.set_frame(frame, self.current_fps)
        self.dashboard.update(**{"Application": "CAPTURING", "Image source": frame.source.title, "Recent activity": "Real frame received"})
        if self.capture_page.auto_analyze.isChecked() and not self.recognition_busy:
            self.analyze_current_frame()

    def analyze_current_frame(self) -> None:
        if self.last_frame is None:
            self.capture_page.set_status("No frame available for OCR.")
            return
        if self.recognition_busy:
            return
        self.recognition_busy = True
        task = RecognitionTask(self.recognizer, self.last_frame.image, self.last_frame.timestamp)
        task.signals.completed.connect(self._recognition_completed)
        self.thread_pool.start(task)
        self.capture_page.set_status("ANALYSING • local OCR")

    def _recognition_completed(self, result: RecognitionResult) -> None:
        self.recognition_busy = False
        if self.last_frame is None:
            return
        annotated = self._annotate(self.last_frame.image, result)
        self.capture_page.set_annotated(annotated, result)
        request, listings = self.extractor.extract(result, self.last_frame.source.width)
        message = result.error or ("Local OCR complete." if result.ocr_available else "Local OCR unavailable.")
        self.market_page.apply_recognition(request, listings, message)
        self.dashboard.update(**{"Recognition": f"{len(result.readings)} numeric candidates", "Recent activity": message})
        self.capture_page.set_status("CAPTURING • OCR updated" if self.capture_worker else "STOPPED • OCR updated")

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
                draw.text((box.x, max(0, box.y - 14)), f"{reading.raw_text} {reading.confidence:.0f}%", fill=color)
        return copy

    def _calculation_updated(self, snapshot, result, quantity: int) -> None:
        request = snapshot.request_price.parsed_value if snapshot.request_price else None
        self.dashboard.update(**{
            "Current item": snapshot.item_name,
            "Result / item": _money(result.per_item_result),
            "Target quantity": str(quantity),
            "Recent activity": result.reason,
        })
        try:
            maximum_loss = Decimal(self.market_page.maximum_loss.text().replace(",", "."))
        except InvalidOperation:
            maximum_loss = Decimal("0")
        self.turnover_page.update_from_calculation(result, quantity, maximum_loss)
        self.overlay.update_market(snapshot.item_name, request, result.average_price, result.net_sale_price,
                                   result.per_item_result, quantity, self.inventory.current_streak, self.reliability.state.value)

    def _inventory_changed(self, streak: int, normal: int) -> None:
        self.dashboard.update(**{"Sticker streak": str(streak), "Recent activity": f"Sell Menu: {streak} sticker items, {normal} normal items"})
        if self.market_page.last_result:
            self._calculation_updated(self.market_page.analyzer.create_snapshot(
                self.market_page.item_name.text(), _reading_from_text(self.market_page.request_price.text()),
                [_reading_from_text(field.text()) for field in self.market_page.listing_prices]
            ), self.market_page.last_result, self.market_page.quantity.value())

    def emergency_stop(self) -> None:
        self.stop_capture()
        sticker_count, normal_count, started = self.inventory.reset_session()
        if sticker_count or normal_count:
            self.database.save_sticker_session(started, datetime.now(timezone.utc), sticker_count, normal_count)
        self.reliability.safe_stop()
        self.capture_page.set_status("SAFE_STOP • F9 emergency stop completed")
        self.dashboard.update(**{"Application": "SAFE_STOP", "Sticker streak": "0", "Recent activity": "Capture and session processing stopped"})
        self.overlay.hide()
        self.statusBar().showMessage("Emergency stop complete: capture stopped, session saved, sticker streak reset.")

    def closeEvent(self, event) -> None:
        self.emergency_stop()
        self.hotkey.uninstall(QApplication.instance())
        self.database.close()
        super().closeEvent(event)

