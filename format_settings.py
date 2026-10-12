from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFontComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


PRESETS = {
    "A4 - 2 x 5": {
        "page_width": 210, "page_height": 297, "columns": 2, "rows": 5,
        "margin_left": 10, "margin_top": 10, "gap_x": 3, "gap_y": 3,
        "sender_height_percent": 34, "sender_base_size": 9, "sender_min_size": 6,
    },
    "A4 - 3 x 8": {
        "page_width": 210, "page_height": 297, "columns": 3, "rows": 8,
        "margin_left": 8, "margin_top": 10, "gap_x": 2, "gap_y": 2,
        "sender_height_percent": 34, "sender_base_size": 9, "sender_min_size": 6,
    },
}


def load_formats(storage_path: Path) -> dict[str, dict]:
    if storage_path.exists():
        try:
            formats = json.loads(storage_path.read_text(encoding="utf-8"))
            if isinstance(formats, dict) and formats:
                return formats
        except (OSError, json.JSONDecodeError):
            pass
    return dict(PRESETS)


@dataclass
class LabelFormat:
    name: str
    page_width: float = 210
    page_height: float = 297
    columns: int = 2
    rows: int = 5
    margin_left: float = 10
    margin_top: float = 10
    gap_x: float = 3
    gap_y: float = 3
    sender_height_percent: float = 34
    sender_base_size: float = 9
    sender_min_size: float = 6
    sender_offset_x: float = 0
    sender_offset_y: float = 0
    recipient_offset_x: float = 0
    recipient_offset_y: float = 0
    sender_width: float = 96
    recipient_width: float = 96
    recipient_height: float = 60
    sender_font_family: str = "DejaVu Sans Condensed"
    sender_font_size: float = 9
    sender_bold: bool = True
    sender_italic: bool = False
    recipient_font_family: str = "DejaVu Sans"
    recipient_font_size: float = 15
    recipient_bold: bool = True
    recipient_italic: bool = False
    sender_enabled: bool = True
    sender_alignment: str = "center"
    recipient_alignment: str = "center"
    sender_vertical_alignment: str = "top"
    recipient_vertical_alignment: str = "center"
    start_column: int = 1
    start_row: int = 1
    label_width: float | None = None
    label_height: float | None = None


def alignment_flag(value: str, vertical: Qt.AlignmentFlag) -> Qt.AlignmentFlag:
    horizontal = {
        "left": Qt.AlignmentFlag.AlignLeft,
        "right": Qt.AlignmentFlag.AlignRight,
    }.get(value, Qt.AlignmentFlag.AlignHCenter)
    return horizontal | vertical


def vertical_alignment_flag(value: str) -> Qt.AlignmentFlag:
    return {
        "top": Qt.AlignmentFlag.AlignTop,
        "bottom": Qt.AlignmentFlag.AlignBottom,
    }.get(value, Qt.AlignmentFlag.AlignVCenter)


