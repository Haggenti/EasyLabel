#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
import tempfile
import os
import math
import json
import re
import csv
from dataclasses import asdict, dataclass
from pathlib import Path

from PySide6.QtCore import QMarginsF, QPoint, QPointF, QSettings, QRectF, QSize, QSizeF, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QCursor, QDesktopServices, QFont, QFontMetricsF, QIcon, QImage, QImageReader, QMouseEvent, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen, QPixmap, QPolygonF, QTransform
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QDoubleSpinBox,
    QSpinBox,
    QScrollArea,
    QStyle,
    QTextBrowser,
    QVBoxLayout,
    QHBoxLayout,
    QComboBox,
    QFontComboBox,
    QCheckBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from label_printer import CsvDocument, Recipient, Sender, find_csv_files, load_csv
from format_settings import FormatSettingsDialog, LabelFormat, load_formats, save_formats


POINTS_PER_MM = 72 / 25.4


def mm(value: float) -> float:
    return value * POINTS_PER_MM


def application_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    envelope = QRectF(7, 15, 50, 34)
    painter.setPen(QPen(QColor("#234e70"), 3))
    painter.setBrush(QColor("#f4f7f9"))
    painter.drawRoundedRect(envelope, 4, 4)
    painter.setPen(QPen(QColor("#2d7199"), 3))
    painter.drawLine(QPointF(9, 18), QPointF(32, 36))
    painter.drawLine(QPointF(32, 36), QPointF(55, 18))
    painter.end()
    return QIcon(pixmap)


class RenderStats:
    def __init__(self) -> None:
        self.labels = 0
        self.pages = 0
        self.reduced = 0
        self.overflow = 0


