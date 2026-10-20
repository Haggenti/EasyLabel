from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QFont, QFontMetricsF, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QApplication,
    QDialog,
    QDoubleSpinBox,
    QFontComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStyle,
    QStyleOptionComboBox,
    QStylePainter,
    QVBoxLayout,
    QWidget,
)


PRESETS = {
    "A4 - 2 x 5": {
        "page_width": 210, "page_height": 297, "columns": 2, "rows": 5,
        "margin_left": 10, "margin_top": 10, "gap_x": 3, "gap_y": 3,
        "sender_height": 18, "sender_base_size": 9, "sender_min_size": 6,
    },
    "A4 - 3 x 8": {
        "page_width": 210, "page_height": 297, "columns": 3, "rows": 8,
        "margin_left": 8, "margin_top": 10, "gap_x": 2, "gap_y": 2,
        "sender_height": 18, "sender_base_size": 9, "sender_min_size": 6,
    },
}


def load_formats(storage_path: Path) -> dict[str, dict]:
    if storage_path.exists():
        try:
            stored_formats = json.loads(storage_path.read_text(encoding="utf-8"))
            if isinstance(stored_formats, dict):
                formats = {
                    name: values
                    for name, values in (
                        (_normalise_format(name, values)
                         for name, values in stored_formats.items())
                    )
                    if name is not None and values is not None
                }
                if formats:
                    return formats
        except (OSError, json.JSONDecodeError):
            pass
    return dict(PRESETS)


def _normalise_format(name: object, values: object) -> tuple[str | None, dict | None]:
    if not isinstance(name, str) or not name.strip() or not isinstance(values, dict):
        return None, None
    name = name.strip()
    values = dict(values)
    if "sender_height" not in values:
        legacy_percent = values.get("sender_height_percent", 34)
        label_height = values.get("label_height")
        if label_height is None:
            label_height = ((float(values.get("page_height", 297))
                             - float(values.get("margin_top", 10)) * 2
                             - float(values.get("gap_y", 3))
                             * (int(values.get("rows", 5)) - 1)) / int(values.get("rows", 5)))
        values["sender_height"] = float(label_height) * float(legacy_percent) / 100
    defaults = asdict(LabelFormat(name))
    normalised = {}
    for field, default in defaults.items():
        if field == "name":
            continue
        value = values.get(field, default)
        try:
            if isinstance(default, bool):
                if not isinstance(value, bool):
                    return None, None
            elif isinstance(default, int):
                value = int(value)
            elif isinstance(default, float):
                value = float(value)
                if not math.isfinite(value):
                    return None, None
            elif default is None:
                if value is not None:
                    value = float(value)
                    if not math.isfinite(value):
                        return None, None
            elif not isinstance(value, str):
                return None, None
        except (TypeError, ValueError, OverflowError):
            return None, None
        normalised[field] = value
    try:
        label_format = LabelFormat(name, **normalised)
    except (TypeError, ValueError):
        return None, None
    if label_format.page_width <= 0 or label_format.page_height <= 0:
        return None, None
    if label_format.columns < 1 or label_format.rows < 1:
        return None, None
    if label_format.corner_radius < 0:
        return None, None
    return name, normalised


def save_formats(storage_path: Path, formats: dict[str, dict]) -> None:
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=storage_path.parent,
            prefix=f".{storage_path.name}.", suffix=".tmp", delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(formats, temporary_file, indent=2, ensure_ascii=False)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, storage_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


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
    sender_height: float = 18
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
    corner_radius: float = 0


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


