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
    completed = Signal(object, object)


class RecognitionTask(QRunnable):
    def __init__(self, recognizer: PriceRecognizer, frame: CaptureFrame) -> None:
        super().__init__()
        self.recognizer = recognizer
        self.frame = CaptureFrame(frame.image.copy(), frame.source, frame.timestamp)
        self.signals = RecognitionSignals()

    def run(self) -> None:
        self.signals.completed.emit(self.recognizer.recognize(self.frame.image, self.frame.timestamp), self.frame)


class AnalyzerPage(QWidget):
    """Compact price panel mirroring the request row and the first ten market lots."""

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
        self._last_recognition_signature: tuple[str | None, tuple[str | None, ...]] | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(9, 8, 9, 8)
        root.setSpacing(6)
        header = QHBoxLayout()
        header.addWidget(QLabel("АНАЛИЗ РЫНКА", objectName="sectionTitle"))
        self.recognition_status = QLabel("ГОТОВО", objectName="statusChip")
        self.recognition_status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(self.recognition_status, 1)
        root.addLayout(header)

        self.item_name = QLineEdit("Распознанный предмет")
        self.request_price = QLineEdit()
        self.request_price.setObjectName("requestPrice")
        self.request_price.setPlaceholderText("—")
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 99999)
        self.quantity.setValue(1)
        self.average_value = QLabel("—", objectName="value")
        self.net_value = QLabel("—", objectName="value")
        self.profit_value = QLabel("—", objectName="neutralValue")
        self.total_value = QLabel("—", objectName="value")
        self.commission_value = QLabel(self._commission_text(), objectName="value")
        order_panel = QWidget(objectName="orderPanel")
        order = QHBoxLayout(order_panel)
        order.setContentsMargins(7, 5, 7, 5)
        order.setSpacing(8)
        order_text = QVBoxLayout()
        order_text.setSpacing(0)
        order_text.addWidget(QLabel("ЦЕНА ЗАКАЗА", objectName="orderCaption"))
        order_text.addWidget(QLabel("рядом с кнопкой «ЗАКАЗАТЬ»", objectName="subtle"))
        order.addLayout(order_text, 1)
        order.addWidget(self.request_price)
        order.addWidget(QLabel("G", objectName="currency"))
        root.addWidget(order_panel)

        lots_panel = QWidget(objectName="lotsPanel")
        lots = QVBoxLayout(lots_panel)
        lots.setContentsMargins(7, 5, 7, 5)
        lots.setSpacing(2)
        lots_header = QHBoxLayout()
        lots_header.addWidget(QLabel("ПЕРВЫЕ 10 ЛОТОВ", objectName="lotsCaption"))
        lots_header.addStretch()
        lots_header.addWidget(QLabel("ЦЕНА", objectName="lotsCaption"))
        lots.addLayout(lots_header)
        self.listing_prices: list[QLineEdit] = []
        for index in range(10):
            row = QWidget(objectName="lotRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(3, 1, 3, 1)
            row_layout.setSpacing(7)
            row_layout.addWidget(QLabel(f"ЛОТ {index + 1:02}", objectName="lotLabel"))
            row_layout.addStretch()
            field = QLineEdit()
            field.setObjectName("listingPrice")
            field.setPlaceholderText("—")
            field.setMaximumWidth(118)
            self.listing_prices.append(field)
            row_layout.addWidget(field)
            row_layout.addWidget(QLabel("G", objectName="currency"))
            lots.addWidget(row)
            field.editingFinished.connect(self.calculate)
        root.addWidget(lots_panel)

        summary = QGridLayout()
        summary.setHorizontalSpacing(8)
        summary.setVerticalSpacing(2)
        self._add_field(summary, 0, 0, "СРЕДНЕЕ / 10", self.average_value)
        self._add_field(summary, 0, 1, "ЧИСТАЯ ПРОДАЖА", self.net_value)
        self._add_field(summary, 1, 0, "ПРИБЫЛЬ / ШТ.", self.profit_value)
        self._add_field(summary, 1, 1, "ИТОГ", self.total_value)
        self._add_field(summary, 2, 0, "КОМИССИЯ", self.commission_value)
        self._add_field(summary, 2, 1, "КОЛИЧЕСТВО", self.quantity)
        root.addLayout(summary)

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
        controls.addWidget(self.stop_button)
        controls.addWidget(self.monitor_button)
        root.addLayout(controls)
        self.reason = QLabel("Ожидание 10 достоверных цен.", objectName="statusLine")
        self.reason.setWordWrap(False)
        root.addWidget(self.reason)
        self.item_name.setVisible(False)

        self.start_button.clicked.connect(self.start_requested)
        self.stop_button.clicked.connect(self.stop_requested)
        self.get_hwnd_button.clicked.connect(self.hwnd_requested)
        self.monitor_button.clicked.connect(self.monitor_requested)
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

    def set_commission_percent(self, percent: Decimal) -> None:
        self.commission = percent / Decimal("100")
        self.commission_value.setText(self._commission_text())
        self.calculate()

    def set_capture_status(self, text: str) -> None:
        self.recognition_status.setText(text)

    def set_hwnd(self, window: WindowInfo) -> None:
        self.selected_window = window
        self.hwnd_value.setText(f"HWND 0x{window.hwnd:X}")

    @staticmethod
    def _recognized_values_signature(
        request: PriceReading | None, listings: list[PriceReading],
    ) -> tuple[str | None, tuple[str | None, ...]]:
        request_value = str(request.parsed_value) if request and request.parsed_value is not None else None
        listing_values = tuple(
            str(reading.parsed_value) if reading.parsed_value is not None else None
            for reading in listings[:MarketAnalyzer.LISTING_COUNT]
        )
        return request_value, listing_values

    def apply_recognition(self, request: PriceReading | None, listings: list[PriceReading], ocr_message: str) -> bool:
        if request is None and not listings:
            if self._last_recognition_signature is None:
                self.set_capture_status("Цены не найдены")
                self.reason.setText(f"{ocr_message} Достоверные цены не найдены.")
            return False
        signature = self._recognized_values_signature(request, listings)
        if signature == self._last_recognition_signature:
            return False
        self._last_recognition_signature = signature
        if request and request.parsed_value is not None:
            self.request_price.setText(str(request.parsed_value))
        for index, field in enumerate(self.listing_prices):
            field.setText(str(listings[index].parsed_value) if index < len(listings) and listings[index].parsed_value is not None else "")
        self.set_capture_status(f"OCR • {len(listings)}/10 цен")
        self.reason.setText(ocr_message if listings else f"{ocr_message} Достоверные цены не найдены.")
        self.calculate()
        return True

    def calculate(self) -> None:
        snapshot = self.analyzer.create_snapshot(
            self.item_name.text().strip() or "Без названия", _reading_from_text(self.request_price.text()),
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
        self.refresh_button = QPushButton("Обновить")
        self.start_button = QPushButton("Старт", objectName="primary")
        self.stop_button = QPushButton("Стоп")
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
        self.auto_analyze = QCheckBox("Авто OCR")
        self.auto_analyze.setChecked(True)
        self.show_overlay = QCheckBox("Показать overlay")
        options.addWidget(self.auto_analyze)
        options.addWidget(self.show_overlay)
        options.addStretch()
        root.addLayout(options)
        self.meta = QLabel("Остановлено • выберите окно", objectName="subtle")
        root.addWidget(self.meta)
        self.preview = QLabel("Реальный кадр ещё не получен")
        self.preview.setObjectName("capturePreview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(220)
        root.addWidget(self.preview, 1)
        bottom = QHBoxLayout()
        self.diagnostics = QLabel("Источник: —\nРазрешение: —\nFPS: —\nOCR: ожидание", objectName="subtle")
        self.analyze_button = QPushButton("Проверить кадр")
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
            self.window_combo.addItem("Захват Windows недоступен")
            return
        try:
            for window in self.provider.enumerate_windows():
                self.window_combo.addItem(f"{window.title}  [{window.width}×{window.height}]", window)
            self.set_status(f"Остановлено • окон: {self.window_combo.count()}")
        except Exception as exc:
            self.set_status(f"Ошибка • {exc}")

    def _start(self) -> None:
        window = self.selected_window()
        if isinstance(window, WindowInfo):
            self.hwnd_ready.emit(window)
            self.start_requested.emit(window)
        else:
            self.set_status("Сначала выберите видимое окно")

    def selected_window(self) -> WindowInfo | None:
        window = self.window_combo.currentData()
        return window if isinstance(window, WindowInfo) else None

    def get_selected_hwnd(self) -> WindowInfo | None:
        window = self.selected_window()
        if window is None:
            self.set_status("Сначала выберите видимое окно")
            return None
        self.hwnd_input.setText(f"0x{window.hwnd:X}")
        self.hwnd_ready.emit(window)
        self.set_status(f"HWND получен • 0x{window.hwnd:X}")
        return window

    def _start_from_hwnd(self) -> None:
        if self.provider is None:
            self.set_status("Захват Windows недоступен")
            return
        try:
            window = self.provider.get_window_info(self.hwnd_input.text())
        except CaptureError as exc:
            self.set_status(f"Ошибка HWND • {exc}")
            return
        self.hwnd_ready.emit(window)
        self.start_requested.emit(window)

    def set_frame(self, frame: CaptureFrame, fps: float | None = None) -> None:
        self.last_image = frame.image
        self.preview.setPixmap(_pixmap(frame.image, self.preview.size()))
        self.diagnostics.setText(
            f"Источник: {frame.source.title}\nРазрешение: {frame.source.width}×{frame.source.height}  •  FPS: {fps or 0:.1f}"
            f"\nПоследний кадр: {frame.timestamp.astimezone().strftime('%H:%M:%S')}"
        )

    def set_annotated(self, image: Image.Image, result: RecognitionResult) -> None:
        self.preview.setPixmap(_pixmap(image, self.preview.size()))
        status = "готов" if result.ocr_available else "недоступен"
        self.diagnostics.setText(self.diagnostics.text().split("\nOCR:")[0] + f"\nOCR: {status}; цен: {len(result.readings)}")

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
        self.analyse_button = QPushButton("Проверить текущий кадр", objectName="primary")
        self.status = QLabel("Ожидание кадра из меню продажи", objectName="subtle")
        top.addWidget(self.analyse_button)
        top.addWidget(self.status, 1)
        root.addLayout(top)
        metrics = QHBoxLayout()
        self.streak = QLabel("0", objectName="value")
        self.sticker_count = QLabel("0", objectName="value")
        self.normal_count = QLabel("0", objectName="value")
        for label, value in (("Серия", self.streak), ("С наклейкой", self.sticker_count), ("Обычные", self.normal_count)):
            metrics.addWidget(QLabel(label, objectName="subtle"))
            metrics.addWidget(value)
        metrics.addStretch()
        root.addLayout(metrics)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Предмет", "Класс", "Точность"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        root.addWidget(self.table, 1)

    def analyze_image(self, image: Image.Image | None) -> None:
        if image is None:
            self.status.setText("Сначала получите реальный кадр меню продажи")
            return
        cards = self.detector.detect_cards(image)
        added = 0
        for index, card in enumerate(cards):
            crop = image.crop((card.x, card.y, card.right, card.bottom))
            item = self.inventory.analyse_card(f"Карточка продажи {index + 1}", crop, card)
            if item is None:
                continue
            added += 1
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(item.name))
            self.table.setItem(row, 1, QTableWidgetItem("С НАКЛЕЙКОЙ" if item.has_sticker else "ОБЫЧНЫЙ"))
            self.table.setItem(row, 2, QTableWidgetItem(f"{item.confidence:.0%}"))
        self._show_counts()
        self.status.setText(f"Кандидатов: {len(cards)} • новых предметов: {added}")
        self.session_changed.emit(self.inventory.current_streak, len(self.inventory.normal_items))

    def _show_counts(self) -> None:
        self.streak.setText(str(self.inventory.current_streak))
        self.sticker_count.setText(str(len(self.inventory.sticker_items)))
        self.normal_count.setText(str(len(self.inventory.normal_items)))

    def reset_display(self) -> None:
        self.table.setRowCount(0)
        self._show_counts()
        self.status.setText("Сессия остановлена")


class TurnoverPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.service = SkinTurnoverService()
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.addWidget(QLabel("ОБОРОТ", objectName="sectionTitle"))
        self.text = QLabel("Выполните расчёт рынка, чтобы построить сценарий.", objectName="subtle")
        self.text.setWordWrap(True)
        root.addWidget(self.text)
        root.addStretch()

    def update_from_calculation(self, result, quantity: int, loss: Decimal) -> None:
        scenario = self.service.simulate(result, quantity, loss)
        self.text.setText(
            f"Цель: {scenario.target_quantity}\nМакс. убыток / шт.: {_money(scenario.maximum_loss_per_item)}"
            f"\nОжидаемый результат: {_money(scenario.projected_total)}\n{scenario.cycle_note}"
        )


class HistoryPage(QWidget):
    def __init__(self, database: Database) -> None:
        super().__init__()
        self.database = database
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        top = QHBoxLayout()
        top.addWidget(QLabel("ИСТОРИЯ", objectName="sectionTitle"))
        refresh = QPushButton("Обновить")
        refresh.clicked.connect(self.refresh)
        top.addStretch()
        top.addWidget(refresh)
        root.addLayout(top)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Когда", "Тип", "Детали"])
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
        root.addWidget(QLabel("НАСТРОЙКИ", objectName="sectionTitle"))
        form = QFormLayout()
        self.commission = QLineEdit(str(database.get_setting("commission_percent", "20")))
        self.frame_interval = QSpinBox()
        self.frame_interval.setRange(100, 5000)
        self.frame_interval.setValue(int(database.get_setting("capture_interval_ms", 350)))
        form.addRow("Комиссия (%)", self.commission)
        form.addRow("Интервал захвата (мс)", self.frame_interval)
        root.addLayout(form)
        self.ocr_note = QLabel(self._ocr_message(), objectName="subtle")
        self.ocr_note.setWordWrap(True)
        root.addWidget(self.ocr_note)
        save = QPushButton("Сохранить", objectName="primary")
        save.clicked.connect(self.save)
        root.addWidget(save, alignment=Qt.AlignLeft)
        root.addStretch()

    def _ocr_message(self) -> str:
        if self.ocr_engine.is_available:
            return f"Tesseract: готов • {self.ocr_engine.executable_path}"
        return f"Tesseract не найден. Проверен путь: {self.ocr_engine.executable_path}. Установите его или добавьте в PATH; захват остаётся доступным."

    def save(self) -> None:
        try:
            percent = Decimal(self.commission.text().strip().replace(",", "."))
            if not Decimal("0") <= percent < Decimal("100"):
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            self.ocr_note.setText("Комиссия должна быть от 0 до 100, не включая 100.")
            return
        self.database.set_setting("commission_percent", str(percent))
        self.database.set_setting("capture_interval_ms", self.frame_interval.value())
        self.commission_changed.emit(percent)
        self.ocr_note.setText(f"Сохранено • {self._ocr_message()}")


class MainWindow(QMainWindow):
    TAB_NAMES = ("Анализ", "Продажа", "Оборот", "Монитор", "История", "Настройки")
    COMPACT_UI_VERSION = 3

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Trade Agent")
        self.setMinimumSize(420, 500)
        self.resize(470, 560)
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
        self.recognition_pending = False
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
        root.setContentsMargins(5, 6, 5, 6)
        root.setSpacing(6)
        nav = QWidget(objectName="topNav")
        nav_layout = QHBoxLayout(nav)
        nav_layout.setContentsMargins(3, 2, 3, 2)
        nav_layout.setSpacing(2)
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        self.tabs.setUsesScrollButtons(False)
        for name in self.TAB_NAMES:
            self.tabs.addTab(name)
        nav_layout.addWidget(self.tabs, 1)
        self.always_on_top = QPushButton("↑", objectName="alwaysOnTop")
        self.always_on_top.setCheckable(True)
        self.always_on_top.setFixedWidth(18)
        self.always_on_top.setToolTip("Поверх всех окон")
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
            self.market_page.set_capture_status("Захват недоступен")
            return
        if self.market_page.selected_window is not None:
            try:
                self.start_capture(self.provider.get_window_info(self.market_page.selected_window.hwnd))
            except CaptureError as exc:
                self.market_page.set_capture_status(f"Ошибка HWND • {exc}")
            return
        window = self.capture_page.get_selected_hwnd()
        if isinstance(window, WindowInfo):
            self.start_capture(window)
        else:
            self.market_page.set_capture_status("Выберите источник в Мониторе")
            self.tabs.setCurrentIndex(3)

    def _get_selected_hwnd(self) -> None:
        window = self.capture_page.get_selected_hwnd()
        if window is None:
            self.market_page.set_capture_status("Выберите источник в Мониторе")
            self.tabs.setCurrentIndex(3)
        else:
            self.market_page.set_hwnd(window)
            self.market_page.set_capture_status("HWND готов")

    def start_capture(self, window: WindowInfo) -> None:
        self.stop_capture()
        if self.provider is None:
            self.capture_page.set_status("Ошибка • захват Windows недоступен")
            self.market_page.set_capture_status("Захват недоступен")
            return
        interval = int(self.database.get_setting("capture_interval_ms", 350))
        self.capture_worker = CaptureWorker(self.provider, window, interval)
        self.recognition_pending = False
        self.capture_worker.frame_captured.connect(self._frame_received)
        self.capture_worker.capture_error.connect(self._capture_error)
        self.capture_worker.status_changed.connect(self._capture_status)
        self.capture_worker.metrics_changed.connect(self._capture_metrics)
        self.capture_worker.start()
        self.capture_page.set_status(f"Захват • {window.title}")
        self.market_page.set_capture_status("Захват • ожидание кадра")

    def stop_capture(self) -> None:
        if self.capture_worker and self.capture_worker.isRunning():
            self.capture_worker.stop()
            self.capture_worker.wait(1800)
        self.capture_worker = None
        self.capture_page.set_status("Остановлено")
        self.market_page.set_capture_status("Остановлено")

    def _capture_status(self, status: str) -> None:
        localized = {
            "CAPTURING": "Захват",
            "DEGRADED": "Снижение надёжности",
            "STOPPED": "Остановлено",
        }.get(status, status)
        self.capture_page.set_status(localized)
        self.market_page.set_capture_status(localized)

    def _capture_metrics(self, fps: float, _timestamp) -> None:
        self.current_fps = fps

    def _capture_error(self, message: str) -> None:
        state = self.reliability.record_error(message)
        self.database.log("WARNING", message)
        localized_state = {
            ReliabilityState.NORMAL: "Нормально",
            ReliabilityState.DEGRADED: "Снижение надёжности",
            ReliabilityState.RECOVERY: "Восстановление",
            ReliabilityState.SAFE_STOP: "Безопасная остановка",
        }[state]
        self.capture_page.set_status(f"{localized_state} • {message}")
        self.market_page.set_capture_status(f"{localized_state} • ошибка захвата")
        if state is ReliabilityState.SAFE_STOP:
            self.stop_capture()

    def _frame_received(self, frame: CaptureFrame) -> None:
        self.last_frame = frame
        self.reliability.record_success(frame.timestamp)
        self.capture_page.set_frame(frame, self.current_fps)
        if not self.capture_page.auto_analyze.isChecked():
            self.market_page.set_capture_status("Кадр изменился • авто-OCR выключен")
        elif self.recognition_busy:
            self.recognition_pending = True
        else:
            self.analyze_current_frame(frame)

    def analyze_current_frame(self, frame: CaptureFrame | None = None) -> None:
        frame = frame or self.last_frame
        if frame is None:
            self.capture_page.set_status("Нет кадра для OCR")
            return
        if self.recognition_busy:
            return
        self.recognition_busy = True
        task = RecognitionTask(self.recognizer, frame)
        task.signals.completed.connect(self._recognition_completed)
        self.thread_pool.start(task)
        self.market_page.set_capture_status("Анализ • локальный OCR")

    def _recognition_completed(self, result: RecognitionResult, frame: CaptureFrame) -> None:
        self.recognition_busy = False
        request, listings = self.extractor.extract(result, frame.source.width)
        message = result.error or ("Локальный OCR завершён" if result.ocr_available else "Локальный OCR недоступен")
        if self.market_page.apply_recognition(request, listings, message):
            self.capture_page.set_annotated(self._annotate(frame.image, result), result)
            self.capture_page.set_status("Захват • цены обновлены" if self.capture_worker else "Остановлено • цены обновлены")
        if self.recognition_pending and self.last_frame is not None and self.last_frame.timestamp != frame.timestamp:
            self.recognition_pending = False
            self.analyze_current_frame(self.last_frame)
        else:
            self.recognition_pending = False

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
        reliability_label = {
            ReliabilityState.NORMAL: "Нормально",
            ReliabilityState.DEGRADED: "Снижение надёжности",
            ReliabilityState.RECOVERY: "Восстановление",
            ReliabilityState.SAFE_STOP: "Безопасная остановка",
        }[self.reliability.state]
        self.overlay.update_market(
            snapshot.item_name, request, result.average_price, result.net_sale_price,
            result.per_item_result, quantity, self.inventory.current_streak, reliability_label,
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
        self.capture_page.set_status("Безопасная остановка • F9 выполнена")
        self.market_page.set_capture_status("Безопасная остановка • F9 выполнена")
        self.overlay.hide()

    def closeEvent(self, event) -> None:
        self.database.set_setting("window_geometry", bytes(self.saveGeometry().toBase64()).decode("ascii"))
        self.emergency_stop()
        self.hotkey.uninstall(QApplication.instance())
        self.database.close()
        super().closeEvent(event)