class FormatPreview(QWidget):
    positionChanged = Signal(int, int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.format = LabelFormat("Aperçu")
        self.dragging_start = False
        self.setMinimumSize(300, 360)

    def set_format(self, label_format: LabelFormat) -> None:
        self.format = label_format
        self.update()

    def page_geometry(self) -> tuple[QRectF, float, float, float]:
        page = QRectF(24, 16, self.width() - 48, self.height() - 32)
        scale = min(page.width() / self.format.page_width,
                    page.height() / self.format.page_height)
        page.setWidth(self.format.page_width * scale)
        page.setHeight(self.format.page_height * scale)
        page.moveCenter(QRectF(self.rect()).center())
        label_width = self.format.label_width
        if label_width is None:
            available_width = self.format.page_width - self.format.margin_left * 2
            label_width = (available_width - self.format.gap_x * (self.format.columns - 1)) / self.format.columns
        label_height = self.format.label_height
        if label_height is None:
            available_height = self.format.page_height - self.format.margin_top * 2
            label_height = (available_height - self.format.gap_y * (self.format.rows - 1)) / self.format.rows
        return page, scale, label_width, label_height

    def label_rect(self, column: int, row: int) -> QRectF:
        page, scale, label_width, label_height = self.page_geometry()
        x = self.format.margin_left + (column - 1) * (label_width + self.format.gap_x)
        y = self.format.margin_top + (row - 1) * (label_height + self.format.gap_y)
        return QRectF(page.left() + x * scale, page.top() + y * scale,
                      label_width * scale, label_height * scale)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        page, scale, label_width, label_height = self.page_geometry()
        painter.fillRect(page, Qt.GlobalColor.white)
        painter.setPen(QPen(Qt.GlobalColor.darkGray, 1))
        painter.drawRect(page)

        painter.setPen(QPen(Qt.GlobalColor.black, 1))
        for row in range(self.format.rows):
            for column in range(self.format.columns):
                x = self.format.margin_left + column * (label_width + self.format.gap_x)
                y = self.format.margin_top + row * (label_height + self.format.gap_y)
                painter.drawRect(QRectF(page.left() + x * scale, page.top() + y * scale,
                                        label_width * scale, label_height * scale))
        marker_rect = self.label_rect(self.format.start_column, self.format.start_row)
        painter.setPen(QPen(Qt.GlobalColor.red, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(marker_rect.adjusted(2, 2, -2, -2))
        painter.setFont(QFont("DejaVu Sans", max(8, int(marker_rect.height() * 0.4))))
        painter.drawText(marker_rect, Qt.AlignmentFlag.AlignCenter, "1*")

    def mousePressEvent(self, event) -> None:
        for row in range(1, self.format.rows + 1):
            for column in range(1, self.format.columns + 1):
                if self.label_rect(column, row).contains(event.position()):
                    self.dragging_start = True
                    self.format.start_column = column
                    self.format.start_row = row
                    self.positionChanged.emit(column, row)
                    self.update()
                    event.accept()
                    return
        event.ignore()

    def mouseMoveEvent(self, event) -> None:
        if not self.dragging_start:
            return
        for row in range(1, self.format.rows + 1):
            for column in range(1, self.format.columns + 1):
                if self.label_rect(column, row).contains(event.position()):
                    if (column, row) != (self.format.start_column, self.format.start_row):
                        self.format.start_column = column
                        self.format.start_row = row
                        self.positionChanged.emit(column, row)
                        self.update()
                    return

    def mouseReleaseEvent(self, event) -> None:
        self.dragging_start = False
        event.accept()


class PositionCanvas(QWidget):
    ZOOM_LEVELS = (1.0, 1.5, 2.0)
    LOGICAL_WIDTH = 100
    LOGICAL_HEIGHT = 60

    def __init__(self, label_format: LabelFormat, sender_text: str = "Expéditeur",
                 recipient_text: str = "Destinataire", parent: QWidget | None = None):
        super().__init__(parent)
        self.format = label_format
        self.sender_text = sender_text
        self.recipient_text = recipient_text
        self.active = ""
        self.drag_mode = ""
        self.drag_start = None
        self.original_offset = (0.0, 0.0)
        self.original_size = (0.0, 0.0)
        self.zoom = 1.0
        self.setMinimumSize(560, 360)
        self.resize(self.canvas_size())

    def screen_dpi(self) -> float:
        screen = self.screen()
        if screen is None:
            screen = self.window().windowHandle().screen() if self.window().windowHandle() else None
        if screen is None:
            return 96
        dpi = screen.physicalDotsPerInchX() / screen.devicePixelRatio()
        return dpi if 72 <= dpi <= 300 else 96

    def scale_and_page(self) -> tuple[float, QRectF]:
        scale = self.screen_dpi() / 25.4 * self.zoom
        width_mm, height_mm = self.label_dimensions()
        page = QRectF(40, 40, width_mm * scale, height_mm * scale)
        return scale, page

    def label_dimensions(self) -> tuple[float, float]:
        width = self.format.label_width
        height = self.format.label_height
        if width is None:
            width = ((self.format.page_width - self.format.margin_left * 2
                      - self.format.gap_x * (self.format.columns - 1))
                     / self.format.columns)
        if height is None:
            height = ((self.format.page_height - self.format.margin_top * 2
                       - self.format.gap_y * (self.format.rows - 1))
                      / self.format.rows)
        return width, height

    def logical_scales(self, page: QRectF) -> tuple[float, float]:
        return page.width() / self.LOGICAL_WIDTH, page.height() / self.LOGICAL_HEIGHT

    def canvas_size(self) -> QSize:
        _, page = self.scale_and_page()
        return QSize(max(560, round(page.right() + 40)),
                     max(360, round(page.bottom() + 40)))

    def set_zoom(self, value: float) -> None:
        self.zoom = min(self.ZOOM_LEVELS, key=lambda level: abs(level - value))
        self.resize(self.canvas_size())
        self.update()

    def set_format(self, label_format: LabelFormat) -> None:
        self.format = label_format
        self.update()

    def geometry_for(self, element: str) -> QRectF:
        _, origin = self.scale_and_page()
        scale_x, scale_y = self.logical_scales(origin)
        if element == "sender":
            sender_height = max(10, min(28, self.format.sender_height_percent * 0.5))
            return QRectF(origin.left() + (2 + self.format.sender_offset_x) * scale_x,
                          origin.top() + (6 + self.format.sender_offset_y) * scale_y,
                          self.format.sender_width * scale_x, sender_height * scale_y)
        return QRectF(origin.left() + (2 + self.format.recipient_offset_x) * scale_x,
                      origin.top() + (22 + self.format.recipient_offset_y) * scale_y,
                      self.format.recipient_width * scale_x,
                      self.format.recipient_height * 0.6 * scale_y)

    def base_geometry(self, element: str) -> tuple[float, float, float, float]:
        if element == "sender":
            sender_height = max(10, min(28, self.format.sender_height_percent * 0.5))
            return 2, 6, self.format.sender_width, sender_height
        return 2, 22, self.format.recipient_width, self.format.recipient_height * 0.6

    def handle_rect(self, element: str) -> QRectF:
        rect = self.geometry_for(element)
        return QRectF(rect.right() - 8, rect.bottom() - 8, 16, 16)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        _, page = self.scale_and_page()
        scale_x, scale_y = self.logical_scales(page)
        painter.fillRect(page, Qt.GlobalColor.white)
        painter.setPen(QPen(Qt.GlobalColor.darkGray, 1))
        painter.drawRect(page)
        painter.setPen(QPen(Qt.GlobalColor.lightGray, 1))
        for x in range(0, self.LOGICAL_WIDTH + 1, 2):
            for y in range(0, self.LOGICAL_HEIGHT + 1, 2):
                painter.drawPoint(page.left() + x * scale_x, page.top() + y * scale_y)
        for element, color, text in (("sender", Qt.GlobalColor.darkBlue, "Expéditeur"),
                                     ("recipient", Qt.GlobalColor.darkGreen, "Destinataire")):
            if element == "sender" and not self.format.sender_enabled:
                continue
            rect = self.geometry_for(element)
            painter.setPen(QPen(color, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            painter.setBrush(color)
            painter.drawRect(self.handle_rect(element))
            family = getattr(self.format, f"{element}_font_family")
            size = getattr(self.format, f"{element}_font_size")
            font = QFont(family, int(size))
            font.setBold(getattr(self.format, f"{element}_bold"))
            font.setItalic(getattr(self.format, f"{element}_italic"))
            painter.setFont(font)
            sample = self.sender_text if element == "sender" else self.recipient_text
            minimum_size = 4
            for fitted_size in range(font.pointSize(), minimum_size - 1, -1):
                font.setPointSize(fitted_size)
                bounds = QFontMetricsF(font).boundingRect(
                    rect.adjusted(3, 3, -3, -3),
                    int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap), sample
                )
                if bounds.width() <= rect.width() - 6 and bounds.height() <= rect.height() - 6:
                    break
            painter.setFont(font)
            painter.drawText(
                rect.adjusted(3, 3, -3, -3),
                alignment_flag(
                    getattr(self.format, f"{element}_alignment"),
                    vertical_alignment_flag(
                        getattr(self.format, f"{element}_vertical_alignment")
                    ),
                ) | Qt.TextFlag.TextWordWrap,
                sample,
            )

    def mousePressEvent(self, event) -> None:
        for element in ("recipient", "sender"):
            if self.handle_rect(element).contains(event.position()):
                self.active = element
                self.drag_mode = "resize"
                self.drag_start = event.position()
                self.original_offset = (
                    getattr(self.format, f"{element}_offset_x"),
                    getattr(self.format, f"{element}_offset_y"),
                )
                _, _, width, height = self.base_geometry(element)
                self.original_size = (width, height)
                return
        for element in ("recipient", "sender"):
            if self.geometry_for(element).contains(event.position()):
                self.active = element
                self.drag_mode = "move"
                self.drag_start = event.position()
                self.original_offset = (
                    getattr(self.format, f"{element}_offset_x"),
                    getattr(self.format, f"{element}_offset_y"),
                )
                return

    def mouseMoveEvent(self, event) -> None:
        if not self.active or self.drag_start is None:
            return
        _, page = self.scale_and_page()
        scale_x, scale_y = self.logical_scales(page)
        delta = event.position() - self.drag_start
        base_x, base_y, element_width, element_height = self.base_geometry(self.active)
        if self.drag_mode == "resize":
            original_width, original_height = self.original_size
            new_width = self.snap_size(original_width + delta.x() / scale_x)
            new_height = self.snap_size(original_height + delta.y() / scale_y)
            new_width = max(30, min(self.LOGICAL_WIDTH - base_x, new_width))
            new_height = max(10, min(self.LOGICAL_HEIGHT - base_y, new_height))
            if self.active == "sender":
                self.format.sender_width = new_width
                self.format.sender_height_percent = new_height * 2
            else:
                self.format.recipient_width = new_width
                self.format.recipient_height = new_height / 0.6
            self.clamp_offsets()
            self.update()
            return
        new_x = self.original_offset[0] + delta.x() / scale_x
        new_y = self.original_offset[1] + delta.y() / scale_y
        new_x = self.snap_size(new_x)
        new_y = self.snap_size(new_y)
        new_x = max(-base_x, min(new_x, self.LOGICAL_WIDTH - base_x - element_width))
        new_y = max(-base_y, min(new_y, self.LOGICAL_HEIGHT - base_y - element_height))
        setattr(self.format, f"{self.active}_offset_x", new_x)
        setattr(self.format, f"{self.active}_offset_y", new_y)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        del event
        self.active = ""
        self.drag_mode = ""

    @staticmethod
    def snap_size(value: float) -> float:
        return round(value * 2) / 2

    def clamp_offsets(self) -> None:
        for element in ("sender", "recipient"):
            base_x, base_y, element_width, element_height = self.base_geometry(element)
            offset_x = max(-base_x, min(getattr(self.format, f"{element}_offset_x"),
                                       self.LOGICAL_WIDTH - base_x - element_width))
            offset_y = max(-base_y, min(getattr(self.format, f"{element}_offset_y"),
                                       self.LOGICAL_HEIGHT - base_y - element_height))
            setattr(self.format, f"{element}_offset_x", offset_x)
            setattr(self.format, f"{element}_offset_y", offset_y)


class PositionEditorDialog(QDialog):
    def __init__(self, label_format: LabelFormat, sender_text: str = "Expéditeur",
                 recipient_text: str = "Destinataire", parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Ajuster les positions")
        self.resize(640, 460)
        self.canvas = PositionCanvas(label_format, sender_text, recipient_text, self)
        self.sender_height = self._number(label_format.sender_height_percent, 10, 70)
        self.sender_enabled = QCheckBox("Afficher l’expéditeur")
        self.sender_enabled.setChecked(label_format.sender_enabled)
        self.sender_font = QFontComboBox()
        self.sender_font.setCurrentFont(QFont(label_format.sender_font_family))
        self.sender_size = self._number(label_format.sender_font_size, 4, 40)
        self.sender_bold = QCheckBox("Gras")
        self.sender_bold.setChecked(label_format.sender_bold)
        self.sender_italic = QCheckBox("Italique")
        self.sender_italic.setChecked(label_format.sender_italic)
        self.sender_alignment = self._alignment(label_format.sender_alignment)
        self.sender_vertical_alignment = self._vertical_alignment(label_format.sender_vertical_alignment)
        self.recipient_font = QFontComboBox()
        self.recipient_font.setCurrentFont(QFont(label_format.recipient_font_family))
        self.recipient_size = self._number(label_format.recipient_font_size, 4, 40)
        self.recipient_bold = QCheckBox("Gras")
        self.recipient_bold.setChecked(label_format.recipient_bold)
        self.recipient_italic = QCheckBox("Italique")
        self.recipient_italic.setChecked(label_format.recipient_italic)
        self.recipient_alignment = self._alignment(label_format.recipient_alignment)
        self.recipient_vertical_alignment = self._vertical_alignment(label_format.recipient_vertical_alignment)
        for control in (self.sender_enabled, self.sender_height, self.sender_font, self.sender_size,
                self.sender_bold, self.sender_italic, self.sender_alignment,
                self.sender_vertical_alignment,
                self.recipient_font, self.recipient_size, self.recipient_bold,
                self.recipient_italic, self.recipient_alignment,
                self.recipient_vertical_alignment):
            if hasattr(control, "valueChanged"):
                control.valueChanged.connect(self.update_sender_settings)
            if hasattr(control, "currentFontChanged"):
                control.currentFontChanged.connect(self.update_sender_settings)
            if hasattr(control, "currentIndexChanged"):
                control.currentIndexChanged.connect(self.update_sender_settings)
            if hasattr(control, "stateChanged"):
                control.stateChanged.connect(self.update_sender_settings)
        instructions = QLabel("Faites glisser les blocs Expéditeur et Destinataire dans l'étiquette.")
        dpi_label = QLabel(f"DPI : {self.canvas.screen_dpi():.0f}")
        zoom_buttons = []
        zoom_value = QLabel("x1")
        for level in PositionCanvas.ZOOM_LEVELS:
            button = QPushButton(f"x{level:g}".replace(".", ","))
            button.setCheckable(True)
            button.clicked.connect(lambda checked, value=level: self.set_canvas_zoom(value))
            zoom_buttons.append(button)
        self.zoom_buttons = zoom_buttons
        self.zoom_value = zoom_value
        zoom_buttons[0].setChecked(True)
        zoom_controls = QHBoxLayout()
        zoom_controls.addWidget(dpi_label)
        zoom_controls.addWidget(QLabel("Zoom"))
        for button in zoom_buttons:
            zoom_controls.addWidget(button)
        zoom_controls.addWidget(zoom_value)
        zoom_controls.addStretch()
        reset_button = QPushButton("Réinitialiser")
        reset_button.clicked.connect(self.reset_positions)
        apply_button = QPushButton("Valider")
        apply_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Annuler")
        cancel_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(reset_button)
        buttons.addStretch()
        buttons.addWidget(cancel_button)
        buttons.addWidget(apply_button)
        layout = QVBoxLayout(self)
        layout.addWidget(instructions)
        settings = QFormLayout()
        settings.addRow(self.sender_enabled)
        settings.addRow("Hauteur expéditeur (%)", self.sender_height)
        settings.addRow("Police expéditeur", self.sender_font)
        sender_style = QHBoxLayout()
        sender_style.addWidget(self.sender_size)
        sender_style.addWidget(self.sender_bold)
        sender_style.addWidget(self.sender_italic)
        sender_style.addWidget(self.sender_alignment)
        sender_style.addWidget(self.sender_vertical_alignment)
        settings.addRow("Style expéditeur", sender_style)
        settings.addRow("Police destinataire", self.recipient_font)
        recipient_style = QHBoxLayout()
        recipient_style.addWidget(self.recipient_size)
        recipient_style.addWidget(self.recipient_bold)
        recipient_style.addWidget(self.recipient_italic)
        recipient_style.addWidget(self.recipient_alignment)
        recipient_style.addWidget(self.recipient_vertical_alignment)
        settings.addRow("Style destinataire", recipient_style)
        layout.addLayout(settings)
        layout.addLayout(zoom_controls)
        canvas_scroll = QScrollArea()
        canvas_scroll.setWidgetResizable(False)
        canvas_scroll.setWidget(self.canvas)
        layout.addWidget(canvas_scroll, 1)
        layout.addLayout(buttons)

    def set_canvas_zoom(self, value: float) -> None:
        self.canvas.set_zoom(value)
        self.zoom_value.setText(f"x{self.canvas.zoom:g}".replace(".", ","))
        for level, button in zip(PositionCanvas.ZOOM_LEVELS, self.zoom_buttons):
            button.setChecked(abs(level - self.canvas.zoom) < 0.01)

    @staticmethod
    def _number(value: float, minimum: float, maximum: float) -> QDoubleSpinBox:
        control = QDoubleSpinBox()
        control.setRange(minimum, maximum)
        control.setValue(value)
        control.setDecimals(1)
        control.setSingleStep(1)
        return control

    @staticmethod
    def _alignment(value: str) -> QComboBox:
        control = QComboBox()
        for label, data in (("Gauche", "left"), ("Centré", "center"), ("Droite", "right")):
            control.addItem(label, data)
        index = control.findData(value)
        control.setCurrentIndex(index if index >= 0 else 1)
        return control

    @staticmethod
    def _vertical_alignment(value: str) -> QComboBox:
        control = QComboBox()
        for label, data in (("Haut", "top"), ("Centré", "center"), ("Bas", "bottom")):
            control.addItem(label, data)
        index = control.findData(value)
        control.setCurrentIndex(index if index >= 0 else 1)
        return control

    def update_sender_settings(self) -> None:
        self.canvas.format.sender_enabled = self.sender_enabled.isChecked()
        self.canvas.format.sender_height_percent = self.sender_height.value()
        self.canvas.format.sender_font_family = self.sender_font.currentFont().family()
        self.canvas.format.sender_font_size = self.sender_size.value()
        self.canvas.format.sender_bold = self.sender_bold.isChecked()
        self.canvas.format.sender_italic = self.sender_italic.isChecked()
        self.canvas.format.sender_alignment = self.sender_alignment.currentData()
        self.canvas.format.sender_vertical_alignment = self.sender_vertical_alignment.currentData()
        self.canvas.format.recipient_font_family = self.recipient_font.currentFont().family()
        self.canvas.format.recipient_font_size = self.recipient_size.value()
        self.canvas.format.recipient_bold = self.recipient_bold.isChecked()
        self.canvas.format.recipient_italic = self.recipient_italic.isChecked()
        self.canvas.format.recipient_alignment = self.recipient_alignment.currentData()
        self.canvas.format.recipient_vertical_alignment = self.recipient_vertical_alignment.currentData()
        self.canvas.clamp_offsets()
        self.canvas.update()

    def reset_positions(self) -> None:
        defaults = LabelFormat("Défauts")
        for element in ("sender", "recipient"):
            setattr(self.canvas.format, f"{element}_offset_x", 0.0)
            setattr(self.canvas.format, f"{element}_offset_y", 0.0)
        self.canvas.format.sender_enabled = defaults.sender_enabled
        self.canvas.format.sender_font_family = defaults.sender_font_family
        self.canvas.format.sender_font_size = defaults.sender_font_size
        self.canvas.format.sender_bold = defaults.sender_bold
        self.canvas.format.sender_italic = defaults.sender_italic
        self.canvas.format.sender_alignment = defaults.sender_alignment
        self.canvas.format.sender_vertical_alignment = defaults.sender_vertical_alignment
        self.canvas.format.recipient_font_family = defaults.recipient_font_family
        self.canvas.format.recipient_font_size = defaults.recipient_font_size
        self.canvas.format.recipient_bold = defaults.recipient_bold
        self.canvas.format.recipient_italic = defaults.recipient_italic
        self.canvas.format.recipient_alignment = defaults.recipient_alignment
        self.canvas.format.recipient_vertical_alignment = defaults.recipient_vertical_alignment
        self.sender_enabled.setChecked(defaults.sender_enabled)
        self.sender_font.setCurrentFont(QFont(defaults.sender_font_family))
        self.sender_size.setValue(defaults.sender_font_size)
        self.sender_bold.setChecked(defaults.sender_bold)
        self.sender_italic.setChecked(defaults.sender_italic)
        self.sender_alignment.setCurrentIndex(self.sender_alignment.findData(defaults.sender_alignment))
        self.sender_vertical_alignment.setCurrentIndex(
            self.sender_vertical_alignment.findData(defaults.sender_vertical_alignment)
        )
        self.recipient_font.setCurrentFont(QFont(defaults.recipient_font_family))
        self.recipient_size.setValue(defaults.recipient_font_size)
        self.recipient_bold.setChecked(defaults.recipient_bold)
        self.recipient_italic.setChecked(defaults.recipient_italic)
        self.recipient_alignment.setCurrentIndex(self.recipient_alignment.findData(defaults.recipient_alignment))
        self.recipient_vertical_alignment.setCurrentIndex(
            self.recipient_vertical_alignment.findData(defaults.recipient_vertical_alignment)
        )
        self.canvas.update()


class FormatSettingsDialog(QDialog):
    def __init__(self, current: LabelFormat, storage_path: Path,
                 sender_text: str = "Expéditeur", recipient_text: str = "Destinataire",
                 parent: QWidget | None = None, print_test_callback=None):
        super().__init__(parent)
        self.setWindowTitle("Formats d'étiquettes")
        self.resize(820, 560)
        self.storage_path = storage_path
        self.sender_text = sender_text
        self.recipient_text = recipient_text
        self.formats = self.load_formats()
        self.current_format = current
        self.print_test_callback = print_test_callback

        self.preset_list = QListWidget()
        self.preset_list.currentItemChanged.connect(self.select_format)
        for name in self.formats:
            self.preset_list.addItem(QListWidgetItem(name))

        self.name = QLineEdit(current.name)
        self.page_width = self._number(current.page_width, 1, 1000)
        self.page_height = self._number(current.page_height, 1, 1000)
        self.columns = self._number(current.columns, 1, 50, integer=True)
        self.rows = self._number(current.rows, 1, 50, integer=True)
        self.margin_left = self._number(current.margin_left, 0, 100)
        self.margin_top = self._number(current.margin_top, 0, 100)
        self.gap_x = self._number(current.gap_x, 0, 100)
        self.gap_y = self._number(current.gap_y, 0, 100)
        self.label_width = self._number(
            current.label_width if current.label_width is not None else self._derived_label_width(current), 0.1, 1000
        )
        self.label_height = self._number(
            current.label_height if current.label_height is not None else self._derived_label_height(current), 0.1, 1000
        )
        self.margin_right_value = QLabel()
        self.margin_bottom_value = QLabel()
        for value_label in (self.margin_right_value, self.margin_bottom_value):
            value_label.setMinimumWidth(72)
            value_label.setStyleSheet(
                "QLabel { background: #eef2f5; border: 1px solid #cbd5dc; "
                "border-radius: 3px; padding: 4px 7px; }"
            )
        self.sender_height_percent = current.sender_height_percent
        self.sender_enabled = current.sender_enabled
        self.sender_base_size = current.sender_base_size
        self.sender_min_size = current.sender_min_size
        self.sender_offset_x = current.sender_offset_x
        self.sender_offset_y = current.sender_offset_y
        self.recipient_offset_x = current.recipient_offset_x
        self.recipient_offset_y = current.recipient_offset_y
        self.sender_width = current.sender_width
        self.recipient_width = current.recipient_width
        self.recipient_height = current.recipient_height
        self.sender_font_family = current.sender_font_family
        self.sender_font_size = current.sender_font_size
        self.sender_bold = current.sender_bold
        self.sender_italic = current.sender_italic
        self.recipient_font_family = current.recipient_font_family
        self.recipient_font_size = current.recipient_font_size
        self.recipient_bold = current.recipient_bold
        self.recipient_italic = current.recipient_italic
        self.sender_alignment = current.sender_alignment
        self.recipient_alignment = current.recipient_alignment
        self.sender_vertical_alignment = current.sender_vertical_alignment
        self.recipient_vertical_alignment = current.recipient_vertical_alignment
        self.start_column = current.start_column
        self.start_row = current.start_row
        self.preview = FormatPreview()
        self.preview.format.start_column = self.start_column
        self.preview.format.start_row = self.start_row
        self.preview.positionChanged.connect(self.set_start_position)
        self.controls = (self.name, self.page_width, self.page_height, self.columns,
                 self.rows, self.margin_left, self.margin_top, self.gap_x, self.gap_y,
                 self.label_width, self.label_height)
        for control in self.controls:
            if hasattr(control, "textChanged"):
                control.textChanged.connect(self.update_preview)
            else:
                control.valueChanged.connect(self.update_preview)

        form = QGridLayout()
        fields = (
            ("Nom", self.name), ("Largeur page (mm)", self.page_width),
            ("Hauteur page (mm)", self.page_height), ("Colonnes", self.columns),
            ("Lignes", self.rows), ("Marge gauche (mm)", self.margin_left),
            ("Marge haut (mm)", self.margin_top), ("Espace horizontal (mm)", self.gap_x),
            ("Espace vertical (mm)", self.gap_y),
        )
        for row, (label, control) in enumerate(fields):
            form.addWidget(QLabel(label), row, 0)
            form.addWidget(control, row, 1)
        margin_info = QVBoxLayout()
        margin_info.addLayout(self._calculated_margin_row("Marge droite (mm)", self.margin_right_value))
        margin_info.addLayout(self._calculated_margin_row("Marge basse (mm)", self.margin_bottom_value))
        label_info = QVBoxLayout()
        label_info.addLayout(self._calculated_margin_row("Largeur étiquette (mm)", self.label_width))
        label_info.addLayout(self._calculated_margin_row("Hauteur étiquette (mm)", self.label_height))
        form.addLayout(label_info, 0, 2, 2, 1, Qt.AlignmentFlag.AlignTop)
        form.addLayout(margin_info, 5, 2, 2, 1, Qt.AlignmentFlag.AlignTop)
        form.setColumnStretch(0, 1)
        form.setColumnStretch(1, 0)
        form.setColumnStretch(2, 1)

        self.save_feedback = QLabel()
        self.save_feedback.setVisible(False)
        self.save_feedback.setStyleSheet(
            "QLabel { background: #e8f5e9; color: #216e39; border: 1px solid #9bd1a5; "
            "border-radius: 4px; padding: 7px 9px; }"
        )
        self.geometry_feedback = QLabel()
        self.geometry_feedback.setWordWrap(True)
        self.geometry_feedback.setStyleSheet("QLabel { color: #a33a2b; padding: 4px 0; }")
        position_button = QPushButton("Modifier la mise en page...")
        position_button.clicked.connect(self.open_position_editor)
        save_button = QPushButton("Enregistrer le format")
        save_button.clicked.connect(self.save_format)
        delete_button = QPushButton("Supprimer")
        delete_button.clicked.connect(self.delete_format)
        apply_button = QPushButton("Utiliser ce format")
        apply_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Annuler")
        cancel_button.clicked.connect(self.reject)
        test_page_button = QPushButton("Imprimer une page de test")
        test_page_button.clicked.connect(self.print_test_page)
        center_buttons = QHBoxLayout()
        center_horizontal_button = QPushButton("Centrer horizontalement")
        center_horizontal_button.clicked.connect(self.center_horizontally)
        center_vertical_button = QPushButton("Centrer verticalement")
        center_vertical_button.clicked.connect(self.center_vertically)
        center_buttons.addWidget(center_horizontal_button)
        center_buttons.addWidget(center_vertical_button)

        editor = QVBoxLayout()
        editor.addLayout(form)
        editor.addLayout(center_buttons)
        editor.addWidget(position_button)
        editor.addWidget(save_button)
        editor.addWidget(self.geometry_feedback)
        editor.addWidget(self.save_feedback)
        editor.addStretch()
        editor.addWidget(apply_button)
        editor.addWidget(cancel_button)
        editor.addSpacing(12)
        editor.addWidget(delete_button)

        left = QVBoxLayout()
        left.addWidget(QLabel("Formats disponibles"))
        left.addWidget(self.preset_list)
        layout = QHBoxLayout(self)
        layout.addLayout(left, 1)
        layout.addLayout(editor, 2)
        preview_column = QVBoxLayout()
        preview_column.addWidget(self.preview, 1)
        preview_column.addWidget(test_page_button)
        layout.addLayout(preview_column, 2)
        matching_items = self.preset_list.findItems(current.name, Qt.MatchFlag.MatchExactly)
        if matching_items:
            self.preset_list.setCurrentItem(matching_items[0])
        self.update_preview()

    @staticmethod
    def _number(value: float, minimum: float, maximum: float, integer: bool = False):
        control = QDoubleSpinBox()
        control.setRange(minimum, maximum)
        control.setValue(value)
        control.setDecimals(0 if integer else 1)
        control.setSingleStep(1)
        return control

    @staticmethod
    def _calculated_margin_row(label: str, value: QLabel) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        row.addWidget(value)
        return row

    @staticmethod
    def _derived_label_width(label_format: LabelFormat) -> float:
        return (label_format.page_width - label_format.margin_left * 2
                - label_format.gap_x * (label_format.columns - 1)) / label_format.columns

    @staticmethod
    def _derived_label_height(label_format: LabelFormat) -> float:
        return (label_format.page_height - label_format.margin_top * 2
                - label_format.gap_y * (label_format.rows - 1)) / label_format.rows

    def load_formats(self) -> dict[str, dict]:
        return load_formats(self.storage_path)

    def select_format(self, item: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        del previous
        if item is None:
            return
        values = self.formats[item.text()]
        self.name.setText(item.text())
        defaults = asdict(LabelFormat(item.text()))
        defaults = asdict(LabelFormat(item.text()))
        for field in ("page_width", "page_height", "columns", "rows", "margin_left", "margin_top", "gap_x", "gap_y"):
            getattr(self, field).setValue(values.get(field, defaults[field]))
        selected = LabelFormat(item.text(), **values)
        self.label_width.setValue(
            selected.label_width if selected.label_width is not None else self._derived_label_width(selected)
        )
        self.label_height.setValue(
            selected.label_height if selected.label_height is not None else self._derived_label_height(selected)
        )
        self.sender_height_percent = values.get("sender_height_percent", defaults["sender_height_percent"])
        self.sender_base_size = values.get("sender_base_size", defaults["sender_base_size"])
        self.sender_min_size = values.get("sender_min_size", defaults["sender_min_size"])
        self.sender_enabled = values.get("sender_enabled", defaults["sender_enabled"])
        self.sender_offset_x = values.get("sender_offset_x", defaults["sender_offset_x"])
        self.sender_offset_y = values.get("sender_offset_y", defaults["sender_offset_y"])
        self.recipient_offset_x = values.get("recipient_offset_x", defaults["recipient_offset_x"])
        self.recipient_offset_y = values.get("recipient_offset_y", defaults["recipient_offset_y"])
        self.sender_width = values.get("sender_width", defaults["sender_width"])
        self.recipient_width = values.get("recipient_width", defaults["recipient_width"])
        self.recipient_height = values.get("recipient_height", defaults["recipient_height"])
        for field in ("sender_font_family", "sender_font_size", "sender_bold", "sender_italic",
                      "recipient_font_family", "recipient_font_size", "recipient_bold",
                      "recipient_italic", "sender_alignment", "recipient_alignment",
                      "sender_vertical_alignment", "recipient_vertical_alignment"):
            setattr(self, field, values.get(field, defaults[field]))
            self.start_column = int(values.get("start_column", defaults["start_column"]))
            self.start_row = int(values.get("start_row", defaults["start_row"]))
            self.preview.format.start_column = self.start_column
            self.preview.format.start_row = self.start_row
            self.preview.update()

    def current_values(self) -> LabelFormat:
        return LabelFormat(
            self.name.text().strip() or "Format personnalisé",
            self.page_width.value(), self.page_height.value(), int(self.columns.value()),
            int(self.rows.value()), self.margin_left.value(), self.margin_top.value(),
            self.gap_x.value(), self.gap_y.value(), self.sender_height_percent,
            self.sender_base_size, self.sender_min_size,
            self.sender_offset_x, self.sender_offset_y, self.recipient_offset_x,
            self.recipient_offset_y, self.sender_width, self.recipient_width,
            self.recipient_height,
            self.sender_font_family, self.sender_font_size, self.sender_bold,
            self.sender_italic, self.recipient_font_family, self.recipient_font_size,
            self.recipient_bold, self.recipient_italic,
            self.sender_enabled,
            self.sender_alignment, self.recipient_alignment,
            self.sender_vertical_alignment, self.recipient_vertical_alignment,
            self.start_column, self.start_row,
            self.label_width.value(), self.label_height.value(),
        )

    def set_start_position(self, column: int, row: int) -> None:
        self.start_column = column
        self.start_row = row
        self.update_preview()

    def center_horizontally(self) -> None:
        current = self.current_values()
        remaining = (current.page_width - current.columns * current.label_width
                     - (current.columns - 1) * current.gap_x)
        self.margin_left.setValue(max(0, remaining / 2))

    def center_vertically(self) -> None:
        current = self.current_values()
        remaining = (current.page_height - current.rows * current.label_height
                     - (current.rows - 1) * current.gap_y)
        self.margin_top.setValue(max(0, remaining / 2))

    def print_test_page(self) -> None:
        if self.print_test_callback is not None:
            self.print_test_callback(self.current_values())

    def update_preview(self) -> None:
        current = self.current_values()
        self.preview.set_format(current)
        right_space = (current.page_width - current.margin_left
                       - current.columns * current.label_width
                       - (current.columns - 1) * current.gap_x)
        bottom_space = (current.page_height - current.margin_top
                        - current.rows * current.label_height
                        - (current.rows - 1) * current.gap_y)
        self.margin_right_value.setText(f"{right_space:.1f}")
        self.margin_bottom_value.setText(f"{bottom_space:.1f}")
        messages = []
        if right_space < 0:
            messages.append(f"Largeur dépassée de {-right_space:.1f} mm")
        if bottom_space < 0:
            messages.append(f"Hauteur dépassée de {-bottom_space:.1f} mm")
        self.geometry_feedback.setText(" | ".join(messages))
        self.geometry_feedback.setVisible(bool(messages))

    def open_position_editor(self) -> None:
        dialog = PositionEditorDialog(
            self.current_values(), self.sender_text, self.recipient_text, self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        edited = dialog.canvas.format
        self.sender_offset_x = edited.sender_offset_x
        self.sender_offset_y = edited.sender_offset_y
        self.recipient_offset_x = edited.recipient_offset_x
        self.recipient_offset_y = edited.recipient_offset_y
        self.sender_width = edited.sender_width
        self.recipient_width = edited.recipient_width
        self.recipient_height = edited.recipient_height
        self.sender_height_percent = edited.sender_height_percent
        self.sender_enabled = edited.sender_enabled
        self.sender_vertical_alignment = edited.sender_vertical_alignment
        self.recipient_vertical_alignment = edited.recipient_vertical_alignment
        self.sender_font_family = edited.sender_font_family
        self.sender_font_size = edited.sender_font_size
        self.sender_bold = edited.sender_bold
        self.sender_italic = edited.sender_italic
        self.recipient_font_family = edited.recipient_font_family
        self.recipient_font_size = edited.recipient_font_size
        self.recipient_bold = edited.recipient_bold
        self.recipient_italic = edited.recipient_italic
        self.update_preview()

    def save_format(self) -> None:
        label_format = self.current_values()
        self.formats[label_format.name] = asdict(label_format) | {"name": None}
        self.formats[label_format.name].pop("name", None)
        try:
            self.storage_path.write_text(json.dumps(self.formats, indent=2), encoding="utf-8")
        except OSError as error:
            QMessageBox.warning(self, "Enregistrement impossible", str(error))
            return
        if not self.preset_list.findItems(label_format.name, Qt.MatchFlag.MatchExactly):
            self.preset_list.addItem(label_format.name)
        self.save_feedback.setText(f"✓ Format enregistré : {label_format.name}")
        self.save_feedback.setVisible(True)
        QTimer.singleShot(4000, self.save_feedback.hide)

    def delete_format(self) -> None:
        item = self.preset_list.currentItem()
        if item is None:
            return
        if len(self.formats) <= 1:
            QMessageBox.information(
                self, "Dernier format", "Il doit rester au moins un format enregistré."
            )
            return
        self.formats.pop(item.text(), None)
        self.storage_path.write_text(json.dumps(self.formats, indent=2), encoding="utf-8")
        self.preset_list.takeItem(self.preset_list.row(item))

    def format_result(self) -> LabelFormat:
        return self.current_values()