class PaddedComboBox(QComboBox):
    def paintEvent(self, event) -> None:
        del event
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        text = option.currentText
        option.currentText = ""
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        text_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            option,
            QStyle.SubControl.SC_ComboBoxEditField,
            self,
        ).adjusted(8, 0, -8, 0)
        painter.drawItemText(
            text_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.palette(), self.isEnabled(), text,
        )


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
                rect = QRectF(page.left() + x * scale, page.top() + y * scale,
                              label_width * scale, label_height * scale)
                radius = min(self.format.corner_radius * scale,
                             rect.width() / 2, rect.height() / 2)
                painter.drawRoundedRect(rect, radius, radius)
        marker_rect = self.label_rect(self.format.start_column, self.format.start_row)
        painter.setPen(QPen(Qt.GlobalColor.red, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        marker_rect = marker_rect.adjusted(2, 2, -2, -2)
        radius = min(self.format.corner_radius * scale,
                 marker_rect.width() / 2, marker_rect.height() / 2)
        painter.drawRoundedRect(marker_rect, radius, radius)
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
    RECIPIENT_TOP_PERCENT = 34
    SNAP_DISTANCE_MM = 1.5

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
        self.zoom = 2.0
        self.setMouseTracking(True)
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
        base_x, base_y, width, height = self.base_geometry(element)
        page_width, page_height = self.label_dimensions()
        offset_x = getattr(self.format, f"{element}_offset_x") * self.LOGICAL_WIDTH / page_width
        offset_y = getattr(self.format, f"{element}_offset_y") * self.LOGICAL_HEIGHT / page_height
        return QRectF(origin.left() + (base_x + offset_x) * scale_x,
                      origin.top() + (base_y + offset_y) * scale_y,
                      width * scale_x, height * scale_y)

    def base_geometry(self, element: str) -> tuple[float, float, float, float]:
        page_width, page_height = self.label_dimensions()
        sender_height = self.format.sender_height
        if element == "sender":
            return (2 * self.LOGICAL_WIDTH / page_width,
                 2 * self.LOGICAL_HEIGHT / page_height,
             self.format.sender_width, sender_height * self.LOGICAL_HEIGHT / page_height)
        return (2 * self.LOGICAL_WIDTH / page_width,
              (2 + page_height * self.RECIPIENT_TOP_PERCENT / 100)
              * self.LOGICAL_HEIGHT / page_height,
            self.format.recipient_width,
            self.format.recipient_height * self.LOGICAL_HEIGHT / 100)

    def resize_edges(self, element: str, position: QPointF) -> str:
        rect = self.geometry_for(element)
        tolerance = 8.0
        if not rect.adjusted(-tolerance, -tolerance, tolerance, tolerance).contains(position):
            return ""
        edges = ""
        if abs(position.x() - rect.left()) <= tolerance:
            edges += "l"
        elif abs(position.x() - rect.right()) <= tolerance:
            edges += "r"
        if abs(position.y() - rect.top()) <= tolerance:
            edges += "t"
        elif abs(position.y() - rect.bottom()) <= tolerance:
            edges += "b"
        return edges

    @staticmethod
    def cursor_for_edges(edges: str) -> Qt.CursorShape:
        if edges in ("lt", "rb"):
            return Qt.CursorShape.SizeFDiagCursor
        if edges in ("rt", "lb"):
            return Qt.CursorShape.SizeBDiagCursor
        if edges in ("l", "r"):
            return Qt.CursorShape.SizeHorCursor
        if edges in ("t", "b"):
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    def paintEvent(self, event) -> None:
        del event
        page_width, page_height = self.label_dimensions()
        painter = QPainter(self)
        _, page = self.scale_and_page()
        scale_x, scale_y = self.logical_scales(page)
        painter.fillRect(page, Qt.GlobalColor.white)
        painter.setPen(QPen(Qt.GlobalColor.darkGray, 1))
        radius = min(self.format.corner_radius * scale_x,
                 self.format.corner_radius * scale_y,
                 page.width() / 2, page.height() / 2)
        painter.drawRoundedRect(page, radius, radius)
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
            family = getattr(self.format, f"{element}_font_family")
            size = getattr(self.format, f"{element}_font_size")
            minimum_size = 4
            fitted_size = max(minimum_size, round(size * self.zoom))
            font = QFont(family, fitted_size)
            font.setBold(getattr(self.format, f"{element}_bold"))
            font.setItalic(getattr(self.format, f"{element}_italic"))
            painter.setFont(font)
            sample = self.sender_text if element == "sender" else self.recipient_text
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
            edges = self.resize_edges(element, event.position())
            if edges:
                self.active = element
                self.drag_mode = f"resize:{edges}"
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
            for element in ("recipient", "sender"):
                edges = self.resize_edges(element, event.position())
                if edges:
                    self.setCursor(QCursor(self.cursor_for_edges(edges)))
                    return
            self.unsetCursor()
            return
        _, page = self.scale_and_page()
        scale_x, scale_y = self.logical_scales(page)
        delta = event.position() - self.drag_start
        base_x, base_y, element_width, element_height = self.base_geometry(self.active)
        if self.drag_mode.startswith("resize:"):
            edges = self.drag_mode.split(":", 1)[1]
            original_width, original_height = self.original_size
            page_width, page_height = self.label_dimensions()
            original_x = base_x + self.original_offset[0] * self.LOGICAL_WIDTH / page_width
            original_y = base_y + self.original_offset[1] * self.LOGICAL_HEIGHT / page_height
            original_right = original_x + original_width
            original_bottom = original_y + original_height
            delta_x = delta.x() / scale_x
            delta_y = delta.y() / scale_y
            symmetric = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            new_x = original_x + delta_x if "l" in edges else original_x
            new_y = original_y + delta_y if "t" in edges else original_y
            new_right = original_right + delta_x if "r" in edges else original_right
            new_bottom = original_bottom + delta_y if "b" in edges else original_bottom
            if symmetric:
                if "l" in edges:
                    new_right = original_right - delta_x
                elif "r" in edges:
                    new_x = original_x - delta_x
                if "t" in edges:
                    new_bottom = original_bottom - delta_y
                elif "b" in edges:
                    new_y = original_y - delta_y
            minimum_width = 30
            minimum_height = 10
            if new_right - new_x < minimum_width:
                if "l" in edges:
                    new_x = new_right - minimum_width
                else:
                    new_right = new_x + minimum_width
            if new_bottom - new_y < minimum_height:
                if "t" in edges:
                    new_y = new_bottom - minimum_height
                else:
                    new_bottom = new_y + minimum_height
            new_x = max(0, min(new_x, self.LOGICAL_WIDTH - minimum_width))
            new_y = max(0, min(new_y, self.LOGICAL_HEIGHT - minimum_height))
            new_right = max(new_x + minimum_width, min(new_right, self.LOGICAL_WIDTH))
            new_bottom = max(new_y + minimum_height, min(new_bottom, self.LOGICAL_HEIGHT))
            new_width = self.snap_size(new_right - new_x)
            new_height = self.snap_size(new_bottom - new_y)
            if self.active == "sender":
                self.format.sender_width = new_width
                self.format.sender_height = new_height * self.label_dimensions()[1] / self.LOGICAL_HEIGHT
            else:
                self.format.recipient_width = new_width
                self.format.recipient_height = new_height / 0.6
            setattr(self.format, f"{self.active}_offset_x",
                    (new_x - base_x) * page_width / self.LOGICAL_WIDTH)
            setattr(self.format, f"{self.active}_offset_y",
                    (new_y - base_y) * page_height / self.LOGICAL_HEIGHT)
            self.clamp_offsets()
            self.update()
            return
        page_width, page_height = self.label_dimensions()
        original_x = self.original_offset[0] * self.LOGICAL_WIDTH / page_width
        original_y = self.original_offset[1] * self.LOGICAL_HEIGHT / page_height
        new_x = self.snap_size(original_x + delta.x() / scale_x)
        new_y = self.snap_size(original_y + delta.y() / scale_y)
        new_x = self.snap_horizontal_position(
            self.active, new_x, base_x, element_width, page_width
        )
        new_x = max(-base_x, min(new_x, self.LOGICAL_WIDTH - base_x - element_width))
        new_y = max(-base_y, min(new_y, self.LOGICAL_HEIGHT - base_y - element_height))
        setattr(self.format, f"{self.active}_offset_x", new_x * page_width / self.LOGICAL_WIDTH)
        setattr(self.format, f"{self.active}_offset_y", new_y * page_height / self.LOGICAL_HEIGHT)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        del event
        self.active = ""
        self.drag_mode = ""

    @staticmethod
    def snap_size(value: float) -> float:
        return round(value * 2) / 2

    def snap_horizontal_position(self, element: str, position: float,
                                 base_x: float, width: float,
                                 page_width: float) -> float:
        del element
        candidates = [(self.LOGICAL_WIDTH - width) / 2 - base_x]
        tolerance = self.SNAP_DISTANCE_MM * self.LOGICAL_WIDTH / page_width
        nearest = min(candidates, key=lambda candidate: abs(candidate - position))
        return nearest if abs(nearest - position) <= tolerance else position

    def clamp_offsets(self) -> None:
        page_width, page_height = self.label_dimensions()
        for element in ("sender", "recipient"):
            base_x, base_y, element_width, element_height = self.base_geometry(element)
            offset_x = getattr(self.format, f"{element}_offset_x") * self.LOGICAL_WIDTH / page_width
            offset_y = getattr(self.format, f"{element}_offset_y") * self.LOGICAL_HEIGHT / page_height
            offset_x = max(-base_x, min(offset_x, self.LOGICAL_WIDTH - base_x - element_width))
            offset_y = max(-base_y, min(offset_y, self.LOGICAL_HEIGHT - base_y - element_height))
            setattr(self.format, f"{element}_offset_x", offset_x * page_width / self.LOGICAL_WIDTH)
            setattr(self.format, f"{element}_offset_y", offset_y * page_height / self.LOGICAL_HEIGHT)


class PositionEditorDialog(QDialog):
    def __init__(self, label_format: LabelFormat, sender_text: str = "Expéditeur",
                 recipient_text: str = "Destinataire", parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Ajuster les positions")
        self.canvas = PositionCanvas(label_format, sender_text, recipient_text, self)
        _, page = self.canvas.scale_and_page()
        initial_width = max(640, round(page.width() + 32))
        screen = QApplication.primaryScreen()
        if screen is not None:
            initial_width = min(initial_width, screen.availableGeometry().width() - 24)
        self.resize(initial_width, 860)
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
        for control in (self.sender_enabled, self.sender_font, self.sender_size,
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
        zoom_value = QLabel("x2")
        for level in PositionCanvas.ZOOM_LEVELS:
            button = QPushButton(f"x{level:g}".replace(".", ","))
            button.setCheckable(True)
            button.clicked.connect(lambda checked, value=level: self.set_canvas_zoom(value))
            zoom_buttons.append(button)
        self.zoom_buttons = zoom_buttons
        self.zoom_value = zoom_value
        zoom_buttons[-1].setChecked(True)
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
        settings.addRow("Police expéditeur", self.sender_font)
        sender_style = QGridLayout()
        sender_style.addWidget(self.sender_size, 0, 0)
        sender_style.addWidget(self.sender_bold, 0, 1)
        sender_style.addWidget(self.sender_italic, 0, 2)
        sender_style.addWidget(self.sender_alignment, 1, 0)
        sender_style.addWidget(self.sender_vertical_alignment, 1, 1)
        settings.addRow("Style expéditeur", sender_style)
        settings.addRow("Police destinataire", self.recipient_font)
        recipient_style = QGridLayout()
        recipient_style.addWidget(self.recipient_size, 0, 0)
        recipient_style.addWidget(self.recipient_bold, 0, 1)
        recipient_style.addWidget(self.recipient_italic, 0, 2)
        recipient_style.addWidget(self.recipient_alignment, 1, 0)
        recipient_style.addWidget(self.recipient_vertical_alignment, 1, 1)
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
        control = PaddedComboBox()
        control.setMinimumContentsLength(6)
        control.setMinimumWidth(92)
        control.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        for label, data in (("Gauche", "left"), ("Centré", "center"), ("Droite", "right")):
            control.addItem(label, data)
        index = control.findData(value)
        control.setCurrentIndex(index if index >= 0 else 1)
        return control

    @staticmethod
    def _vertical_alignment(value: str) -> QComboBox:
        control = PaddedComboBox()
        control.setMinimumContentsLength(6)
        control.setMinimumWidth(92)
        control.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        for label, data in (("Haut", "top"), ("Centré", "center"), ("Bas", "bottom")):
            control.addItem(label, data)
        index = control.findData(value)
        control.setCurrentIndex(index if index >= 0 else 1)
        return control

    def update_sender_settings(self) -> None:
        self.canvas.format.sender_enabled = self.sender_enabled.isChecked()
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
        self.canvas.format.sender_height = LabelFormat("Défauts").sender_height
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
    FORMAT_NAME_ROLE = Qt.ItemDataRole.UserRole + 1

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
        self.active_format_name = current.name
        self.print_test_callback = print_test_callback

        self.preset_list = QListWidget()
        self.preset_list.setMinimumWidth(210)
        self.preset_list.currentItemChanged.connect(self.select_format)
        for name, values in self.formats.items():
            item = self.format_list_item(name, values)
            self.preset_list.addItem(item)
        self.update_active_format_marker()

        self.name = QLineEdit(current.name)
        self.page_width = self._number(current.page_width, 1, 1000, suffix=" mm", step=0.1)
        self.page_height = self._number(current.page_height, 1, 1000, suffix=" mm", step=0.1)
        self.columns = self._number(current.columns, 1, 50, integer=True)
        self.rows = self._number(current.rows, 1, 50, integer=True)
        self.margin_left = self._number(current.margin_left, 0, 100, suffix=" mm", step=0.1)
        self.margin_top = self._number(current.margin_top, 0, 100, suffix=" mm", step=0.1)
        self.gap_x = self._number(current.gap_x, 0, 100, suffix=" mm", step=0.1)
        self.gap_y = self._number(current.gap_y, 0, 100, suffix=" mm", step=0.1)
        self.label_width = self._number(
            current.label_width if current.label_width is not None else self._derived_label_width(current),
            0.1, 1000, suffix=" mm", step=0.1
        )
        self.label_height = self._number(
            current.label_height if current.label_height is not None else self._derived_label_height(current),
            0.1, 1000, suffix=" mm", step=0.1
        )
        self.corner_radius = self._number(current.corner_radius, 0, 1000, suffix=" mm", step=0.1)
        self.margin_right_value = QLabel()
        self.margin_bottom_value = QLabel()
        self.auto_center_horizontal = QCheckBox("Centrage horizontal automatique")
        self.auto_center_vertical = QCheckBox("Centrage vertical automatique")
        self.auto_center_horizontal.stateChanged.connect(self.update_auto_centering)
        self.auto_center_vertical.stateChanged.connect(self.update_auto_centering)
        for value_label in (self.margin_right_value, self.margin_bottom_value):
            value_label.setMinimumWidth(72)
            value_label.setStyleSheet(
                "QLabel { background: #eef2f5; border: 1px solid #cbd5dc; "
                "border-radius: 3px; padding: 4px 7px; }"
            )
        self.sender_height = current.sender_height
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
                 self.label_width, self.label_height, self.corner_radius)
        for control in self.controls:
            if hasattr(control, "textChanged"):
                control.textChanged.connect(self.update_preview)
            else:
                control.valueChanged.connect(self.update_preview)

        form = QGridLayout()

        def add_field(row: int, column: int, label: str, control) -> None:
            base_column = 0 if column == 0 else 3
            form.addWidget(QLabel(label), row, base_column)
            form.addWidget(control, row, base_column + 1)

        form.addWidget(QLabel("Nom"), 0, 0)
        form.addWidget(self.name, 0, 1, 1, 4)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        form.addWidget(separator, 1, 2, 7, 1)
        add_field(1, 0, "Largeur page", self.page_width)
        add_field(1, 1, "Hauteur page", self.page_height)
        add_field(2, 0, "Colonnes", self.columns)
        add_field(2, 1, "Lignes", self.rows)
        add_field(3, 0, "Largeur étiquette", self.label_width)
        add_field(3, 1, "Hauteur étiquette", self.label_height)
        add_field(4, 0, "Marge gauche", self.margin_left)
        add_field(4, 1, "Marge droite", self.margin_right_value)
        add_field(5, 0, "Marge haut", self.margin_top)
        add_field(5, 1, "Marge basse", self.margin_bottom_value)
        add_field(6, 0, "Espace horizontal", self.gap_x)
        add_field(6, 1, "Espace vertical", self.gap_y)
        add_field(7, 0, "Rayon des coins", self.corner_radius)
        form.setColumnStretch(1, 0)
        form.setColumnStretch(2, 0)
        form.setColumnStretch(4, 0)

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
        center_options = QHBoxLayout()
        center_options.addWidget(self.auto_center_horizontal)
        center_options.addWidget(self.auto_center_vertical)

        editor = QVBoxLayout()
        editor.addLayout(form)
        editor.addLayout(center_options)
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
        item = self.find_format_item(current.name)
        if item is not None:
            self.preset_list.setCurrentItem(item)
        self.update_preview()

    @staticmethod
    def _number(value: float, minimum: float, maximum: float, integer: bool = False,
               suffix: str = "", step: float = 1):
        control = QDoubleSpinBox()
        control.setRange(minimum, maximum)
        control.setValue(value)
        control.setDecimals(0 if integer else 1)
        control.setSingleStep(step)
        control.setSuffix(suffix)
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

    def format_list_item(self, name: str, values: dict) -> QListWidgetItem:
        columns = int(values.get("columns", 1))
        rows = int(values.get("rows", 1))
        item = QListWidgetItem(f"{name} ({columns} x {rows})")
        item.setData(self.FORMAT_NAME_ROLE, name)
        return item

    def find_format_item(self, name: str) -> QListWidgetItem | None:
        for index in range(self.preset_list.count()):
            item = self.preset_list.item(index)
            if item.data(self.FORMAT_NAME_ROLE) == name:
                return item
        return None

    def select_format(self, item: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        del previous
        if item is None:
            return
        name = item.data(self.FORMAT_NAME_ROLE)
        values = self.formats[name]
        self.name.setText(name)
        defaults = asdict(LabelFormat(name))
        for field in ("page_width", "page_height", "columns", "rows", "margin_left", "margin_top", "gap_x", "gap_y"):
            getattr(self, field).setValue(values.get(field, defaults[field]))
        selected = LabelFormat(name, **values)
        self.label_width.setValue(
            selected.label_width if selected.label_width is not None else self._derived_label_width(selected)
        )
        self.label_height.setValue(
            selected.label_height if selected.label_height is not None else self._derived_label_height(selected)
        )
        self.corner_radius.setValue(selected.corner_radius)
        self.sender_height = values.get("sender_height", defaults["sender_height"])
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

    def update_active_format_marker(self) -> None:
        marker = QPixmap(16, 16)
        marker.fill(Qt.GlobalColor.transparent)
        painter = QPainter(marker)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(Qt.GlobalColor.darkGreen, 2.5,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.drawLine(3, 8, 7, 12)
        painter.drawLine(7, 12, 14, 3)
        painter.end()
        icon = QIcon(marker)
        for index in range(self.preset_list.count()):
            item = self.preset_list.item(index)
            item.setIcon(icon if item.data(self.FORMAT_NAME_ROLE) == self.active_format_name else QIcon())

    def current_values(self) -> LabelFormat:
        return LabelFormat(
            self.name.text().strip() or "Format personnalisé",
            self.page_width.value(), self.page_height.value(), int(self.columns.value()),
            int(self.rows.value()), self.margin_left.value(), self.margin_top.value(),
            self.gap_x.value(), self.gap_y.value(), self.sender_height,
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
            self.corner_radius.value(),
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

    def update_auto_centering(self) -> None:
        self.update_preview()

    def update_corner_radius_range(self) -> None:
        maximum = min(self.label_width.value(), self.label_height.value()) / 2
        self.corner_radius.setRange(0, max(0, maximum))

    def apply_auto_centering(self) -> None:
        self.margin_left.setEnabled(not self.auto_center_horizontal.isChecked())
        self.margin_top.setEnabled(not self.auto_center_vertical.isChecked())
        if self.auto_center_horizontal.isChecked():
            remaining = (self.page_width.value() - self.columns.value() * self.label_width.value()
                         - (self.columns.value() - 1) * self.gap_x.value())
            self.margin_left.blockSignals(True)
            self.margin_left.setValue(max(0, remaining / 2))
            self.margin_left.blockSignals(False)
        if self.auto_center_vertical.isChecked():
            remaining = (self.page_height.value() - self.rows.value() * self.label_height.value()
                         - (self.rows.value() - 1) * self.gap_y.value())
            self.margin_top.blockSignals(True)
            self.margin_top.setValue(max(0, remaining / 2))
            self.margin_top.blockSignals(False)

    def print_test_page(self) -> None:
        if self.print_test_callback is not None:
            self.print_test_callback(self.current_values())

    def update_preview(self) -> None:
        self.update_corner_radius_range()
        self.apply_auto_centering()
        current = self.current_values()
        self.preview.set_format(current)
        right_space = (current.page_width - current.margin_left
                       - current.columns * current.label_width
                       - (current.columns - 1) * current.gap_x)
        bottom_space = (current.page_height - current.margin_top
                        - current.rows * current.label_height
                        - (current.rows - 1) * current.gap_y)
        self.margin_right_value.setText(f"{right_space:.1f} mm")
        self.margin_bottom_value.setText(f"{bottom_space:.1f} mm")
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
        self.sender_height = edited.sender_height
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
        self.sender_alignment = edited.sender_alignment
        self.recipient_alignment = edited.recipient_alignment
        self.sender_vertical_alignment = edited.sender_vertical_alignment
        self.recipient_vertical_alignment = edited.recipient_vertical_alignment
        self.update_preview()

    def save_format(self) -> None:
        label_format = self.current_values()
        self.formats[label_format.name] = asdict(label_format) | {"name": None}
        self.formats[label_format.name].pop("name", None)
        try:
            save_formats(self.storage_path, self.formats)
        except OSError as error:
            QMessageBox.warning(self, "Enregistrement impossible", str(error))
            return
        item = self.find_format_item(label_format.name)
        if item is None:
            self.preset_list.addItem(self.format_list_item(label_format.name, asdict(label_format)))
        else:
            item.setText(self.format_list_item(label_format.name, asdict(label_format)).text())
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
        name = item.data(self.FORMAT_NAME_ROLE)
        self.formats.pop(name, None)
        try:
            save_formats(self.storage_path, self.formats)
        except OSError as error:
            QMessageBox.warning(self, "Suppression impossible", str(error))
            return
        self.preset_list.takeItem(self.preset_list.row(item))

    def format_result(self) -> LabelFormat:
        return self.current_values()