class PrintMediaDialog(QDialog):
    def __init__(self, media_types: list[tuple[str, str]], sources: list[tuple[str, str]],
                 selected_media: str = "", selected_source: str = "",
                 parent: QWidget | None = None,
                 printers: list[tuple[str, str]] | None = None,
                 selected_printer: str = "",
                 printer_options: dict[str, tuple[list[tuple[str, str]], list[tuple[str, str]], str, str]] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Options d'impression")
        self.printer_options = printer_options or {}
        self.printer = QComboBox()
        for label, value in printers or []:
            self.printer.addItem(label, value)
        selected_index = self.printer.findData(selected_printer)
        if selected_index >= 0:
            self.printer.setCurrentIndex(selected_index)
        self.media = QComboBox()
        self.source = QComboBox()
        self._fill_options(media_types, sources, selected_media, selected_source)
        self.printer.currentIndexChanged.connect(self._printer_changed)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        if self.printer.count():
            layout.addWidget(QLabel("Imprimante"))
            layout.addWidget(self.printer)
        layout.addWidget(QLabel("Type de papier"))
        layout.addWidget(self.media)
        layout.addWidget(QLabel("Source du papier"))
        layout.addWidget(self.source)
        layout.addWidget(buttons)

    def _fill_options(self, media_types: list[tuple[str, str]],
                      sources: list[tuple[str, str]], selected_media: str,
                      selected_source: str) -> None:
        self.media.blockSignals(True)
        self.source.blockSignals(True)
        self.media.clear()
        self.source.clear()
        for label, value in media_types:
            self.media.addItem(label, value)
        for label, value in sources:
            self.source.addItem(label, value)
        media_index = self.media.findData(selected_media)
        source_index = self.source.findData(selected_source)
        if media_index >= 0:
            self.media.setCurrentIndex(media_index)
        if source_index >= 0:
            self.source.setCurrentIndex(source_index)
        self.media.blockSignals(False)
        self.source.blockSignals(False)

    def _printer_changed(self, index: int) -> None:
        del index
        printer_name = str(self.printer.currentData() or "")
        options = self.printer_options.get(printer_name)
        if options is None:
            return
        media_types, sources, _, _ = options
        selected_source = next(
            (value for _, value in sources if value.casefold() == "multipurpose"), ""
        )
        self._fill_options(media_types, sources, "", selected_source)

    def selected_options(self) -> tuple[str, str, str]:
        return (str(self.printer.currentData() or ""),
                str(self.media.currentData() or ""),
                str(self.source.currentData() or ""))


class FileTreeItem(QTreeWidgetItem):
    def text(self, column: int = 0) -> str:
        return super().text(column)


class FileListWidget(QTreeWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setHeaderLabels(("Fichier", "Étiquettes", "Exemplaires"))
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(True)
        header = self.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

    def addItem(self, item: QTreeWidgetItem) -> None:
        self.addTopLevelItem(item)

    def item(self, index: int) -> QTreeWidgetItem | None:
        return self.topLevelItem(index)

    def count(self) -> int:
        return self.topLevelItemCount()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        item = self.itemAt(event.position().toPoint())
        if item is not None and event.button() == Qt.MouseButton.LeftButton:
            item_rect = self.visualItemRect(item)
            if event.position().x() > item_rect.left() + 28:
                state = (Qt.CheckState.Unchecked
                         if item.checkState(0) == Qt.CheckState.Checked
                         else Qt.CheckState.Checked)
                item.setCheckState(0, state)
        super().mousePressEvent(event)

    @staticmethod
    def warning_icon() -> QIcon:
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#5c4300"), 1))
        painter.setBrush(QColor("#ffd23f"))
        painter.drawPolygon(QPolygonF((QPointF(8, 1), QPointF(15, 14), QPointF(1, 14))))
        painter.setPen(QPen(QColor("#5c4300"), 2))
        painter.drawLine(QPointF(8, 5), QPointF(8, 10))
        painter.drawPoint(QPointF(8, 12))
        painter.end()
        return QIcon(pixmap)


@dataclass
class EnvelopeLayout:
    page_width: float = 220
    page_height: float = 110
    sender_x: float = 12
    sender_y: float = 8
    sender_width: float = 92
    sender_height: float = 22
    sender_enabled: bool = True
    recipient_x: float = 115
    recipient_y: float = 35
    recipient_width: float = 90
    recipient_height: float = 55
    sender_font_family: str = "DejaVu Sans"
    sender_font_size: float = 8
    sender_bold: bool = True
    sender_italic: bool = False
    recipient_font_family: str = "DejaVu Sans"
    recipient_font_size: float = 14
    recipient_bold: bool = True
    recipient_italic: bool = False
    sender_alignment: str = "center"
    recipient_alignment: str = "center"
    postal_code_enabled: bool = False
    postal_code_x: float = 20
    postal_code_y: float = 78
    postal_code_width: float = 60
    postal_code_height: float = 16
    postal_code_offset_x: float = 0
    postal_code_offset_y: float = 0
    background_image: str = ""
    sender_vertical_alignment: str = "top"
    recipient_vertical_alignment: str = "center"


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


def format_postal_code(value: str) -> str:
    text = str(value).strip()
    digits = "".join(character for character in text if character.isdigit())
    return digits.zfill(5) if digits else text


def format_recipient_text(recipient, include_postal: bool = True) -> str:
    values = [recipient.name, recipient.address]
    if include_postal:
        values.append(f"{format_postal_code(recipient.postal_code)} {recipient.city}")
    else:
        values.append(recipient.city)
    return "\n".join(value for value in values if value)


def remove_postal_code_from_text(text: str, postal_code: str) -> str:
    digits = format_postal_code(postal_code)
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(digits) and (len(stripped) == len(digits)
                                            or stripped[len(digits)].isspace()):
            remainder = stripped[len(digits):].strip()
            if remainder:
                lines.append(remainder)
            continue
        lines.append(line)
    return "\n".join(line for line in lines if line.strip())

def text_overflows(bounds: QRectF, rect: QRectF, font: QFont) -> bool:
    horizontal_tolerance = max(1.0, font.pointSizeF() * 0.25)
    vertical_tolerance = max(2.0, font.pointSizeF())
    return (bounds.width() > rect.width() + horizontal_tolerance
            or bounds.height() > rect.height() + vertical_tolerance)


POSTAL_CELL_GAP_MM = 2.0


def draw_centered_digit(painter: QPainter, cell: QRectF, digit: str) -> None:
    metrics = QFontMetricsF(painter.font())
    bounds = metrics.tightBoundingRect(digit)
    center = cell.center()
    baseline = QPointF(
        center.x() - bounds.center().x(),
        center.y() - bounds.center().y(),
    )
    painter.drawText(baseline, digit)


def postal_code_cells(rect: QRectF, count: int, gap: float = 2.0) -> list[QRectF]:
    if count <= 0:
        return []
    gap = min(gap, rect.width() / max(count * 2, 1))
    cell_width = (rect.width() - count * gap) / count
    first_left = rect.left() + gap / 2
    return [QRectF(first_left + index * (cell_width + gap), rect.top(),
                   cell_width, rect.height()) for index in range(count)]


class EnvelopeCanvas(QWidget):
    backgroundChanged = Signal(str)
    zoomChanged = Signal(float)
    BASE_WIDTH = 700
    BASE_HEIGHT = 400
    BASE_MARGIN = 40

    def __init__(self, layout: EnvelopeLayout, sender_text: str = "Expéditeur",
                 recipient_text: str = "Destinataire", postal_code_text: str = "00000",
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.layout_data = layout
        self.sender_text = sender_text
        self.recipient_text = recipient_text
        self.postal_code_text = postal_code_text
        self.active = ""
        self.drag_mode = ""
        self.drag_start = None
        self.original_offset = (0.0, 0.0)
        self.original_size = (0.0, 0.0)
        self.zoom = 1.0
        self.pan_start = None
        self.pan_scroll_start = None
        self.setMouseTracking(True)
        self.setMinimumSize(700, 400)
        self.resize(self.canvas_size())

    def screen_scale(self) -> float:
        return self.screen_dpi() / 25.4

    def screen_dpi(self) -> float:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return 96
        dpi = screen.physicalDotsPerInchX() / screen.devicePixelRatio()
        return dpi if 72 <= dpi <= 300 else 96

    def canvas_size(self) -> QSize:
        scale = self.screen_scale() * self.zoom
        return QSize(
            max(self.BASE_WIDTH, round(self.layout_data.page_width * scale + self.BASE_MARGIN * 2)),
            max(self.BASE_HEIGHT, round(self.layout_data.page_height * scale + self.BASE_MARGIN * 2)),
        )

    def set_zoom(self, value: float) -> None:
        old_zoom = self.zoom
        new_zoom = max(0.5, min(5.0, value))
        if new_zoom == old_zoom:
            return
        self.zoom = new_zoom
        self.resize(self.canvas_size())
        self.zoomChanged.emit(self.zoom)
        self.update()

    def wheelEvent(self, event) -> None:
        direction = 1 if event.angleDelta().y() > 0 else -1
        self.set_zoom(self.zoom + direction * 0.25)
        event.accept()

    def _scroll_area(self) -> QScrollArea | None:
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                return parent
            parent = parent.parentWidget()
        return None

    def scale_and_page(self) -> tuple[float, QRectF]:
        scale = self.screen_scale() * self.zoom
        page_width = self.layout_data.page_width * scale
        page_height = self.layout_data.page_height * scale
        page = QRectF((self.width() - page_width) / 2,
                      (self.height() - page_height) / 2,
                      page_width, page_height)
        return scale, page

    def rect_for(self, element: str) -> QRectF:
        scale, page = self.scale_and_page()
        x = getattr(self.layout_data, f"{element}_x")
        y = getattr(self.layout_data, f"{element}_y")
        width = getattr(self.layout_data, f"{element}_width")
        height = getattr(self.layout_data, f"{element}_height")
        return QRectF(page.left() + x * scale, page.top() + y * scale,
                      width * scale, height * scale)

    def resize_edges(self, element: str, position: QPointF) -> str:
        rect = self.rect_for(element)
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

    def draw_postal_code(self, painter: QPainter, rect: QRectF, scale: float) -> None:
        postal_code = format_postal_code(self.postal_code_text)
        postal_code = "".join(character for character in postal_code if character.isdigit())
        if not postal_code:
            return
        cells = postal_code_cells(rect, len(postal_code), POSTAL_CELL_GAP_MM * scale)
        for cell, character in zip(cells, postal_code):
            draw_centered_digit(painter, cell, character)

    def set_background_image(self, path: str) -> None:
        self.layout_data.background_image = path
        self.backgroundChanged.emit(path)
        self.update()

    def load_background_image(self) -> QImage:
        path = self.layout_data.background_image
        if Path(path).suffix.lower() not in {".jpg", ".jpeg"}:
            return QImage()
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            return image
        page_is_landscape = self.layout_data.page_width >= self.layout_data.page_height
        image_is_landscape = image.width() >= image.height()
        if page_is_landscape != image_is_landscape:
            image = image.transformed(QTransform().rotate(90))
        return image

    def draw_rulers(self, painter: QPainter, scale: float, page: QRectF) -> None:
        ruler_color = Qt.GlobalColor.darkGray
        painter.save()
        painter.setPen(QPen(ruler_color, 1))
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        horizontal_y = page.bottom() + 18
        vertical_x = page.left() - 18
        painter.drawLine(page.left(), horizontal_y, page.right(), horizontal_y)
        painter.drawLine(vertical_x, page.top(), vertical_x, page.bottom())
        painter.drawText(QRectF(page.left() - 8, horizontal_y + 2, 16, 12),
                         Qt.AlignmentFlag.AlignCenter, "0")
        painter.drawText(QRectF(vertical_x - 28, page.bottom() - 6, 26, 12),
                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "0")

        for millimeters in range(1, math.ceil(self.layout_data.page_width) + 1):
            if millimeters % 10:
                continue
            x = page.left() + millimeters * scale
            if x > page.right() + 0.1:
                break
            tick_length = 8 if millimeters % 50 == 0 else 5
            painter.drawLine(x, horizontal_y, x, horizontal_y - tick_length)
            if millimeters % 50 == 0:
                painter.drawText(QRectF(x - 20, horizontal_y + 2, 40, 12),
                                 Qt.AlignmentFlag.AlignCenter, str(millimeters))

        for millimeters in range(1, math.ceil(self.layout_data.page_height) + 1):
            if millimeters % 10:
                continue
            y = page.bottom() - millimeters * scale
            if y < page.top() - 0.1:
                break
            tick_length = 8 if millimeters % 50 == 0 else 5
            painter.drawLine(vertical_x, y, vertical_x + tick_length, y)
            if millimeters % 50 == 0:
                painter.drawText(QRectF(vertical_x - 44, y - 6, 40, 12),
                                 Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                                 str(millimeters))
        painter.restore()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale, page = self.scale_and_page()
        painter.fillRect(page, Qt.GlobalColor.white)
        if self.layout_data.background_image:
            image = self.load_background_image()
            if not image.isNull():
                painter.save()
                painter.setOpacity(0.45)
                painter.drawImage(page, image)
                painter.restore()
        painter.setPen(QPen(Qt.GlobalColor.darkGray, 1))
        painter.drawRect(page)
        self.draw_rulers(painter, scale, page)
        recipient_text = self.recipient_text
        if self.layout_data.postal_code_enabled:
            recipient_text = remove_postal_code_from_text(
                recipient_text, self.postal_code_text
            )
        for element, color, text in (("sender", Qt.GlobalColor.darkBlue, self.sender_text),
                                     ("recipient", Qt.GlobalColor.darkGreen, recipient_text)):
            if element == "sender" and not self.layout_data.sender_enabled:
                continue
            rect = self.rect_for(element)
            painter.setPen(QPen(color, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            font = QFont(getattr(self.layout_data, f"{element}_font_family"))
            font.setPixelSize(round(
                getattr(self.layout_data, f"{element}_font_size")
                * self.screen_dpi() / 72 * self.zoom
            ))
            font.setBold(getattr(self.layout_data, f"{element}_bold"))
            font.setItalic(getattr(self.layout_data, f"{element}_italic"))
            painter.setFont(font)
            painter.drawText(
                rect.adjusted(3, 3, -3, -3),
                alignment_flag(
                    getattr(self.layout_data, f"{element}_alignment"),
                    vertical_alignment_flag(
                        getattr(self.layout_data, f"{element}_vertical_alignment")
                    ),
                ) | Qt.TextFlag.TextWordWrap,
                text,
            )
        if self.layout_data.postal_code_enabled:
            rect = self.rect_for("postal_code")
            painter.setPen(QPen(Qt.GlobalColor.darkRed, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            painter.setPen(Qt.GlobalColor.darkRed)
            self.draw_postal_code(painter, rect, scale)
        del scale

    def mousePressEvent(self, event) -> None:
        elements = ("postal_code", "recipient", "sender")
        for element in elements:
            if element == "postal_code" and not self.layout_data.postal_code_enabled:
                continue
            if element == "sender" and not self.layout_data.sender_enabled:
                continue
            edges = self.resize_edges(element, event.position())
            if edges:
                self.active = element
                self.drag_mode = f"resize:{edges}"
                self.drag_start = event.position()
                self.original_offset = (getattr(self.layout_data, f"{element}_x"),
                                        getattr(self.layout_data, f"{element}_y"))
                self.original_size = (getattr(self.layout_data, f"{element}_width"),
                                      getattr(self.layout_data, f"{element}_height"))
                return
        for element in elements:
            if element == "postal_code" and not self.layout_data.postal_code_enabled:
                continue
            if element == "sender" and not self.layout_data.sender_enabled:
                continue
            if self.rect_for(element).contains(event.position()):
                self.active = element
                self.drag_mode = "move"
                self.drag_start = event.position()
                self.original_offset = (getattr(self.layout_data, f"{element}_x"),
                                        getattr(self.layout_data, f"{element}_y"))
                self.original_size = (getattr(self.layout_data, f"{element}_width"),
                                      getattr(self.layout_data, f"{element}_height"))
                return
        scroll_area = self._scroll_area()
        if scroll_area is not None and self.scale_and_page()[1].contains(event.position()):
            self.pan_start = scroll_area.viewport().mapFromGlobal(
                event.globalPosition().toPoint()
            )
            self.pan_scroll_start = (
                scroll_area.horizontalScrollBar().value(),
                scroll_area.verticalScrollBar().value(),
            )
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        event.ignore()

    def mouseMoveEvent(self, event) -> None:
        if self.pan_start is not None and self.pan_scroll_start is not None:
            scroll_area = self._scroll_area()
            if scroll_area is not None:
                current_position = scroll_area.viewport().mapFromGlobal(
                    event.globalPosition().toPoint()
                )
                delta = current_position - self.pan_start
                scroll_area.horizontalScrollBar().setValue(
                    self.pan_scroll_start[0] - delta.x()
                )
                scroll_area.verticalScrollBar().setValue(
                    self.pan_scroll_start[1] - delta.y()
                )
            event.accept()
            return
        if not self.active or self.drag_start is None:
            elements = ("postal_code", "recipient", "sender")
            for element in elements:
                if element == "postal_code" and not self.layout_data.postal_code_enabled:
                    continue
                if element == "sender" and not self.layout_data.sender_enabled:
                    continue
                edges = self.resize_edges(element, event.position())
                if edges:
                    self.setCursor(QCursor(self.cursor_for_edges(edges)))
                    return
            self.unsetCursor()
            return
        scale, _ = self.scale_and_page()
        delta = event.position() - self.drag_start
        if self.drag_mode.startswith("resize:"):
            edges = self.drag_mode.split(":", 1)[1]
            minimum_width = 5 if self.active == "postal_code" else 20
            minimum_height = 5 if self.active == "postal_code" else 10
            original_x, original_y = self.original_offset
            original_width, original_height = self.original_size
            original_right = original_x + original_width
            original_bottom = original_y + original_height
            new_x = original_x + delta.x() / scale if "l" in edges else original_x
            new_y = original_y + delta.y() / scale if "t" in edges else original_y
            new_right = original_right + delta.x() / scale if "r" in edges else original_right
            new_bottom = original_bottom + delta.y() / scale if "b" in edges else original_bottom
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
            new_x = max(0, min(new_x, self.layout_data.page_width - minimum_width))
            new_y = max(0, min(new_y, self.layout_data.page_height - minimum_height))
            new_right = max(new_x + minimum_width,
                            min(new_right, self.layout_data.page_width))
            new_bottom = max(new_y + minimum_height,
                             min(new_bottom, self.layout_data.page_height))
            setattr(self.layout_data, f"{self.active}_x", round(new_x * 2) / 2)
            setattr(self.layout_data, f"{self.active}_y", round(new_y * 2) / 2)
            setattr(self.layout_data, f"{self.active}_width", round((new_right - new_x) * 2) / 2)
            setattr(self.layout_data, f"{self.active}_height", round((new_bottom - new_y) * 2) / 2)
        else:
            x = max(0, min(self.layout_data.page_width - self.original_size[0],
                           self.original_offset[0] + delta.x() / scale))
            y = max(0, min(self.layout_data.page_height - self.original_size[1],
                           self.original_offset[1] + delta.y() / scale))
            setattr(self.layout_data, f"{self.active}_x", round(x * 2) / 2)
            setattr(self.layout_data, f"{self.active}_y", round(y * 2) / 2)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self.pan_start is not None:
            self.pan_start = None
            self.pan_scroll_start = None
            self.unsetCursor()
            event.accept()
            return
        del event
        self.active = ""
        self.drag_mode = ""
        self.drag_start = None


def fit_font(text: str, rect: QRectF, base_size: int = 15, minimum_size: int = 9,
             family: str = "DejaVu Sans", bold: bool = True, italic: bool = False) -> tuple[QFont, bool]:
    flags = (Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
             | Qt.TextFlag.TextWordWrap)
    for size in range(base_size, minimum_size - 1, -1):
        font = QFont(family, size)
        font.setBold(bold)
        font.setItalic(italic)
        bounds = QFontMetricsF(font).boundingRect(rect, int(flags), text)
        if bounds.width() <= rect.width() and bounds.height() <= rect.height():
            return font, size < base_size

    font = QFont(family, minimum_size)
    font.setBold(bold)
    font.setItalic(italic)
    return font, False


def draw_fitted_lines(painter: QPainter, text: str, rect: QRectF,
                      alignment: Qt.AlignmentFlag, vertical_alignment: Qt.AlignmentFlag,
                      base_size: int, minimum_size: int, family: str,
                      bold: bool, italic: bool) -> tuple[list[QFont], bool, bool]:
    lines = text.splitlines() or [""]
    fonts = []
    reduced = False
    for line in lines:
        def font_at(size: float) -> QFont:
            candidate = QFont(family)
            candidate.setPointSizeF(size)
            candidate.setBold(bold)
            candidate.setItalic(italic)
            return candidate

        minimum_font = font_at(minimum_size)
        maximum_font = font_at(base_size)
        metrics = QFontMetricsF(maximum_font, painter.device())
        if metrics.tightBoundingRect(line).width() <= rect.width():
            font = maximum_font
        else:
            lower = float(minimum_size)
            upper = float(base_size)
            for _ in range(24):
                middle = (lower + upper) / 2
                candidate = font_at(middle)
                metrics = QFontMetricsF(candidate, painter.device())
                if metrics.tightBoundingRect(line).width() <= rect.width():
                    lower = middle
                else:
                    upper = middle
            font = font_at(lower)
            metrics = QFontMetricsF(font, painter.device())
            if metrics.tightBoundingRect(line).width() > rect.width():
                font = minimum_font
        reduced = reduced or font.pointSizeF() < base_size
        fonts.append(font)

    total_height = sum(QFontMetricsF(font, painter.device()).height() for font in fonts)

    if vertical_alignment == Qt.AlignmentFlag.AlignTop:
        top = rect.top()
    elif vertical_alignment == Qt.AlignmentFlag.AlignBottom:
        top = rect.bottom() - total_height
    else:
        top = rect.top() + (rect.height() - total_height) / 2

    painter.save()
    y = top
    overflow = total_height > rect.height()
    for line, font in zip(lines, fonts):
        metrics = QFontMetricsF(font, painter.device())
        line_height = metrics.height()
        line_rect = QRectF(rect.left(), y, rect.width(), line_height)
        if metrics.tightBoundingRect(line).width() > rect.width():
            overflow = True
        painter.setFont(font)
        painter.drawText(line_rect, int(alignment), line)
        y += line_height
    painter.restore()
    return fonts, reduced, overflow


def draw_postal_code(painter: QPainter, rect: QRectF, postal_code: str,
                     font: QFont, draw_guides: bool = False,
                     offset_x: float = 0, offset_y: float = 0) -> None:
    digits = "".join(character for character in postal_code if character.isdigit())
    if not digits:
        return
    cells = postal_code_cells(rect, len(digits), mm(POSTAL_CELL_GAP_MM))
    painter.setFont(font)
    for cell, digit in zip(cells, digits):
        if draw_guides:
            painter.save()
            painter.setPen(QPen(Qt.GlobalColor.gray, 0.5, Qt.PenStyle.DashLine))
            painter.drawRect(cell)
            painter.restore()
        draw_centered_digit(painter, cell, digit)


def render_pdf(documents: list[CsvDocument], output_path: Path, columns: int, rows: int,
               margin_left: float, margin_top: float, gap_x: float, gap_y: float,
               start_column: int = 1, start_row: int = 1,
               page_width: float = 210, page_height: float = 297,
               show_guides: bool = False, sender_height: float = 18,
               sender_base_size: float = 9, sender_min_size: float = 6,
               sender_offset_x: float = 0, sender_offset_y: float = 0,
               recipient_offset_x: float = 0, recipient_offset_y: float = 0,
               sender_width: float = 96, recipient_width: float = 96,
               recipient_height: float = 60,
               sender_font_family: str = "DejaVu Sans Condensed", sender_font_size: float = 9,
               sender_bold: bool = True, sender_italic: bool = False,
               recipient_font_family: str = "DejaVu Sans", recipient_font_size: float = 15,
               recipient_bold: bool = True, recipient_italic: bool = False,
               recipient_min_size: float = 6, sender_enabled: bool = True,
               sender_alignment: str = "center", recipient_alignment: str = "center",
               sender_vertical_alignment: str = "top",
               recipient_vertical_alignment: str = "center",
               label_width: float | None = None, label_height: float | None = None,
               corner_radius: float = 0) -> RenderStats:
    writer = QPdfWriter(str(output_path))
    writer.setPageSize(QPageSize(QSizeF(page_width, page_height), QPageSize.Unit.Millimeter))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
    writer.setResolution(72)

    page_width_points = mm(page_width)
    page_height_points = mm(page_height)
    label_width_points = (mm(label_width) if label_width is not None else
                          (page_width_points - mm(margin_left * 2)
                           - mm(gap_x * (columns - 1))) / columns)
    label_height_points = (mm(label_height) if label_height is not None else
                           (page_height_points - mm(margin_top * 2)
                            - mm(gap_y * (rows - 1))) / rows)
    painter = QPainter(writer)
    painter.setPen(Qt.GlobalColor.black)
    stats = RenderStats()
    slot = (start_row - 1) * columns + (start_column - 1)

    for document in documents:
        for recipient in document.recipients:
            if stats.labels == 0:
                stats.pages = 1
            if slot == columns * rows:
                writer.newPage()
                stats.pages += 1
                slot = 0
            column = slot % columns
            row = slot // columns
            x = mm(margin_left + column * (label_width_points / POINTS_PER_MM + gap_x))
            y = mm(margin_top + row * (label_height_points / POINTS_PER_MM + gap_y))
            label_rect = QRectF(x, y, label_width_points, label_height_points)
            if show_guides:
                painter.save()
                painter.setPen(QPen(Qt.GlobalColor.gray, 0.5, Qt.PenStyle.DashLine))
                radius = min(mm(corner_radius), label_rect.width() / 2, label_rect.height() / 2)
                painter.drawRoundedRect(label_rect, radius, radius)
                painter.restore()
            sender_height_points = mm(sender_height)
            sender_rect = QRectF(
                label_rect.left() + mm(2) + mm(sender_offset_x),
                label_rect.top() + mm(2) + mm(sender_offset_y),
                label_width_points * sender_width / 100,
                sender_height_points,
            )
            recipient_rect = QRectF(
                label_rect.left() + mm(2) + mm(recipient_offset_x),
                label_rect.top() + label_height_points * 34 / 100 + mm(recipient_offset_y),
                label_width_points * recipient_width / 100,
                label_height_points * recipient_height / 100,
            )
            label_overflow = False

            if sender_enabled:
                sender_text = "\n".join(document.sender.lines)
                _, sender_was_reduced, sender_overflow = draw_fitted_lines(
                    painter, sender_text, sender_rect,
                    alignment_flag(sender_alignment, vertical_alignment_flag(sender_vertical_alignment)),
                    vertical_alignment_flag(sender_vertical_alignment),
                    int(sender_font_size), int(sender_min_size),
                    sender_font_family, sender_bold, sender_italic
                )
                if sender_was_reduced:
                    stats.reduced += 1
                if sender_overflow:
                    label_overflow = True

            recipient_text = format_recipient_text(recipient)
            _, was_reduced, recipient_overflow = draw_fitted_lines(
                painter, recipient_text, recipient_rect,
                alignment_flag(recipient_alignment, vertical_alignment_flag(recipient_vertical_alignment)),
                vertical_alignment_flag(recipient_vertical_alignment),
                int(recipient_font_size), int(recipient_min_size),
                recipient_font_family, recipient_bold, recipient_italic
            )
            if was_reduced:
                stats.reduced += 1
            if recipient_overflow:
                label_overflow = True
            if label_overflow:
                stats.overflow += 1
            slot += 1
            stats.labels += 1

    painter.end()
    return stats


def render_test_sheet(output_path: Path, page_width: float, page_height: float,
                      columns: int, rows: int, margin_left: float,
                      margin_top: float, gap_x: float, gap_y: float,
                      label_width: float | None = None,
                      label_height: float | None = None,
                      corner_radius: float = 0) -> RenderStats:
    writer = QPdfWriter(str(output_path))
    writer.setPageSize(QPageSize(QSizeF(page_width, page_height), QPageSize.Unit.Millimeter))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
    writer.setResolution(72)
    painter = QPainter(writer)
    painter.setPen(QPen(Qt.GlobalColor.gray, 0.5, Qt.PenStyle.DashLine))
    page_width_points = mm(page_width)
    page_height_points = mm(page_height)
    margin_left_points = mm(margin_left)
    margin_top_points = mm(margin_top)
    painter.drawLine(margin_left_points, 0, margin_left_points, page_height_points)
    painter.drawLine(page_width_points - margin_left_points, 0,
                     page_width_points - margin_left_points, page_height_points)
    painter.drawLine(0, margin_top_points, page_width_points, margin_top_points)
    painter.drawLine(0, page_height_points - margin_top_points,
                     page_width_points, page_height_points - margin_top_points)
    label_width_points = (mm(label_width) if label_width is not None else
                          (page_width_points - mm(margin_left * 2)
                           - mm(gap_x * (columns - 1))) / columns)
    label_height_points = (mm(label_height) if label_height is not None else
                           (page_height_points - mm(margin_top * 2)
                            - mm(gap_y * (rows - 1))) / rows)
    for row in range(rows):
        for column in range(columns):
            x = mm(margin_left + column * (label_width_points / POINTS_PER_MM + gap_x))
            y = mm(margin_top + row * (label_height_points / POINTS_PER_MM + gap_y))
            rect = QRectF(x, y, label_width_points, label_height_points)
            radius = min(mm(corner_radius), rect.width() / 2, rect.height() / 2)
            painter.drawRoundedRect(rect, radius, radius)
    painter.end()
    stats = RenderStats()
    stats.pages = 1
    return stats


def render_envelope_pdf(documents: list[CsvDocument], output_path: Path,
                        envelope_size: tuple[float, float], recipient_x: float,
                        recipient_y: float, recipient_width: float,
                        recipient_height: float, show_guides: bool = False,
                        sender_x: float = 12, sender_y: float = 8,
                        sender_width: float | None = None,
                        sender_height: float = 22, sender_enabled: bool = True,
                        sender_font_family: str = "DejaVu Sans", sender_font_size: float = 8,
                        sender_bold: bool = True, sender_italic: bool = False,
                        recipient_font_family: str = "DejaVu Sans", recipient_font_size: float = 14,
                        recipient_bold: bool = True, recipient_italic: bool = False,
                        sender_alignment: str = "center", recipient_alignment: str = "center",
                        sender_vertical_alignment: str = "top",
                        recipient_vertical_alignment: str = "center",
                        postal_code_enabled: bool = False, postal_code_x: float = 20,
                        postal_code_y: float = 78, postal_code_width: float = 60,
                        postal_code_height: float = 16,
                        postal_code_offset_x: float = 0,
                        postal_code_offset_y: float = 0) -> RenderStats:
    width_mm, height_mm = envelope_size
    writer = QPdfWriter(str(output_path))
    writer.setPageSize(QPageSize(QSizeF(width_mm, height_mm), QPageSize.Unit.Millimeter))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
    writer.setResolution(72)
    painter = QPainter(writer)
    painter.setPen(Qt.GlobalColor.black)
    stats = RenderStats()

    for document in documents:
        for index, recipient in enumerate(document.recipients):
            if index or stats.labels:
                writer.newPage()
            stats.pages += 1
            sender_rect = QRectF(mm(sender_x), mm(sender_y),
                                 mm(sender_width if sender_width is not None else width_mm * 0.42),
                                 mm(sender_height))
            if sender_enabled:
                sender_text = "\n".join(document.sender.lines)
                _, sender_was_reduced, sender_overflow = draw_fitted_lines(
                    painter, sender_text, sender_rect,
                    alignment_flag(sender_alignment, vertical_alignment_flag(sender_vertical_alignment)),
                    vertical_alignment_flag(sender_vertical_alignment),
                    int(sender_font_size), 4,
                    sender_font_family, sender_bold, sender_italic
                )
                if sender_was_reduced:
                    stats.reduced += 1
                if sender_overflow:
                    stats.overflow += 1

            recipient_rect = QRectF(mm(recipient_x), mm(recipient_y),
                                    mm(recipient_width), mm(recipient_height))
            if show_guides:
                painter.save()
                painter.setPen(QPen(Qt.GlobalColor.gray, 0.5, Qt.PenStyle.DashLine))
                painter.drawRect(QRectF(0, 0, mm(width_mm), mm(height_mm)))
                painter.drawRect(recipient_rect)
                painter.restore()
            recipient_text = format_recipient_text(recipient, not postal_code_enabled)
            recipient_fonts, was_reduced, recipient_overflow = draw_fitted_lines(
                painter, recipient_text, recipient_rect,
                alignment_flag(recipient_alignment, vertical_alignment_flag(recipient_vertical_alignment)),
                vertical_alignment_flag(recipient_vertical_alignment),
                int(recipient_font_size), 4,
                recipient_font_family, recipient_bold, recipient_italic
            )
            if was_reduced:
                stats.reduced += 1
            if recipient_overflow:
                stats.overflow += 1
            if postal_code_enabled:
                postal_rect = QRectF(mm(postal_code_x), mm(postal_code_y),
                                     mm(postal_code_width), mm(postal_code_height))
                postal_font = QFont(max(recipient_fonts, key=lambda font: font.pointSizeF()))
                postal_code = format_postal_code(recipient.postal_code)
                draw_postal_code(
                    painter, postal_rect, postal_code, postal_font, show_guides,
                    postal_code_offset_x, postal_code_offset_y,
                )
            stats.labels += 1

    painter.end()
    return stats


class EnvelopeEditorDialog(QDialog):
    def __init__(self, layout_data: EnvelopeLayout, sender_text: str = "Expéditeur",
                 recipient_text: str = "Destinataire", parent: QWidget | None = None,
                 postal_code_text: str = "00000", print_test_callback=None):
        super().__init__(parent)
        self.setWindowTitle("Ajuster l’enveloppe")
        self.setMinimumWidth(420)
        self.resize(430, 500)
        self.setModal(True)
        self.layout_data = layout_data
        self.print_test_callback = print_test_callback
        self._closing_linked_windows = False
        if Path(layout_data.background_image).suffix.lower() not in {".jpg", ".jpeg"}:
            self.layout_data.background_image = ""
        self.page_width = self.number(layout_data.page_width, 80, 500)
        self.page_height = self.number(layout_data.page_height, 50, 300)
        self.page_width.setMaximumWidth(110)
        self.page_height.setMaximumWidth(110)
        self.page_width.valueChanged.connect(self.update_page)
        self.page_height.valueChanged.connect(self.update_page)
        self.sender_font = QFontComboBox()
        self.sender_font.setMaximumWidth(260)
        self.sender_enabled = QCheckBox("Afficher l’expéditeur")
        self.sender_enabled.setChecked(layout_data.sender_enabled)
        self.sender_font.setCurrentFont(QFont(layout_data.sender_font_family))
        self.sender_size = self.number(layout_data.sender_font_size, 4, 40)
        self.sender_bold = QCheckBox("Gras")
        self.sender_bold.setChecked(layout_data.sender_bold)
        self.sender_italic = QCheckBox("Italique")
        self.sender_italic.setChecked(layout_data.sender_italic)
        self.sender_alignment = self._alignment(layout_data.sender_alignment)
        self.sender_vertical_alignment = self._vertical_alignment(layout_data.sender_vertical_alignment)
        self.recipient_font = QFontComboBox()
        self.recipient_font.setMaximumWidth(260)
        self.recipient_font.setCurrentFont(QFont(layout_data.recipient_font_family))
        self.recipient_size = self.number(layout_data.recipient_font_size, 4, 40)
        self.recipient_bold = QCheckBox("Gras")
        self.recipient_bold.setChecked(layout_data.recipient_bold)
        self.recipient_italic = QCheckBox("Italique")
        self.recipient_italic.setChecked(layout_data.recipient_italic)
        self.recipient_alignment = self._alignment(layout_data.recipient_alignment)
        self.recipient_vertical_alignment = self._vertical_alignment(layout_data.recipient_vertical_alignment)
        self.postal_code_enabled = QCheckBox("Afficher le code postal dans des cases")
        self.postal_code_enabled.setChecked(layout_data.postal_code_enabled)
        self.load_background_button = QPushButton("Charger un fond")
        self.load_background_button.setToolTip(
            "Chargez une numérisation de la face de l'enveloppe (format jpeg)"
        )
        self.load_background_button.clicked.connect(self.load_background)
        self.remove_background_button = QPushButton()
        self.remove_background_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        )
        self.remove_background_button.setIconSize(QSize(16, 16))
        self.remove_background_button.setFixedWidth(32)
        self.remove_background_button.setToolTip("Enlever le fond")
        self.remove_background_button.setAccessibleName("Enlever le fond")
        self.remove_background_button.setEnabled(bool(layout_data.background_image))
        self.remove_background_button.clicked.connect(self.remove_background)
        for control in (self.sender_enabled, self.sender_font, self.sender_size, self.sender_bold,
                self.sender_italic, self.sender_alignment, self.sender_vertical_alignment,
                self.recipient_font,
                self.recipient_size, self.recipient_bold, self.recipient_italic,
            self.recipient_alignment, self.recipient_vertical_alignment, self.postal_code_enabled):
            if hasattr(control, "valueChanged"):
                control.valueChanged.connect(self.update_typography)
            if hasattr(control, "currentFontChanged"):
                control.currentFontChanged.connect(self.update_typography)
            if hasattr(control, "currentIndexChanged"):
                control.currentIndexChanged.connect(self.update_typography)
            if hasattr(control, "stateChanged"):
                control.stateChanged.connect(self.update_typography)
        self.canvas = EnvelopeCanvas(
            layout_data, sender_text, recipient_text, postal_code_text, self
        )
        self.canvas.backgroundChanged.connect(self.update_background_button)
        self.canvas_window = QDialog(
            self,
            Qt.WindowType.Tool | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowMinMaxButtonsHint | Qt.WindowType.WindowCloseButtonHint,
        )
        self.canvas_window.setWindowTitle("Aperçu de l’enveloppe")
        self.canvas_window.resize(760, 560)
        self.canvas_window.setModal(False)
        self.canvas_window.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        canvas_window_layout = QVBoxLayout(self.canvas_window)
        canvas_scroll = QScrollArea()
        self.canvas_scroll = canvas_scroll
        canvas_scroll.setWidgetResizable(False)
        canvas_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        canvas_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        canvas_scroll.setWidget(self.canvas)
        canvas_window_layout.addWidget(canvas_scroll)
        self.canvas_window.finished.connect(self.canvas_window_closed)
        zoom_out_button = QPushButton("−")
        zoom_out_button.setToolTip("Réduire le zoom")
        zoom_out_button.clicked.connect(lambda: self.canvas.set_zoom(self.canvas.zoom - 0.25))
        zoom_reset_button = QPushButton("100 %")
        zoom_reset_button.setToolTip("Réinitialiser le zoom")
        zoom_reset_button.clicked.connect(lambda: self.canvas.set_zoom(1.0))
        zoom_in_button = QPushButton("+")
        zoom_in_button.setToolTip("Augmenter le zoom")
        zoom_in_button.clicked.connect(lambda: self.canvas.set_zoom(self.canvas.zoom + 0.25))
        zoom_label = QLabel("Zoom")
        zoom_value = QLabel("100 %")
        self.canvas.zoomChanged.connect(lambda value: zoom_value.setText(f"{round(value * 100)} %"))
        zoom_controls = QHBoxLayout()
        zoom_controls.addWidget(zoom_label)
        zoom_controls.addWidget(zoom_out_button)
        zoom_controls.addWidget(zoom_reset_button)
        zoom_controls.addWidget(zoom_in_button)
        zoom_controls.addWidget(zoom_value)
        zoom_controls.addStretch()
        zoom_controls.addWidget(self.load_background_button)
        zoom_controls.addWidget(self.remove_background_button)
        canvas_window_layout.insertLayout(0, zoom_controls)

        settings = QVBoxLayout()

        dimensions = QGridLayout()
        dimensions.addWidget(QLabel("Largeur enveloppe (mm)"), 0, 0)
        dimensions.addWidget(self.page_width, 0, 1)
        dimensions.addWidget(QLabel("Hauteur enveloppe (mm)"), 1, 0)
        dimensions.addWidget(self.page_height, 1, 1)
        dimensions.setHorizontalSpacing(4)
        settings.addLayout(dimensions)

        sender_group = QVBoxLayout()
        sender_group.addWidget(self.sender_enabled)
        sender_font_row = QHBoxLayout()
        sender_font_row.addWidget(QLabel("Police"))
        sender_font_row.addWidget(self.sender_font)
        sender_font_row.addWidget(self.sender_size)
        sender_font_row.addStretch()
        sender_group.addLayout(sender_font_row)
        sender_style = QHBoxLayout()
        sender_style.addWidget(self.sender_bold)
        sender_style.addWidget(self.sender_italic)
        sender_style.addWidget(self.sender_alignment)
        sender_style.addWidget(self.sender_vertical_alignment)
        sender_style.addStretch()
        sender_group.addLayout(sender_style)
        settings.addWidget(self._separator())
        settings.addWidget(QLabel("Expéditeur"))
        settings.addLayout(sender_group)

        recipient_group = QVBoxLayout()
        recipient_font_row = QHBoxLayout()
        recipient_font_row.addWidget(QLabel("Police"))
        recipient_font_row.addWidget(self.recipient_font)
        recipient_font_row.addWidget(self.recipient_size)
        recipient_font_row.addStretch()
        recipient_group.addLayout(recipient_font_row)
        recipient_style = QHBoxLayout()
        recipient_style.addWidget(self.recipient_bold)
        recipient_style.addWidget(self.recipient_italic)
        recipient_style.addWidget(self.recipient_alignment)
        recipient_style.addWidget(self.recipient_vertical_alignment)
        recipient_style.addStretch()
        recipient_group.addLayout(recipient_style)
        settings.addWidget(self._separator())
        settings.addWidget(QLabel("Destinataire"))
        settings.addLayout(recipient_group)

        settings.addWidget(self._separator())
        settings.addWidget(self.postal_code_enabled)

        reset_button = QPushButton("Réinitialiser")
        reset_button.clicked.connect(self.reset_layout)
        cancel_button = QPushButton("Annuler")
        cancel_button.clicked.connect(self.reject)
        apply_button = QPushButton("Utiliser cette mise en page")
        apply_button.clicked.connect(self.accept)
        test_button = QPushButton("Imprimer une enveloppe test")
        test_button.clicked.connect(self.print_test)
        test_row = QHBoxLayout()
        test_row.addWidget(test_button)
        test_row.addStretch()
        final_row = QHBoxLayout()
        final_row.addWidget(reset_button)
        final_row.addStretch()
        final_row.addWidget(cancel_button)
        final_row.addWidget(apply_button)
        buttons = QVBoxLayout()
        buttons.addLayout(test_row)
        buttons.addLayout(final_row)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)
        settings.setSpacing(5)
        layout.addLayout(settings)
        layout.addLayout(buttons)
        self.show_canvas_window()

    def print_test(self) -> None:
        if self.print_test_callback is not None:
            self.update_typography()
            self.print_test_callback(self.layout_data)

    def show_canvas_window(self) -> None:
        self.canvas_window.show()
        self.canvas_window.raise_()
        self.canvas_window.activateWindow()
        QTimer.singleShot(0, self.fit_canvas_to_window)
        QTimer.singleShot(0, self.focus_canvas_window)

    def fit_canvas_to_window(self) -> None:
        viewport = self.canvas_scroll.viewport().size()
        page_width = self.layout_data.page_width * self.canvas.screen_scale()
        page_height = self.layout_data.page_height * self.canvas.screen_scale()
        available_width = viewport.width() - self.canvas.BASE_MARGIN * 2
        available_height = viewport.height() - self.canvas.BASE_MARGIN * 2
        if page_width <= 0 or page_height <= 0:
            return
        fit_zoom = min(available_width / page_width, available_height / page_height)
        self.canvas.set_zoom(max(0.5, min(5.0, fit_zoom)))

    def focus_canvas_window(self) -> None:
        if self.canvas_window.isVisible():
            self.canvas_window.raise_()
            self.canvas_window.activateWindow()
            self.canvas.setFocus()

    def canvas_window_closed(self) -> None:
        if not self._closing_linked_windows and self.isVisible():
            self._closing_linked_windows = True
            try:
                self.close()
            finally:
                self._closing_linked_windows = False

    def closeEvent(self, event) -> None:
        if not self._closing_linked_windows:
            self._closing_linked_windows = True
            self.canvas_window.close()
            self._closing_linked_windows = False
        super().closeEvent(event)

    @staticmethod
    def number(value: float, minimum: float, maximum: float) -> QDoubleSpinBox:
        control = QDoubleSpinBox()
        control.setRange(minimum, maximum)
        control.setDecimals(1)
        control.setSingleStep(0.1)
        control.setValue(value)
        return control

    @staticmethod
    def _separator() -> QFrame:
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        return separator

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

    def update_page(self) -> None:
        self.layout_data.page_width = self.page_width.value()
        self.layout_data.page_height = self.page_height.value()
        self.canvas.update()

    def update_typography(self) -> None:
        self.layout_data.sender_enabled = self.sender_enabled.isChecked()
        self.layout_data.sender_font_family = self.sender_font.currentFont().family()
        self.layout_data.sender_font_size = self.sender_size.value()
        self.layout_data.sender_bold = self.sender_bold.isChecked()
        self.layout_data.sender_italic = self.sender_italic.isChecked()
        self.layout_data.sender_alignment = self.sender_alignment.currentData()
        self.layout_data.sender_vertical_alignment = self.sender_vertical_alignment.currentData()
        self.layout_data.recipient_font_family = self.recipient_font.currentFont().family()
        self.layout_data.recipient_font_size = self.recipient_size.value()
        self.layout_data.recipient_bold = self.recipient_bold.isChecked()
        self.layout_data.recipient_italic = self.recipient_italic.isChecked()
        self.layout_data.recipient_alignment = self.recipient_alignment.currentData()
        self.layout_data.recipient_vertical_alignment = self.recipient_vertical_alignment.currentData()
        self.layout_data.postal_code_enabled = self.postal_code_enabled.isChecked()
        self.canvas.update()

    def remove_background(self) -> None:
        self.layout_data.background_image = ""
        self.remove_background_button.setEnabled(False)
        self.canvas.update()

    def load_background(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Charger un fond d’enveloppe",
            "",
            "Images JPEG (*.jpg *.jpeg)",
        )
        if path and Path(path).suffix.lower() in {".jpg", ".jpeg"}:
            self.canvas.set_background_image(path)

    def update_background_button(self, path: str) -> None:
        self.remove_background_button.setEnabled(bool(path))

    def reset_layout(self) -> None:
        defaults = EnvelopeLayout()
        self.layout_data.sender_x = 12
        self.layout_data.sender_y = 8
        self.layout_data.sender_width = self.layout_data.page_width * 0.42
        self.layout_data.sender_height = 22
        self.layout_data.recipient_x = self.layout_data.page_width * 0.52
        self.layout_data.recipient_y = self.layout_data.page_height * 0.32
        self.layout_data.recipient_width = self.layout_data.page_width * 0.41
        self.layout_data.recipient_height = self.layout_data.page_height * 0.5
        self.layout_data.sender_enabled = defaults.sender_enabled
        self.layout_data.sender_font_family = defaults.sender_font_family
        self.layout_data.sender_font_size = defaults.sender_font_size
        self.layout_data.sender_bold = defaults.sender_bold
        self.layout_data.sender_italic = defaults.sender_italic
        self.layout_data.sender_alignment = defaults.sender_alignment
        self.layout_data.sender_vertical_alignment = defaults.sender_vertical_alignment
        self.layout_data.recipient_font_family = defaults.recipient_font_family
        self.layout_data.recipient_font_size = defaults.recipient_font_size
        self.layout_data.recipient_bold = defaults.recipient_bold
        self.layout_data.recipient_italic = defaults.recipient_italic
        self.layout_data.recipient_alignment = defaults.recipient_alignment
        self.layout_data.recipient_vertical_alignment = defaults.recipient_vertical_alignment
        self.layout_data.postal_code_enabled = defaults.postal_code_enabled
        self.layout_data.background_image = defaults.background_image
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
        self.postal_code_enabled.setChecked(defaults.postal_code_enabled)
        self.remove_background_button.setEnabled(False)
        self.canvas.update()


class EnvelopeFormatDialog(QDialog):
    def __init__(self, formats: dict[str, dict], active_name: str,
                 sender_text: str = "Expéditeur", recipient_text: str = "Destinataire",
                 parent: QWidget | None = None, postal_code_text: str = "00000",
                 print_test_callback=None):
        super().__init__(parent)
        self.setWindowTitle("Formats d'enveloppes")
        self.resize(560, 420)
        self.formats = json.loads(json.dumps(formats))
        self.sender_text = sender_text
        self.recipient_text = recipient_text
        self.postal_code_text = postal_code_text
        self.print_test_callback = print_test_callback
        self.active_name = active_name
        self.current_layout = EnvelopeLayout()
        self.pending_new_name: str | None = None

        self.preset_list = QListWidget()
        self.preset_list.currentItemChanged.connect(self.select_format)
        self.name = QLineEdit()
        edit_button = QPushButton("Modifier la mise en page...")
        edit_button.clicked.connect(self.edit_format)
        save_button = QPushButton("Enregistrer le format")
        save_button.clicked.connect(self.save_format)
        use_button = QPushButton("Utiliser ce format")
        use_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Annuler")
        cancel_button.clicked.connect(self.reject)

        form = QVBoxLayout()
        form.addWidget(QLabel("Nom du format"))
        form.addWidget(self.name)
        form.addWidget(edit_button)
        form.addWidget(save_button)
        form.addStretch()
        buttons = QHBoxLayout()
        buttons.addWidget(cancel_button)
        buttons.addWidget(use_button)
        form.addLayout(buttons)
        left = QVBoxLayout()
        left.addWidget(QLabel("Formats disponibles"))
        left.addWidget(self.preset_list)
        list_actions = QHBoxLayout()
        add_button = QPushButton("+")
        add_button.setFixedWidth(32)
        add_button.setToolTip("Ajouter un nouveau format")
        add_button.setAccessibleName("Ajouter un nouveau format")
        add_button.clicked.connect(self.add_format)
        delete_button = QPushButton()
        delete_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        delete_button.setFixedWidth(32)
        delete_button.setToolTip("Supprimer le format sélectionné")
        delete_button.setAccessibleName("Supprimer le format sélectionné")
        delete_button.clicked.connect(self.delete_format)
        list_actions.addWidget(add_button)
        list_actions.addStretch()
        list_actions.addWidget(delete_button)
        left.addLayout(list_actions)
        layout = QHBoxLayout(self)
        layout.addLayout(left, 1)
        layout.addLayout(form, 1)
        self.refresh_list(active_name)

    def refresh_list(self, selected_name: str) -> None:
        self.preset_list.blockSignals(True)
        self.preset_list.clear()
        for name in self.formats:
            self.preset_list.addItem(QListWidgetItem(name))
        items = self.preset_list.findItems(selected_name, Qt.MatchFlag.MatchExactly)
        if items:
            self.preset_list.setCurrentItem(items[0])
        elif self.preset_list.count():
            self.preset_list.setCurrentRow(0)
        self.preset_list.blockSignals(False)
        item = self.preset_list.currentItem()
        if item is not None:
            self.select_format(item, None)

    def select_format(self, item: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        del previous
        if item is None:
            return
        name = item.text()
        if self.pending_new_name is not None and name != self.pending_new_name:
            self.formats.pop(self.pending_new_name, None)
            self.pending_new_name = None
        self.active_name = name
        self.name.setText(self.active_name)
        self.current_layout = EnvelopeLayout(**self.formats[self.active_name])

    def add_format(self) -> None:
        if self.pending_new_name is not None:
            self.formats.pop(self.pending_new_name, None)
            self.refresh_list(self.active_name)
        index = 1
        name = "Nouveau format"
        while name in self.formats:
            index += 1
            name = f"Nouveau format {index}"
        self.formats[name] = asdict(EnvelopeLayout())
        self.pending_new_name = name
        self.refresh_list(name)

    def edit_format(self) -> None:
        edited_layout = EnvelopeLayout(**asdict(self.current_layout))
        dialog = EnvelopeEditorDialog(
            edited_layout, self.sender_text, self.recipient_text, self,
            self.postal_code_text, self.print_test_callback
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.current_layout = dialog.layout_data

    def save_format(self) -> None:
        name = self.name.text().strip()
        if not name or self.active_name not in self.formats:
            return
        original_name = self.active_name
        if name != original_name and name in self.formats:
            QMessageBox.warning(self, "Nom déjà utilisé", "Un format porte déjà ce nom.")
            return
        self.current_layout = EnvelopeLayout(**asdict(self.current_layout))
        values = asdict(self.current_layout)
        updated_formats = dict(self.formats)
        updated_formats.pop(original_name, None)
        updated_formats[name] = values
        self.formats = updated_formats
        self.active_name = name
        if self.pending_new_name == original_name:
            self.pending_new_name = None
        self.refresh_list(name)

    def delete_format(self) -> None:
        if len(self.formats) <= 1 or self.active_name not in self.formats:
            return
        decision = QMessageBox.question(
            self,
            "Confirmer la suppression",
            f"Supprimer le format « {self.active_name} » ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if decision != QMessageBox.StandardButton.Yes:
            return
        del self.formats[self.active_name]
        self.active_name = next(iter(self.formats))
        self.pending_new_name = None
        self.refresh_list(self.active_name)

    def format_result(self) -> tuple[str, EnvelopeLayout, dict[str, dict]]:
        self.save_format()
        return self.active_name, self.current_layout, self.formats


class LabelWindow(QMainWindow):
    COPIES_ROLE = Qt.ItemDataRole.UserRole + 1
    BASE_LABEL_ROLE = Qt.ItemDataRole.UserRole + 2

    @staticmethod
    def existing_csv_directory(requested: Path) -> Path:
        default_directory = Path(__file__).resolve().parent / "csv"
        if requested.is_dir():
            return requested
        if default_directory.is_dir():
            return default_directory
        return Path(__file__).resolve().parent

    def __init__(self, directory: Path):
        super().__init__()
        self.setWindowTitle("EasyLabel - Impression d'étiquettes et d'enveloppes")
        self.setWindowIcon(application_icon())
        self.resize(860, 620)
        self.settings = QSettings("EasyLabel", "ImpressionEtiquettes")
        saved_directory = self.settings.value("csv_directory", "")
        if not saved_directory:
            saved_directory = QSettings("Tik", "ImpressionEtiquettes").value(
                "csv_directory", ""
            )
        saved_path = Path(saved_directory) if saved_directory else directory
        self.directory = self.existing_csv_directory(saved_path)
        self.files: dict[str, Path] = {}
        self.file_list = FileListWidget()
        self.file_list.itemChanged.connect(self.update_summary)
        self.file_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(self.show_file_context_menu)
        self.summary = QLabel()
        self.columns = self._spin_box(2, 1, 8)
        self.rows = self._spin_box(5, 1, 20)
        self.margin_left = self._spin_box(10, 0, 50, 1)
        self.margin_top = self._spin_box(10, 0, 50, 1)
        self.gap_x = self._spin_box(3, 0, 30, 1)
        self.gap_y = self._spin_box(3, 0, 30, 1)
        self.label_width: float | None = None
        self.label_height: float | None = None
        self.corner_radius = 0.0
        self.page_width = 210.0
        self.page_height = 297.0
        self.format_name = "A4 - 2 x 5"
        self.sender_height = 18.0
        self.sender_enabled = True
        self.sender_base_size = 9.0
        self.sender_min_size = 6.0
        self.sender_offset_x = 0.0
        self.sender_offset_y = 0.0
        self.recipient_offset_x = 0.0
        self.recipient_offset_y = 0.0
        self.sender_width = 96.0
        self.recipient_width = 100.0
        self.recipient_height = 60.0
        self.sender_font_family = "DejaVu Sans Condensed"
        self.sender_font_size = 9.0
        self.sender_bold = True
        self.sender_italic = False
        self.sender_alignment = "center"
        self.sender_vertical_alignment = "top"
        self.recipient_font_family = "DejaVu Sans"
        self.recipient_font_size = 15.0
        self.recipient_bold = True
        self.recipient_italic = False
        self.recipient_alignment = "center"
        self.recipient_vertical_alignment = "center"
        self.format_storage_path = self.directory / "formats.json"
        self.available_formats = load_formats(self.format_storage_path)
        self.preset_info = QLabel()
        self.preset_info.setStyleSheet(
            "QLabel { color: #3f4a56; background: #eef2f5; border: 1px solid #cbd5dc; "
            "border-radius: 4px; padding: 5px 9px; }"
        )
        self.show_guides = QCheckBox("Contours de calibration")
        self.start_column = self._spin_box(1, 1, 8, 1)
        self.start_row = self._spin_box(1, 1, 20, 1)
        self.columns.valueChanged.connect(self.update_start_ranges)
        self.rows.valueChanged.connect(self.update_start_ranges)
        self.columns.valueChanged.connect(self.update_summary)
        self.rows.valueChanged.connect(self.update_summary)
        self.start_column.valueChanged.connect(self.update_summary)
        self.start_row.valueChanged.connect(self.update_summary)
        self.mode = QComboBox()
        self.mode.addItems(["Planche d'étiquettes", "Enveloppes"])
        self.mode.currentIndexChanged.connect(self.update_mode_controls)
        self.mode.currentIndexChanged.connect(self.update_summary)
        self.envelope_presets = self.load_envelope_presets()
        self.envelope_preset_name = self.settings.value(
            "envelope_preset", next(iter(self.envelope_presets))
        )
        if self.envelope_preset_name not in self.envelope_presets:
            self.envelope_preset_name = next(iter(self.envelope_presets))
        self.envelope_format = QComboBox()
        for name, values in self.envelope_presets.items():
            self.envelope_format.addItem(
                name, (values["page_width"], values["page_height"])
            )
        self.envelope_page_width, self.envelope_page_height = self.envelope_format.currentData()
        self.envelope_format.currentIndexChanged.connect(self.update_envelope_format)
        self.envelope_x = self._spin_box(115, 0, 220, 1)
        self.envelope_y = self._spin_box(35, 0, 162, 1)
        self.envelope_width = self._spin_box(90, 20, 220, 1)
        self.envelope_height = self._spin_box(55, 20, 162, 1)
        self.envelope_sender_x = 12.0
        self.envelope_sender_y = 8.0
        self.envelope_sender_width = 92.0
        self.envelope_sender_height = 22.0
        self.envelope_sender_enabled = True
        self.envelope_sender_font_family = "DejaVu Sans"
        self.envelope_sender_font_size = 8.0
        self.envelope_sender_bold = True
        self.envelope_sender_italic = False
        self.envelope_sender_alignment = "center"
        self.envelope_sender_vertical_alignment = "top"
        self.envelope_recipient_font_family = "DejaVu Sans"
        self.envelope_recipient_font_size = 14.0
        self.envelope_recipient_bold = True
        self.envelope_recipient_italic = False
        self.envelope_recipient_alignment = "center"
        self.envelope_recipient_vertical_alignment = "center"
        self.envelope_postal_code_enabled = False
        self.envelope_postal_code_x = 20.0
        self.envelope_postal_code_y = 78.0
        self.envelope_postal_code_width = 60.0
        self.envelope_postal_code_height = 16.0
        self.envelope_postal_code_offset_x = 0.0
        self.envelope_postal_code_offset_y = 0.0
        self.printers = QComboBox()
        self.load_printers()

        self.select_all_checkbox = QCheckBox("Sélectionner tous les fichiers")
        self.select_all_checkbox.setTristate(True)
        self.select_all_checkbox.stateChanged.connect(self.select_all_changed)
        self.global_copies = self._spin_box(1, 1, 99)
        self.global_copies.valueChanged.connect(self.update_summary)
        self.file_filter = QLineEdit()
        self.file_filter.setPlaceholderText("Filtrer les fichiers...")
        self.file_filter.setClearButtonEnabled(True)
        self.file_filter.textChanged.connect(self.filter_files)
        self.export_button = QPushButton("Exporter le PDF")
        self.export_button.clicked.connect(self.export_pdf)
        self.print_button = QPushButton("Imprimer")
        self.print_button.clicked.connect(lambda checked=False: self.print_pdf())

        file_menu = self.menuBar().addMenu("Fichier")
        choose_directory_action = file_menu.addAction("Choisir le dossier CSV...")
        choose_directory_action.triggered.connect(self.choose_directory)
        refresh_files_action = file_menu.addAction("Actualiser les fichiers CSV")
        refresh_files_action.triggered.connect(self.refresh_files)
        file_menu.addSeparator()
        export_formats_action = file_menu.addAction("Exporter les formats...")
        export_formats_action.triggered.connect(self.export_formats)
        import_formats_action = file_menu.addAction("Importer des formats...")
        import_formats_action.triggered.connect(self.import_formats)

        mode_menu = self.menuBar().addMenu("Mode")
        mode_group = QActionGroup(self)
        self.label_mode_action = QAction("Planche d'étiquettes", self)
        self.label_mode_action.setCheckable(True)
        self.label_mode_action.triggered.connect(lambda: self.mode.setCurrentIndex(0))
        self.envelope_mode_action = QAction("Enveloppes", self)
        self.envelope_mode_action.setCheckable(True)
        self.envelope_mode_action.triggered.connect(lambda: self.mode.setCurrentIndex(1))
        mode_group.addAction(self.label_mode_action)
        mode_group.addAction(self.envelope_mode_action)
        mode_menu.addAction(self.label_mode_action)
        mode_menu.addAction(self.envelope_mode_action)

        self.format_manager_action = self.menuBar().addAction("Gérer les formats")
        self.format_manager_action.triggered.connect(self.open_format_manager)

        about_menu = self.menuBar().addMenu("À propos")
        about_action = about_menu.addAction("À propos de l'application")
        about_action.triggered.connect(self.show_about)
        manual_action = about_menu.addAction("Manuel")
        manual_action.triggered.connect(self.show_manual)

        printer_settings = QHBoxLayout()
        buttons = QHBoxLayout()
        self.preview_button = QPushButton("Aperçu")
        self.preview_button.clicked.connect(self.preview_pdf)
        buttons.addWidget(self.preview_button)
        buttons.addWidget(self.export_button)
        buttons.addWidget(self.print_button)
        printer_settings.addStretch()
        printer_settings.addWidget(QLabel("Exemplaires globaux"))
        printer_settings.addWidget(self.global_copies)
        printer_settings.addSpacing(12)
        printer_settings.addLayout(buttons)

        layout = QVBoxLayout()
        files_header = QHBoxLayout()
        files_header.addWidget(QLabel("Fichiers CSV disponibles"))
        self.directory_info = QLabel(str(self.directory))
        self.directory_info.setToolTip(str(self.directory))
        self.directory_info.setStyleSheet("QLabel { color: #5c6873; }")
        files_header.addWidget(self.directory_info, 1)
        files_header.addWidget(self.preset_info)
        files_header.addStretch()
        selection_header = QHBoxLayout()
        selection_header.addWidget(self.select_all_checkbox)
        selection_header.addStretch()
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filtre"))
        filter_row.addWidget(self.file_filter, 1)
        layout.addLayout(files_header)
        layout.addLayout(selection_header)
        layout.addLayout(filter_row)
        layout.addWidget(self.file_list)
        layout.addWidget(self.summary)
        layout.addLayout(printer_settings)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)
        self.update_mode_controls()
        self.update_start_ranges()
        last_format = self.settings.value("last_format", "")
        if last_format:
            try:
                self.apply_format_values(LabelFormat(**json.loads(last_format)))
            except (TypeError, ValueError, json.JSONDecodeError):
                last_format = ""
        last_preset = self.settings.value("last_preset", "A4 - 2 x 5")
        if not last_format and last_preset in self.available_formats:
            self.apply_preset(last_preset)
        elif not last_format:
            self.apply_preset(next(iter(self.available_formats)))
        self.restore_envelope_layout()
        self.load_directory_files()

    def show_about(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("À propos")

        content = QVBoxLayout(dialog)
        content.addWidget(QLabel("EasyLabel - Impression d'étiquettes et d'enveloppes"))
        content.addSpacing(12)
        content.addWidget(QLabel("Pour le Syndicat SUD"))
        content.addSpacing(12)
        content.addWidget(QLabel("Par joe - 2026"))

        footer = QHBoxLayout()
        logo = QLabel()
        logo_path = Path(__file__).resolve().parent / "sud-ptt.jpg"
        logo_pixmap = QPixmap(str(logo_path))
        if not logo_pixmap.isNull():
            logo.setPixmap(logo_pixmap.scaled(
                130, 72, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        footer.addWidget(logo)
        footer.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(dialog.accept)
        footer.addWidget(buttons)
        content.addLayout(footer)

        dialog.exec()

    def show_manual(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Manuel de EasyLabel")
        dialog.resize(820, 680)

        browser = QTextBrowser(dialog)
        browser.setOpenExternalLinks(True)
        manual_path = Path(__file__).resolve().parent / "MANUEL.md"
        try:
            browser.setMarkdown(manual_path.read_text(encoding="utf-8"))
        except OSError:
            browser.setPlainText(
                "Le manuel est indisponible.\n\n"
                f"Fichier attendu : {manual_path}"
            )

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout = QVBoxLayout(dialog)
        layout.addWidget(browser)
        layout.addWidget(buttons)
        dialog.exec()

    def export_formats(self) -> None:
        mode = "envelopes" if self.mode.currentIndex() == 1 else "labels"
        default_name = "formats-enveloppes.json" if mode == "envelopes" else "formats-etiquettes.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter les formats", str(self.directory / default_name),
            "Fichiers JSON (*.json)", options=QFileDialog.Option.DontUseNativeDialog
        )
        if not path:
            return
        formats = self.envelope_presets if mode == "envelopes" else self.available_formats
        payload = {"type": "tik-formats", "version": 1, "mode": mode, "formats": formats}
        try:
            Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as error:
            QMessageBox.warning(self, "Export impossible", str(error))
            return
        QMessageBox.information(self, "Export terminé", f"Formats exportés dans :\n{path}")

    def import_formats(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Importer des formats", str(self.directory),
            "Fichiers JSON (*.json)"
        )
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            if (not isinstance(payload, dict) or payload.get("type") != "tik-formats"
                    or payload.get("version") != 1 or not isinstance(payload.get("formats"), dict)):
                raise ValueError("Ce fichier ne contient pas un export de formats valide.")
            mode = "envelopes" if self.mode.currentIndex() == 1 else "labels"
            if payload.get("mode") != mode:
                expected = "enveloppes" if mode == "envelopes" else "étiquettes"
                raise ValueError(f"Ce fichier contient des formats pour les {payload.get('mode')}, pas pour les {expected}.")
            imported = payload["formats"]
            if mode == "envelopes":
                defaults = asdict(EnvelopeLayout())
                for name, values in imported.items():
                    if isinstance(name, str) and isinstance(values, dict):
                        self.envelope_presets[name] = asdict(EnvelopeLayout(**{**defaults, **values}))
                self.save_envelope_presets()
                self.refresh_envelope_preset_controls(self.envelope_preset_name)
            else:
                for name, values in imported.items():
                    if isinstance(name, str) and isinstance(values, dict):
                        self.available_formats[name] = values
                save_formats(self.format_storage_path, self.available_formats)
                self.available_formats = load_formats(self.format_storage_path)
            QMessageBox.information(self, "Import terminé", f"{len(imported)} format(s) importé(s).")
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            QMessageBox.warning(self, "Import impossible", str(error))

    @staticmethod
    def _spin_box(value: int, minimum: int, maximum: int, step: int = 1) -> QSpinBox:
        control = QSpinBox()
        control.setRange(minimum, maximum)
        control.setValue(value)
        control.setSingleStep(step)
        return control

    def load_envelope_presets(self) -> dict[str, dict]:
        defaults = {
            "DL - 220 x 110 mm": asdict(EnvelopeLayout()),
            "C5 - 229 x 162 mm": asdict(EnvelopeLayout(
                page_width=229, page_height=162, recipient_x=120,
                recipient_y=52, recipient_width=95, recipient_height=80,
            )),
        }
        default_fields = asdict(EnvelopeLayout())
        required_fields = set(default_fields) - {
            "sender_alignment", "recipient_alignment", "postal_code_enabled",
            "postal_code_x", "postal_code_y", "postal_code_width", "postal_code_height",
            "background_image", "sender_vertical_alignment", "recipient_vertical_alignment",
        }
        saved = self.settings.value("envelope_formats", "")
        if saved:
            try:
                values = json.loads(saved)
                if isinstance(values, dict):
                    for name, data in values.items():
                        if not isinstance(name, str) or not isinstance(data, dict):
                            continue
                        if not required_fields.issubset(data):
                            continue
                        try:
                            defaults[name] = asdict(
                                EnvelopeLayout(**{**default_fields, **data})
                            )
                        except (TypeError, ValueError):
                            continue
            except (TypeError, json.JSONDecodeError):
                pass
        return defaults

    def save_envelope_presets(self) -> None:
        self.settings.setValue("envelope_formats", json.dumps(self.envelope_presets))

    def load_directory_files(self) -> None:
        for path in find_csv_files(self.directory):
            self.add_file(path)
        self.update_summary()

    def refresh_files(self) -> None:
        saved_state = {}
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            if item is not None:
                saved_state[item.data(0, Qt.ItemDataRole.UserRole)] = (
                    item.checkState(0), int(item.data(0, self.COPIES_ROLE) or 1)
                )
        self.files.clear()
        self.file_list.clear()
        for path in find_csv_files(self.directory):
            self.add_file(path)
            item = self.file_list.item(self.file_list.count() - 1)
            if item is None:
                continue
            previous = saved_state.get(str(path))
            if previous is not None:
                state, copies = previous
                item.setData(0, self.COPIES_ROLE, copies)
                item.setText(2, str(copies))
                item.setCheckState(0, state)
            self.filter_files(self.file_filter.text())

    def choose_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "Choisir le dossier des fichiers CSV", str(self.directory)
        )
        if selected:
            self.set_directory(Path(selected))

    def set_directory(self, directory: Path) -> None:
        if not directory.is_dir():
            return
        self.directory = directory
        self.settings.setValue("csv_directory", str(directory))
        self.format_storage_path = directory / "formats.json"
        self.available_formats = load_formats(self.format_storage_path)
        self.files.clear()
        self.file_list.clear()
        self.directory_info.setText(str(directory))
        self.directory_info.setToolTip(str(directory))
        self.load_directory_files()

    def add_file(self, path: Path) -> None:
        if str(path) in self.files:
            return
        document = None
        try:
            document = load_csv(path)
            label = path.name
        except ValueError as error:
            label = f"{path.name} (erreur : {error})"
        item = FileTreeItem((label, str(len(document.recipients) if document else 0), "1"))
        item.setData(0, Qt.ItemDataRole.UserRole, str(path))
        item.setData(0, self.COPIES_ROLE, 1)
        item.setData(0, self.BASE_LABEL_ROLE, label)
        if document is not None and document.issues:
            item.setIcon(0, self.file_list.warning_icon())
            item.setToolTip(0, "\n".join(document.issues))
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Unchecked)
        self.file_list.addItem(item)
        self.files[str(path)] = path

    def filter_files(self, text: str) -> None:
        query = text.strip().casefold()
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            file_name = Path(item.data(0, Qt.ItemDataRole.UserRole)).name.casefold()
            item.setHidden(bool(query) and query not in file_name)
        self.update_summary()

    def show_file_context_menu(self, position) -> None:
        item = self.file_list.itemAt(position)
        if item is None:
            return
        path = Path(item.data(0, Qt.ItemDataRole.UserRole))
        menu = QMenu(self.file_list)
        open_action = menu.addAction("Ouvrir le fichier")
        open_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        )
        copies_action = menu.addAction("Nombre d'exemplaires...")
        copies_action.triggered.connect(lambda: self.set_file_copies(item))
        menu.exec(self.file_list.mapToGlobal(position))

    def set_file_copies(self, item: QListWidgetItem) -> None:
        path = Path(item.data(0, Qt.ItemDataRole.UserRole))
        current = int(item.data(0, self.COPIES_ROLE) or 1)
        copies, accepted = QInputDialog.getInt(
            self, "Nombre d'exemplaires",
            f"Exemplaires pour {path.name} :", current, 1, 99, 1,
        )
        if not accepted:
            return
        item.setData(0, self.COPIES_ROLE, copies)
        item.setText(2, str(copies))
        self.update_summary()

    def choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Sélectionner des CSV", str(self.directory), "CSV (*.csv)")
        for path in paths:
            self.add_file(Path(path))

    def load_printers(self) -> None:
        if os.name == "nt":
            self.printers.addItem("Imprimante par défaut", "")
            return
        try:
            result = subprocess.run(
                ["lpstat", "-a"], capture_output=True, text=True, check=False, timeout=5
            )
        except (OSError, subprocess.TimeoutExpired):
            result = None
        if result is None or result.returncode:
            self.printers.addItem("Imprimante par défaut", "")
            return
        for line in result.stdout.splitlines():
            printer_name = line.split(maxsplit=1)[0] if line.split() else ""
            if printer_name:
                self.printers.addItem(printer_name, printer_name)
        if not self.printers.count():
            self.printers.addItem("Imprimante par défaut", "")

    def selected_documents(self) -> list[CsvDocument]:
        documents = []
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            if item.checkState(0) == Qt.CheckState.Checked:
                path = Path(item.data(0, Qt.ItemDataRole.UserRole))
                try:
                    document = load_csv(path)
                    documents.extend([document] * int(item.data(0, self.COPIES_ROLE) or 1))
                except (OSError, UnicodeError, ValueError, csv.Error) as error:
                    raise ValueError(f"Impossible de lire {path.name} : {error}") from error
        return documents * self.global_copies.value()

    def update_summary(self) -> None:
        documents = []
        active_selected_count = 0
        active_count = 0
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            if not item.isHidden():
                active_count += 1
                if item.checkState(0) == Qt.CheckState.Checked:
                    active_selected_count += 1
            if item.checkState(0) != Qt.CheckState.Checked:
                continue
            try:
                document = load_csv(Path(item.data(0, Qt.ItemDataRole.UserRole)))
                documents.extend([document] * int(item.data(0, self.COPIES_ROLE) or 1))
            except (OSError, UnicodeError, ValueError, csv.Error):
                continue
        documents *= self.global_copies.value()
        if active_count and active_selected_count == active_count:
            checkbox_state = Qt.CheckState.Checked
        elif active_selected_count:
            checkbox_state = Qt.CheckState.PartiallyChecked
        else:
            checkbox_state = Qt.CheckState.Unchecked
        self.select_all_checkbox.blockSignals(True)
        self.select_all_checkbox.setCheckState(checkbox_state)
        self.select_all_checkbox.blockSignals(False)
        file_count = len(documents)
        has_selected_csv = file_count > 0
        self.preview_button.setEnabled(has_selected_csv)
        self.export_button.setEnabled(has_selected_csv)
        self.print_button.setEnabled(has_selected_csv)
        label_count = sum(len(document.recipients) for document in documents)
        issue_count = sum(len(document.issues) for document in documents)
        if self.mode.currentIndex() == 1:
            page_count = label_count
        else:
            capacity = self.columns.value() * self.rows.value()
            first_capacity = capacity - ((self.start_row.value() - 1) * self.columns.value() + self.start_column.value() - 1)
            page_count = 0 if not label_count else 1 + max(0, math.ceil((label_count - first_capacity) / capacity))
        if self.mode.currentIndex() == 1:
            message = f"{file_count} fichier(s), {label_count} enveloppe(s)"
        else:
            message = f"{file_count} fichier(s), {label_count} étiquette(s), {page_count} page(s)"
        if issue_count:
            message += f" - [!] {issue_count} avertissement(s)"
        self.summary.setText(message)

    def set_all_files(self, selected: bool) -> None:
        state = Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            if not item.isHidden():
                item.setCheckState(0, state)
        self.update_summary()

    def select_all_changed(self, state: int) -> None:
        check_state = Qt.CheckState(state)
        if check_state == Qt.CheckState.PartiallyChecked:
            return
        self.set_all_files(check_state == Qt.CheckState.Checked)

    def update_mode_controls(self) -> None:
        is_envelope = self.mode.currentIndex() == 1
        self.label_mode_action.setChecked(not is_envelope)
        self.envelope_mode_action.setChecked(is_envelope)
        self.update_active_format_display()
        self.start_column.setEnabled(not is_envelope)
        self.start_row.setEnabled(not is_envelope)

    def update_active_format_display(self) -> None:
        if self.mode.currentIndex() == 1:
            text = f"Mode enveloppe : {self.envelope_format.currentText()}"
        else:
            text = f"Mode étiquette : {self.format_name}"
        self.preset_info.setText(text)

    def open_format_manager(self) -> None:
        if self.mode.currentIndex() == 1:
            self.open_envelope_formats()
        else:
            self.open_format_settings()

    def update_start_ranges(self) -> None:
        self.start_column.setMaximum(self.columns.value())
        self.start_row.setMaximum(self.rows.value())

    def open_layout_options(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Options de mise en page")
        dialog.setMinimumWidth(300)
        column = self._spin_box(self.start_column.value(), 1, self.columns.value())
        row = self._spin_box(self.start_row.value(), 1, self.rows.value())
        guides = QCheckBox("Contours de calibration")
        guides.setChecked(self.show_guides.isChecked())
        grid = QGridLayout()
        grid.addWidget(QLabel("Colonne de départ"), 0, 0)
        grid.addWidget(column, 0, 1)
        grid.addWidget(QLabel("Ligne de départ"), 1, 0)
        grid.addWidget(row, 1, 1)
        grid.addWidget(guides, 2, 0, 1, 2)
        cancel_button = QPushButton("Annuler")
        cancel_button.clicked.connect(dialog.reject)
        apply_button = QPushButton("Valider")
        apply_button.clicked.connect(dialog.accept)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel_button)
        buttons.addWidget(apply_button)
        layout = QVBoxLayout(dialog)
        layout.addLayout(grid)
        layout.addLayout(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.start_column.setValue(column.value())
            self.start_row.setValue(row.value())
            self.show_guides.setChecked(guides.isChecked())

    def update_envelope_format(self) -> None:
        name = self.envelope_format.currentText()
        if name in self.envelope_presets and name != self.envelope_preset_name:
            self.apply_envelope_preset(name)
        self.update_active_format_display()

    def apply_envelope_preset(self, name: str) -> None:
        values = self.envelope_presets.get(name)
        if values is None:
            return
        defaults = asdict(EnvelopeLayout())
        layout_data = EnvelopeLayout(**{**defaults, **values})
        self.envelope_preset_name = name
        self.settings.setValue("envelope_preset", name)
        self.envelope_page_width = layout_data.page_width
        self.envelope_page_height = layout_data.page_height
        self.envelope_sender_x = layout_data.sender_x
        self.envelope_sender_y = layout_data.sender_y
        self.envelope_sender_width = layout_data.sender_width
        self.envelope_sender_height = layout_data.sender_height
        self.envelope_sender_enabled = layout_data.sender_enabled
        self.envelope_sender_font_family = layout_data.sender_font_family
        self.envelope_sender_font_size = layout_data.sender_font_size
        self.envelope_sender_bold = layout_data.sender_bold
        self.envelope_sender_italic = layout_data.sender_italic
        self.envelope_sender_alignment = layout_data.sender_alignment
        self.envelope_sender_vertical_alignment = layout_data.sender_vertical_alignment
        self.envelope_recipient_font_family = layout_data.recipient_font_family
        self.envelope_recipient_font_size = layout_data.recipient_font_size
        self.envelope_recipient_bold = layout_data.recipient_bold
        self.envelope_recipient_italic = layout_data.recipient_italic
        self.envelope_recipient_alignment = layout_data.recipient_alignment
        self.envelope_recipient_vertical_alignment = layout_data.recipient_vertical_alignment
        self.envelope_postal_code_enabled = layout_data.postal_code_enabled
        self.envelope_postal_code_x = layout_data.postal_code_x
        self.envelope_postal_code_y = layout_data.postal_code_y
        self.envelope_postal_code_width = layout_data.postal_code_width
        self.envelope_postal_code_height = layout_data.postal_code_height
        self.envelope_postal_code_offset_x = layout_data.postal_code_offset_x
        self.envelope_postal_code_offset_y = layout_data.postal_code_offset_y
        self.envelope_x.setMaximum(max(220, round(layout_data.page_width)))
        self.envelope_y.setMaximum(max(162, round(layout_data.page_height)))
        self.envelope_width.setMaximum(max(220, round(layout_data.page_width)))
        self.envelope_height.setMaximum(max(162, round(layout_data.page_height)))
        self.envelope_x.setValue(round(layout_data.recipient_x))
        self.envelope_y.setValue(round(layout_data.recipient_y))
        self.envelope_width.setValue(round(layout_data.recipient_width))
        self.envelope_height.setValue(round(layout_data.recipient_height))
        combo_index = self.envelope_format.findText(name)
        if combo_index >= 0 and self.envelope_format.currentIndex() != combo_index:
            self.envelope_format.blockSignals(True)
            self.envelope_format.setCurrentIndex(combo_index)
            self.envelope_format.blockSignals(False)
        self.update_active_format_display()

    def refresh_envelope_preset_controls(self, active_name: str) -> None:
        self.envelope_format.blockSignals(True)
        self.envelope_format.clear()
        for name, values in self.envelope_presets.items():
            self.envelope_format.addItem(name, (values["page_width"], values["page_height"]))
        self.envelope_format.blockSignals(False)
        self.apply_envelope_preset(active_name)

    def open_envelope_formats(self) -> None:
        dialog = EnvelopeFormatDialog(
            self.envelope_presets, self.envelope_preset_name,
            self._sample_sender(), self._sample_recipient(), self,
            self._sample_postal_code(), self.print_test_envelope
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, layout_data, formats = dialog.format_result()
        self.envelope_presets = formats
        self.envelope_preset_name = name
        self.save_envelope_presets()
        self.refresh_envelope_preset_controls(name)
        self.save_envelope_layout(layout_data)

    def save_envelope_layout(self, layout_data: EnvelopeLayout) -> None:
        self.envelope_presets[self.envelope_preset_name] = asdict(layout_data)
        self.save_envelope_presets()
        self.settings.setValue("envelope_layout", json.dumps(asdict(layout_data)))

    def restore_envelope_layout(self) -> None:
        if self.envelope_preset_name in self.envelope_presets:
            self.apply_envelope_preset(self.envelope_preset_name)
            return
        saved_layout = self.settings.value("envelope_layout", "")
        if not saved_layout:
            return
        try:
            values = json.loads(saved_layout)
            layout_data = EnvelopeLayout(**{**asdict(EnvelopeLayout()), **values})
        except (TypeError, ValueError, json.JSONDecodeError):
            return
        self.envelope_x.setMaximum(max(220, round(layout_data.page_width)))
        self.envelope_y.setMaximum(max(162, round(layout_data.page_height)))
        self.envelope_width.setMaximum(max(220, round(layout_data.page_width)))
        self.envelope_height.setMaximum(max(162, round(layout_data.page_height)))
        self.envelope_page_width = layout_data.page_width
        self.envelope_page_height = layout_data.page_height
        self.envelope_sender_x = layout_data.sender_x
        self.envelope_sender_y = layout_data.sender_y
        self.envelope_sender_width = layout_data.sender_width
        self.envelope_sender_height = layout_data.sender_height
        self.envelope_sender_enabled = layout_data.sender_enabled
        self.envelope_sender_font_family = layout_data.sender_font_family
        self.envelope_sender_font_size = layout_data.sender_font_size
        self.envelope_sender_bold = layout_data.sender_bold
        self.envelope_sender_italic = layout_data.sender_italic
        self.envelope_sender_alignment = layout_data.sender_alignment
        self.envelope_sender_vertical_alignment = layout_data.sender_vertical_alignment
        self.envelope_recipient_font_family = layout_data.recipient_font_family
        self.envelope_recipient_font_size = layout_data.recipient_font_size
        self.envelope_recipient_bold = layout_data.recipient_bold
        self.envelope_recipient_italic = layout_data.recipient_italic
        self.envelope_recipient_alignment = layout_data.recipient_alignment
        self.envelope_recipient_vertical_alignment = layout_data.recipient_vertical_alignment
        self.envelope_postal_code_enabled = layout_data.postal_code_enabled
        self.envelope_postal_code_x = layout_data.postal_code_x
        self.envelope_postal_code_y = layout_data.postal_code_y
        self.envelope_postal_code_width = layout_data.postal_code_width
        self.envelope_postal_code_height = layout_data.postal_code_height
        self.envelope_x.setValue(round(layout_data.recipient_x))
        self.envelope_y.setValue(round(layout_data.recipient_y))
        self.envelope_width.setValue(round(layout_data.recipient_width))
        self.envelope_height.setValue(round(layout_data.recipient_height))
        for index in range(self.envelope_format.count()):
            if self.envelope_format.itemData(index) == (layout_data.page_width, layout_data.page_height):
                self.envelope_format.setCurrentIndex(index)
                break

    def envelope_layout(self) -> EnvelopeLayout:
        return EnvelopeLayout(
            self.envelope_page_width, self.envelope_page_height,
            self.envelope_sender_x, self.envelope_sender_y,
            self.envelope_sender_width, self.envelope_sender_height,
            self.envelope_sender_enabled,
            self.envelope_x.value(), self.envelope_y.value(),
            self.envelope_width.value(), self.envelope_height.value(),
            self.envelope_sender_font_family, self.envelope_sender_font_size,
            self.envelope_sender_bold, self.envelope_sender_italic,
            self.envelope_recipient_font_family, self.envelope_recipient_font_size,
            self.envelope_recipient_bold, self.envelope_recipient_italic,
            self.envelope_sender_alignment, self.envelope_recipient_alignment,
            self.envelope_postal_code_enabled, self.envelope_postal_code_x,
            self.envelope_postal_code_y, self.envelope_postal_code_width,
            self.envelope_postal_code_height,
            self.envelope_postal_code_offset_x, self.envelope_postal_code_offset_y,
            "", self.envelope_sender_vertical_alignment,
            self.envelope_recipient_vertical_alignment,
        )

    def open_envelope_editor(self) -> None:
        self.envelope_x.setMaximum(500)
        self.envelope_y.setMaximum(300)
        self.envelope_width.setMaximum(500)
        self.envelope_height.setMaximum(300)
        dialog = EnvelopeEditorDialog(
            self.envelope_layout(), self._sample_sender(), self._sample_recipient(), self,
            self._sample_postal_code(), self.print_test_envelope
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        edited = dialog.layout_data
        self.envelope_page_width = edited.page_width
        self.envelope_page_height = edited.page_height
        self.envelope_sender_x = edited.sender_x
        self.envelope_sender_y = edited.sender_y
        self.envelope_sender_width = edited.sender_width
        self.envelope_sender_height = edited.sender_height
        self.envelope_sender_enabled = edited.sender_enabled
        self.envelope_sender_font_family = edited.sender_font_family
        self.envelope_sender_font_size = edited.sender_font_size
        self.envelope_sender_bold = edited.sender_bold
        self.envelope_sender_italic = edited.sender_italic
        self.envelope_sender_alignment = edited.sender_alignment
        self.envelope_sender_vertical_alignment = edited.sender_vertical_alignment
        self.envelope_recipient_font_family = edited.recipient_font_family
        self.envelope_recipient_font_size = edited.recipient_font_size
        self.envelope_recipient_bold = edited.recipient_bold
        self.envelope_recipient_italic = edited.recipient_italic
        self.envelope_recipient_alignment = edited.recipient_alignment
        self.envelope_recipient_vertical_alignment = edited.recipient_vertical_alignment
        self.envelope_postal_code_enabled = edited.postal_code_enabled
        self.envelope_postal_code_x = edited.postal_code_x
        self.envelope_postal_code_y = edited.postal_code_y
        self.envelope_postal_code_width = edited.postal_code_width
        self.envelope_postal_code_height = edited.postal_code_height
        self.envelope_postal_code_offset_x = edited.postal_code_offset_x
        self.envelope_postal_code_offset_y = edited.postal_code_offset_y
        self.save_envelope_layout(edited)
        self.envelope_x.setValue(round(edited.recipient_x))
        self.envelope_y.setValue(round(edited.recipient_y))
        self.envelope_width.setValue(round(edited.recipient_width))
        self.envelope_height.setValue(round(edited.recipient_height))

    def _sample_sender(self) -> str:
        for path in self.files.values():
            try:
                document = load_csv(path)
            except ValueError:
                continue
            if document.sender.lines:
                return "\n".join(document.sender.lines)
        return "Expéditeur"

    def _sample_recipient(self) -> str:
        for path in self.files.values():
            try:
                document = load_csv(path)
            except ValueError:
                continue
            if document.recipients:
                recipient = document.recipients[0]
                return format_recipient_text(recipient)
        return "Destinataire"

    def _sample_postal_code(self) -> str:
        for path in self.files.values():
            try:
                document = load_csv(path)
            except ValueError:
                continue
            if document.recipients:
                return document.recipients[0].postal_code
        return "00000"

    def apply_preset(self, preset_name: str) -> None:
        values = self.available_formats.get(preset_name)
        if values is None:
            return
        self.format_name = preset_name
        self.settings.setValue("last_preset", preset_name)
        self.page_width = values["page_width"]
        self.page_height = values["page_height"]
        self.columns.setValue(values["columns"])
        self.rows.setValue(values["rows"])
        self.margin_left.setValue(values["margin_left"])
        self.margin_top.setValue(values["margin_top"])
        self.gap_x.setValue(values["gap_x"])
        self.gap_y.setValue(values["gap_y"])
        self.label_width = values.get("label_width")
        self.label_height = values.get("label_height")
        self.corner_radius = values.get("corner_radius", 0)
        self.sender_height = values.get("sender_height", 18)
        self.sender_enabled = values.get("sender_enabled", True)
        self.sender_base_size = values.get("sender_base_size", 9)
        self.sender_min_size = values.get("sender_min_size", 6)
        self.sender_offset_x = values.get("sender_offset_x", 0)
        self.sender_offset_y = values.get("sender_offset_y", 0)
        self.recipient_offset_x = values.get("recipient_offset_x", 0)
        self.recipient_offset_y = values.get("recipient_offset_y", 0)
        self.sender_width = values.get("sender_width", 96)
        self.recipient_width = values.get("recipient_width", 96)
        self.recipient_height = values.get("recipient_height", 60)
        self.sender_font_family = values.get("sender_font_family", "DejaVu Sans Condensed")
        self.sender_font_size = values.get("sender_font_size", self.sender_base_size)
        self.sender_bold = values.get("sender_bold", True)
        self.sender_italic = values.get("sender_italic", False)
        self.sender_alignment = values.get("sender_alignment", "center")
        self.sender_vertical_alignment = values.get("sender_vertical_alignment", "top")
        self.recipient_font_family = values.get("recipient_font_family", "DejaVu Sans")
        self.recipient_font_size = values.get("recipient_font_size", 15)
        self.recipient_bold = values.get("recipient_bold", True)
        self.recipient_italic = values.get("recipient_italic", False)
        self.recipient_alignment = values.get("recipient_alignment", "center")
        self.recipient_vertical_alignment = values.get("recipient_vertical_alignment", "center")
        self.preset_info.setText(f"Format actif : {preset_name}")

    def apply_format_values(self, selected: LabelFormat) -> None:
        self.settings.setValue("last_preset", selected.name)
        self.settings.setValue("last_format", json.dumps(asdict(selected)))
        self.format_name = selected.name
        self.page_width = selected.page_width
        self.page_height = selected.page_height
        self.columns.setValue(selected.columns)
        self.rows.setValue(selected.rows)
        self.margin_left.setValue(selected.margin_left)
        self.margin_top.setValue(selected.margin_top)
        self.gap_x.setValue(selected.gap_x)
        self.gap_y.setValue(selected.gap_y)
        self.label_width = selected.label_width
        self.label_height = selected.label_height
        self.corner_radius = selected.corner_radius
        self.sender_height = selected.sender_height
        self.sender_enabled = selected.sender_enabled
        self.sender_base_size = selected.sender_base_size
        self.sender_min_size = selected.sender_min_size
        self.sender_offset_x = selected.sender_offset_x
        self.sender_offset_y = selected.sender_offset_y
        self.recipient_offset_x = selected.recipient_offset_x
        self.recipient_offset_y = selected.recipient_offset_y
        self.sender_width = selected.sender_width
        self.recipient_width = selected.recipient_width
        self.recipient_height = selected.recipient_height
        self.sender_font_family = selected.sender_font_family
        self.sender_font_size = selected.sender_font_size
        self.sender_bold = selected.sender_bold
        self.sender_italic = selected.sender_italic
        self.sender_alignment = selected.sender_alignment
        self.sender_vertical_alignment = selected.sender_vertical_alignment
        self.start_column.setValue(selected.start_column)
        self.start_row.setValue(selected.start_row)
        self.recipient_font_family = selected.recipient_font_family
        self.recipient_font_size = selected.recipient_font_size
        self.recipient_bold = selected.recipient_bold
        self.recipient_italic = selected.recipient_italic
        self.recipient_alignment = selected.recipient_alignment
        self.recipient_vertical_alignment = selected.recipient_vertical_alignment
        self.preset_info.setText(f"Format actif : {selected.name}")

    def open_format_settings(self) -> None:
        sample_sender = "Expéditeur"
        sample_recipient = "Destinataire"
        try:
            documents = self.selected_documents()
            if not documents:
                available = find_csv_files(self.directory)
                documents = [load_csv(available[0])] if available else []
            if documents:
                document = documents[0]
                if document.sender.lines:
                    sample_sender = "\n".join(document.sender.lines)
                if document.recipients:
                    recipient = document.recipients[0]
                    sample_recipient = "\n".join(
                        value for value in (recipient.name, recipient.address,
                                            f"{recipient.postal_code} {recipient.city}") if value
                    )
        except ValueError:
            pass
        current = LabelFormat(
            self.format_name, self.page_width, self.page_height,
            self.columns.value(), self.rows.value(), self.margin_left.value(),
            self.margin_top.value(), self.gap_x.value(), self.gap_y.value(),
            self.sender_height, self.sender_base_size, self.sender_min_size,
            self.sender_offset_x, self.sender_offset_y,
            self.recipient_offset_x, self.recipient_offset_y,
            self.sender_width, self.recipient_width, self.recipient_height,
            self.sender_font_family, self.sender_font_size, self.sender_bold,
            self.sender_italic, self.recipient_font_family, self.recipient_font_size,
            self.recipient_bold, self.recipient_italic,
            self.sender_enabled,
            self.sender_alignment, self.recipient_alignment,
            self.sender_vertical_alignment, self.recipient_vertical_alignment,
            self.start_column.value(), self.start_row.value(),
            self.label_width, self.label_height, self.corner_radius,
        )
        dialog = FormatSettingsDialog(
            current, self.directory / "formats.json", sample_sender,
            sample_recipient, self, self.print_test_page_format,
            self.apply_format_values
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dialog.format_result()
        self.available_formats = load_formats(self.format_storage_path)
        self.apply_format_values(selected)
        self.preset_info.setText(f"Format actif : {selected.name}")

    def print_test_page_format(self, selected: LabelFormat) -> None:
        self.apply_format_values(selected)
        self.print_pdf(test_page_override=True)

    def create_pdf(self, show_guides: bool | None = None,
                   test_page: bool | None = None) -> tuple[Path, RenderStats]:
        documents = self.selected_documents()
        if test_page is None:
            test_page = getattr(self, "_test_page_requested", False)
        if test_page:
            file_descriptor, output_name = tempfile.mkstemp(prefix="etiquettes-test-", suffix=".pdf")
            Path(output_name).unlink(missing_ok=True)
            os.close(file_descriptor)
            output = Path(output_name)
            try:
                stats = render_test_sheet(
                    output, self.page_width, self.page_height,
                    self.columns.value(), self.rows.value(),
                    self.margin_left.value(), self.margin_top.value(),
                    self.gap_x.value(), self.gap_y.value(),
                    self.label_width, self.label_height,
                    self.corner_radius,
                )
            except Exception:
                output.unlink(missing_ok=True)
                raise
            return output, stats
        if not documents:
            raise ValueError("Sélectionnez au moins un fichier CSV")
        if show_guides is None:
            show_guides = self.show_guides.isChecked()
        file_descriptor, output_name = tempfile.mkstemp(prefix="etiquettes-", suffix=".pdf")
        Path(output_name).unlink(missing_ok=True)
        os.close(file_descriptor)
        output = Path(output_name)
        try:
            if self.mode.currentIndex() == 1:
                stats = render_envelope_pdf(
                    documents, output, (self.envelope_page_width, self.envelope_page_height),
                    self.envelope_x.value(), self.envelope_y.value(),
                    self.envelope_width.value(), self.envelope_height.value()
                    , show_guides, self.envelope_sender_x,
                    self.envelope_sender_y, self.envelope_sender_width,
                    self.envelope_sender_height, self.envelope_sender_enabled,
                    self.envelope_sender_font_family,
                    self.envelope_sender_font_size, self.envelope_sender_bold,
                    self.envelope_sender_italic, self.envelope_recipient_font_family,
                    self.envelope_recipient_font_size, self.envelope_recipient_bold,
                    self.envelope_recipient_italic,
                    self.envelope_sender_alignment, self.envelope_recipient_alignment,
                    self.envelope_sender_vertical_alignment,
                    self.envelope_recipient_vertical_alignment,
                    self.envelope_postal_code_enabled, self.envelope_postal_code_x,
                    self.envelope_postal_code_y, self.envelope_postal_code_width,
                    self.envelope_postal_code_height,
                    self.envelope_postal_code_offset_x,
                    self.envelope_postal_code_offset_y,
                )
            else:
                stats = render_pdf(documents, output, self.columns.value(), self.rows.value(),
                                   self.margin_left.value(), self.margin_top.value(),
                                   self.gap_x.value(), self.gap_y.value(),
                                   self.start_column.value(), self.start_row.value(),
                                   self.page_width, self.page_height,
                                   show_guides, self.sender_height,
                                   self.sender_base_size, self.sender_min_size,
                                   self.sender_offset_x, self.sender_offset_y,
                                   self.recipient_offset_x, self.recipient_offset_y,
                                   self.sender_width, self.recipient_width, self.recipient_height,
                                   self.sender_font_family, self.sender_font_size,
                                   self.sender_bold, self.sender_italic,
                                   self.recipient_font_family, self.recipient_font_size,
                                   self.recipient_bold, self.recipient_italic,
                                   6, self.sender_enabled,
                                   self.sender_alignment, self.recipient_alignment,
                                   self.sender_vertical_alignment,
                                   self.recipient_vertical_alignment,
                                   self.label_width, self.label_height,
                                   self.corner_radius)
        except Exception:
            output.unlink(missing_ok=True)
            raise
        return output, stats

    @staticmethod
    def render_summary(stats: RenderStats, verb: str) -> str:
        return f"{stats.labels} étiquette(s) {verb}.\n{stats.pages} page(s) à imprimer."

    def export_pdf(self) -> None:
        temporary_pdf = None
        try:
            temporary_pdf, stats = self.create_pdf(show_guides=False)
            output, _ = QFileDialog.getSaveFileName(
                self, "Exporter le PDF", str(self.directory / "etiquettes.pdf"),
                "PDF (*.pdf)", options=QFileDialog.Option.DontUseNativeDialog
            )
            if output:
                Path(output).write_bytes(temporary_pdf.read_bytes())
            if output:
                QMessageBox.information(self, "PDF créé", self.render_summary(stats, "exportée(s)"))
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Impossible de générer le PDF", str(error))
        finally:
            if temporary_pdf is not None:
                temporary_pdf.unlink(missing_ok=True)

    def preview_pdf(self) -> None:
        pdf_path = None
        try:
            pdf_path, stats = self.create_pdf(show_guides=True)
            dialog = PdfPreviewDialog(
                pdf_path, self.render_summary(stats, "préparée(s)"),
                lambda show_guides: self.create_pdf(show_guides),
                self.export_pdf, self.print_pdf, self
            )
            dialog.exec()
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Aperçu impossible", str(error))
        finally:
            if pdf_path is not None:
                pdf_path.unlink(missing_ok=True)

    def available_print_media(self, printer_name: str) -> list[tuple[str, str]]:
        media_types, _, _, _ = self.available_print_options(printer_name)
        return media_types

    def available_print_options(self, printer_name: str) -> tuple[
            list[tuple[str, str]], list[tuple[str, str]], str, str]:
        command = ["lpoptions"]
        if printer_name:
            command.extend(["-p", printer_name])
        command.append("-l")
        try:
            result = subprocess.run(command, capture_output=True, text=True,
                                    check=False, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            return [], [], "MediaType", "InputSlot"
        if result.returncode or not isinstance(result.stdout, str):
            return [], [], "MediaType", "InputSlot"
        media_types = [("Automatique", ""), ("Étiquettes (Labels)", "Labels")]
        sources = [("Automatique", "")]
        media_option = "MediaType"
        source_option = "InputSlot"
        for line in result.stdout.splitlines():
            option, separator, values = line.partition(":")
            option_name_raw = option.split("/", 1)[0].strip()
            option_name = option_name_raw.casefold()
            if not separator:
                continue
            if option_name in ("mediatype", "media-type", "media type"):
                media_types = [("Automatique", "")]
                media_option = option_name_raw
                target = media_types
            elif option_name in ("inputslot", "media-source", "mediasource", "media source"):
                sources = [("Automatique", "")]
                source_option = option_name_raw
                target = sources
            else:
                continue
            for value in values.split():
                is_default = value.startswith("*")
                value = value.lstrip("*")
                if value:
                    target.append((value + (" (par défaut)" if is_default else ""), value))
        return media_types, sources, media_option, source_option

    def choose_print_media(self, printer_name: str, envelope: bool = False) -> tuple[str, str, str, str, str] | None:
        media_types, sources, media_option, source_option = self.available_print_options(printer_name)
        if not media_types and not sources:
            return (printer_name, "Envelope", "", media_option, source_option) if envelope else (
                printer_name, "", "", media_option, source_option
            )
        desired_media = "Envelope" if envelope else "Labels"
        if not any(value.casefold() == desired_media.casefold() for _, value in media_types):
            media_types.append(("Enveloppe (Envelope)" if envelope else "Étiquettes (Labels)", desired_media))
        desired_source = ""
        if envelope:
            desired_source = next(
                (value for _, value in sources if value.casefold() == "multipurpose"),
                "",
            )
        printers = [
            (self.printers.itemText(index), str(self.printers.itemData(index) or ""))
            for index in range(self.printers.count())
        ]
        printer_options = {}
        for _, printer in printers:
            options = self.available_print_options(printer)
            option_media, option_sources, option_media_name, option_source_name = options
            if not any(value.casefold() == desired_media.casefold() for _, value in option_media):
                option_media.append((
                    "Enveloppe (Envelope)" if envelope else "Étiquettes (Labels)",
                    desired_media,
                ))
            printer_options[printer] = (
                option_media, option_sources, option_media_name, option_source_name
            )
        dialog = PrintMediaDialog(
            media_types, sources, desired_media, desired_source, self,
            printers, printer_name, printer_options,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        selected_printer, media_type, media_source = dialog.selected_options()
        selected_options = printer_options.get(selected_printer)
        if selected_options is not None:
            _, _, media_option, source_option = selected_options
        return selected_printer, media_type, media_source, media_option, source_option

    def cups_page_size(self, envelope_size: tuple[float, float] | None = None) -> str | None:
        if self.mode.currentIndex() == 0:
            if (abs(self.page_width - 210) < 0.1
                    and abs(self.page_height - 297) < 0.1):
                return "A4"
            return None
        envelope_sizes = {
            (220, 110): "EnvDL",
            (229, 162): "EnvC5",
            (225, 110): "Env10",
            (176, 125): "EnvISOB5",
            (190, 98): "EnvMonarch",
        }
        selected_width, selected_height = envelope_size or (
            self.envelope_page_width, self.envelope_page_height
        )
        for (width, height), page_size in envelope_sizes.items():
            if (abs(selected_width - width) < 0.1
                    and abs(selected_height - height) < 0.1):
                return page_size
        return None

    def print_test_envelope(self, layout_data: EnvelopeLayout) -> None:
        output = None
        try:
            sender = Sender(("Expéditeur",))
            recipient = Recipient("Destinataire Test", "1 rue de l'Impression", "00000", "Ville")
            document = CsvDocument(Path("enveloppe-test"), sender, (recipient,))
            file_descriptor, output_name = tempfile.mkstemp(
                prefix="enveloppe-test-", suffix=".pdf"
            )
            os.close(file_descriptor)
            output = Path(output_name)
            stats = render_envelope_pdf(
                [document], output, (layout_data.page_width, layout_data.page_height),
                layout_data.recipient_x, layout_data.recipient_y,
                layout_data.recipient_width, layout_data.recipient_height,
                sender_x=layout_data.sender_x, sender_y=layout_data.sender_y,
                sender_width=layout_data.sender_width,
                sender_height=layout_data.sender_height,
                sender_enabled=layout_data.sender_enabled,
                sender_font_family=layout_data.sender_font_family,
                sender_font_size=layout_data.sender_font_size,
                sender_bold=layout_data.sender_bold,
                sender_italic=layout_data.sender_italic,
                recipient_font_family=layout_data.recipient_font_family,
                recipient_font_size=layout_data.recipient_font_size,
                recipient_bold=layout_data.recipient_bold,
                recipient_italic=layout_data.recipient_italic,
                sender_alignment=layout_data.sender_alignment,
                recipient_alignment=layout_data.recipient_alignment,
                sender_vertical_alignment=layout_data.sender_vertical_alignment,
                recipient_vertical_alignment=layout_data.recipient_vertical_alignment,
                postal_code_enabled=layout_data.postal_code_enabled,
                postal_code_x=layout_data.postal_code_x,
                postal_code_y=layout_data.postal_code_y,
                postal_code_width=layout_data.postal_code_width,
                postal_code_height=layout_data.postal_code_height,
                postal_code_offset_x=layout_data.postal_code_offset_x,
                postal_code_offset_y=layout_data.postal_code_offset_y,
            )
            printer_name = self.printers.currentData()
            print_options = self.choose_print_media(printer_name, envelope=True)
            if print_options is None:
                return
            printer_name, media_type, media_source, media_option, source_option = print_options
            selected_index = self.printers.findData(printer_name)
            if selected_index >= 0:
                self.printers.setCurrentIndex(selected_index)
            confirmation = (
                f"Imprimante : {self.printers.currentText()}\n"
                f"Format : {layout_data.page_width:g} x {layout_data.page_height:g} mm\n"
                f"Source papier : {media_source or 'Automatique'}\n\n"
                "Lancer l'impression de l'enveloppe test ?"
            )
            if QMessageBox.question(
                self, "Confirmer l'impression", confirmation,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            ) != QMessageBox.StandardButton.Yes:
                return
            if os.name == "nt":
                os.startfile(str(output), "print")
            else:
                command = ["lp"]
                if printer_name:
                    command.extend(["-d", printer_name])
                page_size = self.cups_page_size((layout_data.page_width, layout_data.page_height))
                if page_size:
                    command.extend(["-o", f"media={page_size}"])
                command.extend(["-o", "print-scaling=none"])
                if media_type:
                    command.extend(["-o", f"{media_option}={media_type}"])
                if media_source:
                    command.extend(["-o", f"{source_option}={media_source}"])
                command.extend(["-n", "1", str(output)])
                result = subprocess.run(
                    command, capture_output=True, text=True, check=False, timeout=30
                )
                if result.returncode:
                    raise RuntimeError(result.stderr.strip() or "CUPS a refusé le document")
            QMessageBox.information(self, "Impression envoyée", "L'enveloppe test a été envoyée.")
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            QMessageBox.warning(self, "Impression impossible", str(error))
        finally:
            if output is not None:
                output.unlink(missing_ok=True)


    def print_pdf(self, test_page_override: bool | None = None) -> None:
        pdf_path = None
        try:
            test_page = bool(test_page_override)
            self._test_page_requested = test_page
            pdf_path, stats = self.create_pdf(show_guides=test_page)
            media_type = media_source = media_option = source_option = ""
            if os.name != "nt":
                printer_name = self.printers.currentData()
                print_options = self.choose_print_media(
                    printer_name, envelope=self.mode.currentIndex() == 1
                )
                if print_options is None:
                    return
                printer_name, media_type, media_source, media_option, source_option = print_options
                selected_index = self.printers.findData(printer_name)
                if selected_index >= 0:
                    self.printers.setCurrentIndex(selected_index)
            printer_summary = self.printers.currentText()
            mode_summary = "enveloppes" if self.mode.currentIndex() == 1 else "étiquettes"
            confirmation = (
                f"Imprimante : {printer_summary}\n"
                f"Mode : {mode_summary}\n"
                f"Exemplaires globaux : {self.global_copies.value()}\n"
                f"{'Enveloppes' if self.mode.currentIndex() == 1 else 'Étiquettes'} à imprimer : {stats.labels}\n"
                f"Pages nécessaires : {stats.pages}\n"
                f"Source papier : {media_source or 'Automatique'}\n\n"
                "Lancer l'impression ?"
            )
            if QMessageBox.question(
                self, "Confirmer l'impression", confirmation,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            ) != QMessageBox.StandardButton.Yes:
                return
            if os.name == "nt":
                os.startfile(str(pdf_path), "print")
            else:
                command = ["lp"]
                if printer_name:
                    command.extend(["-d", printer_name])
                page_size = self.cups_page_size()
                if page_size:
                    command.extend(["-o", f"media={page_size}"])
                command.extend(["-o", "print-scaling=none"])
                if media_type:
                    command.extend(["-o", f"{media_option}={media_type}"])
                if media_source:
                    command.extend(["-o", f"{source_option}={media_source}"])
                command.extend(["-n", "1"])
                command.append(str(pdf_path))
                result = subprocess.run(
                    command, capture_output=True, text=True, check=False, timeout=30
                )
                if result.returncode:
                    raise RuntimeError(result.stderr.strip() or "CUPS a refusé le document")
            verb = "de test envoyée(s)" if test_page else "envoyée(s)"
            QMessageBox.information(self, "Impression envoyée", self.render_summary(stats, verb))
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
            QMessageBox.warning(self, "Impression impossible", str(error))
        finally:
            self._test_page_requested = False
            if pdf_path is not None:
                pdf_path.unlink(missing_ok=True)


class PreviewPdfView(QPdfView):
    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.setZoomMode(QPdfView.ZoomMode.Custom)
                factor = 1.1 if delta > 0 else 1 / 1.1
                self.setZoomFactor(max(0.2, min(self.zoomFactor() * factor, 5.0)))
                event.accept()
                return
        super().wheelEvent(event)


class PdfPreviewDialog(QDialog):
    def __init__(self, pdf_path: Path, summary: str = "", regenerate=None,
                 export_callback=None, print_callback=None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Aperçu des étiquettes")
        self.resize(850, 700)
        self.pdf_path = pdf_path
        self.summary_text = summary
        self.regenerate = regenerate
        self.document = QPdfDocument(self)
        self.document.load(str(pdf_path))

        view = PreviewPdfView()
        self.view = view
        view.setDocument(self.document)
        view.setPageMode(QPdfView.PageMode.MultiPage)
        view.setZoomMode(QPdfView.ZoomMode.Custom)
        view.setZoomFactor(1.0)

        dpi_label = QLabel("DPI : 72 (PDF)")
        zoom_buttons = []
        for level in (1.0, 1.5, 2.0):
            button = QPushButton(f"x{level:g}".replace(".", ","))
            button.setCheckable(True)
            button.clicked.connect(lambda checked, value=level: self.set_preview_zoom(value))
            zoom_buttons.append(button)
        self.zoom_buttons = zoom_buttons
        zoom_value = QLabel("x1")
        self.preview_zoom_value = zoom_value
        for button in zoom_buttons:
            button.setChecked(button is zoom_buttons[0])
        fit_button = QPushButton("Largeur")
        fit_button.setToolTip("Adapter à la largeur de la fenêtre")
        fit_button.clicked.connect(self.fit_width)
        fit_page_button = QPushButton("Page")
        fit_page_button.setToolTip("Afficher la page entière dans la fenêtre")
        fit_page_button.clicked.connect(self.fit_page)
        self.guides_checkbox = QCheckBox("Contours des étiquettes")
        self.guides_checkbox.setChecked(True)
        self.guides_checkbox.stateChanged.connect(self.toggle_guides)
        toolbar = QHBoxLayout()
        toolbar.addWidget(dpi_label)
        toolbar.addWidget(QLabel("Zoom"))
        for button in zoom_buttons:
            toolbar.addWidget(button)
        toolbar.addWidget(zoom_value)
        toolbar.addWidget(fit_button)
        toolbar.addWidget(fit_page_button)
        toolbar.addWidget(self.guides_checkbox)
        toolbar.addStretch()

        close_button = QPushButton("Fermer")
        close_button.clicked.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        self.summary_label = None
        if summary:
            self.summary_label = QLabel(summary)
            self.summary_label.setStyleSheet("QLabel { color: #4d5963; padding: 3px; }")
            layout.addWidget(self.summary_label)
        layout.addWidget(view)
        export_button = QPushButton("Exporter le PDF")
        export_button.clicked.connect(export_callback)
        print_button = QPushButton("Imprimer")
        print_button.clicked.connect(print_callback)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(export_button)
        buttons.addWidget(print_button)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    def toggle_guides(self, state: int) -> None:
        if self.regenerate is None:
            return
        show_guides = Qt.CheckState(state) == Qt.CheckState.Checked
        old_path = self.pdf_path
        try:
            new_path, stats = self.regenerate(show_guides)
            self.pdf_path = new_path
            self.document.close()
            self.document.load(str(new_path))
            old_path.unlink(missing_ok=True)
            if self.summary_label is not None:
                summary = (
                    f"{stats.labels} étiquette(s) préparée(s).\n"
                    f"{stats.pages} page(s) à imprimer."
                )
                self.summary_label.setText(summary)
        except (OSError, ValueError):
            self.guides_checkbox.blockSignals(True)
            self.guides_checkbox.setChecked(not show_guides)
            self.guides_checkbox.blockSignals(False)

    def zoom_in(self) -> None:
        self.view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.view.setZoomFactor(min(self.view.zoomFactor() * 1.2, 5.0))

    def set_preview_zoom(self, value: float) -> None:
        self.view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.view.setZoomFactor(value)
        self.preview_zoom_value.setText(f"x{value:g}".replace(".", ","))
        for level, button in zip((1.0, 1.5, 2.0), self.zoom_buttons):
            button.setChecked(abs(level - value) < 0.01)

    def zoom_out(self) -> None:
        self.view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.view.setZoomFactor(max(self.view.zoomFactor() / 1.2, 0.2))

    def fit_width(self) -> None:
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)

    def fit_page(self) -> None:
        self.view.setZoomMode(QPdfView.ZoomMode.FitInView)

    def closeEvent(self, event) -> None:
        self.pdf_path.unlink(missing_ok=True)
        super().closeEvent(event)


def main() -> int:
    directory = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "csv"
    logging_rules = os.environ.get("QT_LOGGING_RULES", "")
    if logging_rules:
        logging_rules += ";"
    os.environ["QT_LOGGING_RULES"] = logging_rules + (
        "kf.notifications.warning=false;"
        "qt.qpa.wayland.warning=false;"
        "qt.qpa.xcb.warning=false"
    )
    application = QApplication(sys.argv)
    application.setWindowIcon(application_icon())
    window = LabelWindow(directory)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())