#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
import tempfile
import os
import math
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from PySide6.QtCore import QMarginsF, QSettings, QRectF, QSizeF, Qt
from PySide6.QtGui import QFont, QFontMetricsF, QMouseEvent, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QDoubleSpinBox,
    QSpinBox,
    QVBoxLayout,
    QHBoxLayout,
    QComboBox,
    QFontComboBox,
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QWidget,
)

from label_printer import CsvDocument, find_csv_files, load_csv
from format_settings import FormatSettingsDialog, LabelFormat, load_formats


POINTS_PER_MM = 72 / 25.4


def mm(value: float) -> float:
    return value * POINTS_PER_MM


class RenderStats:
    def __init__(self) -> None:
        self.labels = 0
        self.reduced = 0
        self.overflow = 0


class FileListWidget(QListWidget):
    def mousePressEvent(self, event: QMouseEvent) -> None:
        item = self.itemAt(event.position().toPoint())
        if item is not None and event.button() == Qt.MouseButton.LeftButton:
            item_rect = self.visualItemRect(item)
            if event.position().x() > item_rect.left() + 28:
                state = (Qt.CheckState.Unchecked
                         if item.checkState() == Qt.CheckState.Checked
                         else Qt.CheckState.Checked)
                item.setCheckState(state)
        super().mousePressEvent(event)


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


class EnvelopeCanvas(QWidget):
    def __init__(self, layout: EnvelopeLayout, sender_text: str = "Expéditeur",
                 recipient_text: str = "Destinataire", parent: QWidget | None = None):
        super().__init__(parent)
        self.layout_data = layout
        self.sender_text = sender_text
        self.recipient_text = recipient_text
        self.active = ""
        self.drag_mode = ""
        self.drag_start = None
        self.original_offset = (0.0, 0.0)
        self.original_size = (0.0, 0.0)
        self.setMinimumSize(640, 360)

    def scale_and_page(self) -> tuple[float, QRectF]:
        scale = min((self.width() - 80) / self.layout_data.page_width,
                    (self.height() - 80) / self.layout_data.page_height)
        page = QRectF(40, 40, self.layout_data.page_width * scale,
                      self.layout_data.page_height * scale)
        return scale, page

    def rect_for(self, element: str) -> QRectF:
        scale, page = self.scale_and_page()
        x = getattr(self.layout_data, f"{element}_x")
        y = getattr(self.layout_data, f"{element}_y")
        width = getattr(self.layout_data, f"{element}_width")
        height = getattr(self.layout_data, f"{element}_height")
        return QRectF(page.left() + x * scale, page.top() + y * scale,
                      width * scale, height * scale)

    def handle_rect(self, element: str) -> QRectF:
        rect = self.rect_for(element)
        return QRectF(rect.right() - 8, rect.bottom() - 8, 16, 16)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale, page = self.scale_and_page()
        painter.fillRect(page, Qt.GlobalColor.white)
        painter.setPen(QPen(Qt.GlobalColor.darkGray, 1))
        painter.drawRect(page)
        for element, color, text in (("sender", Qt.GlobalColor.darkBlue, self.sender_text),
                                     ("recipient", Qt.GlobalColor.darkGreen, self.recipient_text)):
            if element == "sender" and not self.layout_data.sender_enabled:
                continue
            rect = self.rect_for(element)
            painter.setPen(QPen(color, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            painter.setBrush(color)
            painter.drawRect(self.handle_rect(element))
            font = QFont(getattr(self.layout_data, f"{element}_font_family"),
                         int(getattr(self.layout_data, f"{element}_font_size")))
            font.setBold(getattr(self.layout_data, f"{element}_bold"))
            font.setItalic(getattr(self.layout_data, f"{element}_italic"))
            painter.setFont(font)
            painter.drawText(rect.adjusted(3, 3, -3, -3),
                             Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, text)
        del scale

    def mousePressEvent(self, event) -> None:
        for element in ("recipient", "sender"):
            if element == "sender" and not self.layout_data.sender_enabled:
                continue
            if self.handle_rect(element).contains(event.position()):
                self.active = element
                self.drag_mode = "resize"
                self.drag_start = event.position()
                self.original_offset = (getattr(self.layout_data, f"{element}_x"),
                                        getattr(self.layout_data, f"{element}_y"))
                self.original_size = (getattr(self.layout_data, f"{element}_width"),
                                      getattr(self.layout_data, f"{element}_height"))
                return
        for element in ("recipient", "sender"):
            if element == "sender" and not self.layout_data.sender_enabled:
                continue
            if self.rect_for(element).contains(event.position()):
                self.active = element
                self.drag_mode = "move"
                self.drag_start = event.position()
                self.original_offset = (getattr(self.layout_data, f"{element}_x"),
                                        getattr(self.layout_data, f"{element}_y"))
                return

    def mouseMoveEvent(self, event) -> None:
        if not self.active or self.drag_start is None:
            return
        scale, _ = self.scale_and_page()
        delta = event.position() - self.drag_start
        if self.drag_mode == "resize":
            width = max(20, min(self.layout_data.page_width - self.original_offset[0],
                                self.original_size[0] + delta.x() / scale))
            height = max(10, min(self.layout_data.page_height - self.original_offset[1],
                                 self.original_size[1] + delta.y() / scale))
            setattr(self.layout_data, f"{self.active}_width", round(width * 2) / 2)
            setattr(self.layout_data, f"{self.active}_height", round(height * 2) / 2)
        else:
            x = max(0, min(self.layout_data.page_width - self.original_size[0],
                           self.original_offset[0] + delta.x() / scale))
            y = max(0, min(self.layout_data.page_height - self.original_size[1],
                           self.original_offset[1] + delta.y() / scale))
            setattr(self.layout_data, f"{self.active}_x", round(x * 2) / 2)
            setattr(self.layout_data, f"{self.active}_y", round(y * 2) / 2)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
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


def render_pdf(documents: list[CsvDocument], output_path: Path, columns: int, rows: int,
               margin_left: float, margin_top: float, gap_x: float, gap_y: float,
               start_column: int = 1, start_row: int = 1,
               page_width: float = 210, page_height: float = 297,
               show_guides: bool = False, sender_height_percent: float = 34,
               sender_base_size: float = 9, sender_min_size: float = 6,
               sender_offset_x: float = 0, sender_offset_y: float = 0,
               recipient_offset_x: float = 0, recipient_offset_y: float = 0,
               sender_width: float = 96, recipient_width: float = 96,
               recipient_height: float = 60,
               sender_font_family: str = "DejaVu Sans Condensed", sender_font_size: float = 9,
               sender_bold: bool = True, sender_italic: bool = False,
               recipient_font_family: str = "DejaVu Sans", recipient_font_size: float = 15,
               recipient_bold: bool = True, recipient_italic: bool = False,
               recipient_min_size: float = 6, sender_enabled: bool = True) -> RenderStats:
    writer = QPdfWriter(str(output_path))
    writer.setPageSize(QPageSize(QSizeF(page_width, page_height), QPageSize.Unit.Millimeter))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
    writer.setResolution(72)

    page_width_points = mm(page_width)
    page_height_points = mm(page_height)
    label_width = (page_width_points - mm(margin_left * 2) - mm(gap_x * (columns - 1))) / columns
    label_height = (page_height_points - mm(margin_top * 2) - mm(gap_y * (rows - 1))) / rows
    painter = QPainter(writer)
    painter.setPen(Qt.GlobalColor.black)
    stats = RenderStats()
    slot = (start_row - 1) * columns + (start_column - 1)

    for document in documents:
        for recipient in document.recipients:
            if slot == columns * rows:
                writer.newPage()
                slot = 0
            column = slot % columns
            row = slot // columns
            x = mm(margin_left + column * (label_width / POINTS_PER_MM + gap_x))
            y = mm(margin_top + row * (label_height / POINTS_PER_MM + gap_y))
            label_rect = QRectF(x, y, label_width, label_height)
            if show_guides:
                painter.save()
                painter.setPen(QPen(Qt.GlobalColor.gray, 0.5, Qt.PenStyle.DashLine))
                painter.drawRect(label_rect)
                painter.restore()
            sender_height = label_height * sender_height_percent / 100
            sender_rect = QRectF(
                label_rect.left() + mm(2) + mm(sender_offset_x),
                label_rect.top() + mm(2) + mm(sender_offset_y),
                label_width * sender_width / 100,
                sender_height,
            )
            recipient_rect = QRectF(
                label_rect.left() + mm(2) + mm(recipient_offset_x),
                label_rect.top() + sender_height + mm(2) + mm(recipient_offset_y),
                label_width * recipient_width / 100,
                label_height * recipient_height / 100,
            )

            if sender_enabled:
                sender_text = "\n".join(document.sender.lines)
                sender_font, sender_was_reduced = fit_font(
                    sender_text, sender_rect, int(sender_font_size), int(sender_min_size),
                    sender_font_family, sender_bold, sender_italic
                )
                if sender_was_reduced:
                    stats.reduced += 1
                sender_flags = (Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
                                | Qt.TextFlag.TextWordWrap)
                sender_bounds = QFontMetricsF(sender_font).boundingRect(
                    sender_rect, int(sender_flags), sender_text
                )
                if sender_bounds.width() > sender_rect.width() or sender_bounds.height() > sender_rect.height():
                    stats.overflow += 1
                painter.setFont(sender_font)
                painter.drawText(sender_rect, sender_flags, sender_text)

            recipient_text = "\n".join(
                value for value in (recipient.name, recipient.address,
                                    f"{recipient.postal_code} {recipient.city}") if value
            )
            recipient_font, was_reduced = fit_font(
                recipient_text, recipient_rect, int(recipient_font_size), int(recipient_min_size),
                recipient_font_family, recipient_bold, recipient_italic
            )
            if was_reduced:
                stats.reduced += 1
            text_flags = (Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
                          | Qt.TextFlag.TextWordWrap)
            bounds = QFontMetricsF(recipient_font).boundingRect(
                recipient_rect, int(text_flags), recipient_text
            )
            if bounds.width() > recipient_rect.width() or bounds.height() > recipient_rect.height():
                stats.overflow += 1
            painter.setFont(recipient_font)
            painter.drawText(recipient_rect, text_flags, recipient_text)
            slot += 1
            stats.labels += 1

    painter.end()
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
                        recipient_bold: bool = True, recipient_italic: bool = False) -> RenderStats:
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
            sender_rect = QRectF(mm(sender_x), mm(sender_y),
                                 mm(sender_width if sender_width is not None else width_mm * 0.42),
                                 mm(sender_height))
            if sender_enabled:
                sender_text = "\n".join(document.sender.lines)
                sender_font, sender_was_reduced = fit_font(
                    sender_text, sender_rect, int(sender_font_size), 4,
                    sender_font_family, sender_bold, sender_italic
                )
                if sender_was_reduced:
                    stats.reduced += 1
                painter.setFont(sender_font)
                painter.drawText(sender_rect,
                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
                                 | Qt.TextFlag.TextWordWrap, sender_text)

            recipient_rect = QRectF(mm(recipient_x), mm(recipient_y),
                                    mm(recipient_width), mm(recipient_height))
            if show_guides:
                painter.save()
                painter.setPen(QPen(Qt.GlobalColor.gray, 0.5, Qt.PenStyle.DashLine))
                painter.drawRect(QRectF(0, 0, mm(width_mm), mm(height_mm)))
                painter.drawRect(recipient_rect)
                painter.restore()
            recipient_text = "\n".join(
                value for value in (recipient.name, recipient.address,
                                    f"{recipient.postal_code} {recipient.city}") if value
            )
            recipient_font, was_reduced = fit_font(
                recipient_text, recipient_rect, int(recipient_font_size), 4,
                recipient_font_family, recipient_bold, recipient_italic
            )
            if was_reduced:
                stats.reduced += 1
            text_flags = (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                          | Qt.TextFlag.TextWordWrap)
            bounds = QFontMetricsF(recipient_font).boundingRect(
                recipient_rect, int(text_flags), recipient_text
            )
            if bounds.width() > recipient_rect.width() or bounds.height() > recipient_rect.height():
                stats.overflow += 1
            painter.setFont(recipient_font)
            painter.drawText(recipient_rect, text_flags, recipient_text)
            stats.labels += 1

    painter.end()
    return stats


class EnvelopeEditorDialog(QDialog):
    def __init__(self, layout_data: EnvelopeLayout, sender_text: str = "Expéditeur",
                 recipient_text: str = "Destinataire", parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Ajuster l’enveloppe")
        self.resize(760, 560)
        self.layout_data = layout_data
        self.page_width = self.number(layout_data.page_width, 80, 500)
        self.page_height = self.number(layout_data.page_height, 50, 300)
        self.page_width.valueChanged.connect(self.update_page)
        self.page_height.valueChanged.connect(self.update_page)
        self.sender_font = QFontComboBox()
        self.sender_enabled = QCheckBox("Afficher l’expéditeur")
        self.sender_enabled.setChecked(layout_data.sender_enabled)
        self.sender_font.setCurrentFont(QFont(layout_data.sender_font_family))
        self.sender_size = self.number(layout_data.sender_font_size, 4, 40)
        self.sender_bold = QCheckBox("Gras")
        self.sender_bold.setChecked(layout_data.sender_bold)
        self.sender_italic = QCheckBox("Italique")
        self.sender_italic.setChecked(layout_data.sender_italic)
        self.recipient_font = QFontComboBox()
        self.recipient_font.setCurrentFont(QFont(layout_data.recipient_font_family))
        self.recipient_size = self.number(layout_data.recipient_font_size, 4, 40)
        self.recipient_bold = QCheckBox("Gras")
        self.recipient_bold.setChecked(layout_data.recipient_bold)
        self.recipient_italic = QCheckBox("Italique")
        self.recipient_italic.setChecked(layout_data.recipient_italic)
        for control in (self.sender_enabled, self.sender_font, self.sender_size, self.sender_bold,
                        self.sender_italic, self.recipient_font, self.recipient_size,
                        self.recipient_bold, self.recipient_italic):
            if hasattr(control, "valueChanged"):
                control.valueChanged.connect(self.update_typography)
            if hasattr(control, "currentFontChanged"):
                control.currentFontChanged.connect(self.update_typography)
            if hasattr(control, "stateChanged"):
                control.stateChanged.connect(self.update_typography)
        self.canvas = EnvelopeCanvas(layout_data, sender_text, recipient_text, self)

        settings = QGridLayout()
        settings.addWidget(QLabel("Largeur enveloppe (mm)"), 0, 0)
        settings.addWidget(self.page_width, 0, 1)
        settings.addWidget(QLabel("Hauteur enveloppe (mm)"), 0, 2)
        settings.addWidget(self.page_height, 0, 3)
        settings.addWidget(QLabel("Police expéditeur"), 1, 0)
        settings.addWidget(self.sender_font, 1, 1)
        sender_style = QHBoxLayout()
        sender_style.addWidget(self.sender_size)
        sender_style.addWidget(self.sender_bold)
        sender_style.addWidget(self.sender_italic)
        settings.addLayout(sender_style, 1, 2, 1, 2)
        settings.addWidget(self.sender_enabled, 2, 0, 1, 4)
        settings.addWidget(QLabel("Police destinataire"), 3, 0)
        settings.addWidget(self.recipient_font, 3, 1)
        recipient_style = QHBoxLayout()
        recipient_style.addWidget(self.recipient_size)
        recipient_style.addWidget(self.recipient_bold)
        recipient_style.addWidget(self.recipient_italic)
        settings.addLayout(recipient_style, 3, 2, 1, 2)
        instructions = QLabel("Faites glisser les blocs ou leur poignée pour les ajuster.")
        reset_button = QPushButton("Réinitialiser")
        reset_button.clicked.connect(self.reset_layout)
        cancel_button = QPushButton("Annuler")
        cancel_button.clicked.connect(self.reject)
        apply_button = QPushButton("Utiliser cette mise en page")
        apply_button.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addWidget(reset_button)
        buttons.addStretch()
        buttons.addWidget(cancel_button)
        buttons.addWidget(apply_button)
        layout = QVBoxLayout(self)
        layout.addLayout(settings)
        layout.addWidget(instructions)
        layout.addWidget(self.canvas)
        layout.addLayout(buttons)

    @staticmethod
    def number(value: float, minimum: float, maximum: float) -> QDoubleSpinBox:
        control = QDoubleSpinBox()
        control.setRange(minimum, maximum)
        control.setDecimals(1)
        control.setSingleStep(1)
        control.setValue(value)
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
        self.layout_data.recipient_font_family = self.recipient_font.currentFont().family()
        self.layout_data.recipient_font_size = self.recipient_size.value()
        self.layout_data.recipient_bold = self.recipient_bold.isChecked()
        self.layout_data.recipient_italic = self.recipient_italic.isChecked()
        self.canvas.update()

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
        self.layout_data.recipient_font_family = defaults.recipient_font_family
        self.layout_data.recipient_font_size = defaults.recipient_font_size
        self.layout_data.recipient_bold = defaults.recipient_bold
        self.layout_data.recipient_italic = defaults.recipient_italic
        self.sender_enabled.setChecked(defaults.sender_enabled)
        self.sender_font.setCurrentFont(QFont(defaults.sender_font_family))
        self.sender_size.setValue(defaults.sender_font_size)
        self.sender_bold.setChecked(defaults.sender_bold)
        self.sender_italic.setChecked(defaults.sender_italic)
        self.recipient_font.setCurrentFont(QFont(defaults.recipient_font_family))
        self.recipient_size.setValue(defaults.recipient_font_size)
        self.recipient_bold.setChecked(defaults.recipient_bold)
        self.recipient_italic.setChecked(defaults.recipient_italic)
        self.canvas.update()


class LabelWindow(QMainWindow):
    def __init__(self, directory: Path):
        super().__init__()
        self.setWindowTitle("Impression d'étiquettes")
        self.resize(860, 620)
        self.settings = QSettings("Tik", "ImpressionEtiquettes")
        saved_directory = self.settings.value("csv_directory", "")
        saved_path = Path(saved_directory) if saved_directory else directory
        self.directory = saved_path if saved_path.is_dir() else directory
        self.files: dict[str, Path] = {}
        self.file_list = FileListWidget()
        self.file_list.itemChanged.connect(self.update_summary)
        self.summary = QLabel()
        self.columns = self._spin_box(2, 1, 8)
        self.rows = self._spin_box(5, 1, 20)
        self.margin_left = self._spin_box(10, 0, 50, 1)
        self.margin_top = self._spin_box(10, 0, 50, 1)
        self.gap_x = self._spin_box(3, 0, 30, 1)
        self.gap_y = self._spin_box(3, 0, 30, 1)
        self.page_width = 210.0
        self.page_height = 297.0
        self.format_name = "A4 - 2 x 5"
        self.sender_height_percent = 34.0
        self.sender_enabled = True
        self.sender_base_size = 9.0
        self.sender_min_size = 6.0
        self.sender_offset_x = 0.0
        self.sender_offset_y = 0.0
        self.recipient_offset_x = 0.0
        self.recipient_offset_y = 0.0
        self.sender_width = 96.0
        self.recipient_width = 96.0
        self.recipient_height = 60.0
        self.sender_font_family = "DejaVu Sans Condensed"
        self.sender_font_size = 9.0
        self.sender_bold = True
        self.sender_italic = False
        self.recipient_font_family = "DejaVu Sans"
        self.recipient_font_size = 15.0
        self.recipient_bold = True
        self.recipient_italic = False
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
        self.envelope_format = QComboBox()
        self.envelope_format.addItem("DL - 220 x 110 mm", (220.0, 110.0))
        self.envelope_format.addItem("C5 - 229 x 162 mm", (229.0, 162.0))
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
        self.envelope_recipient_font_family = "DejaVu Sans"
        self.envelope_recipient_font_size = 14.0
        self.envelope_recipient_bold = True
        self.envelope_recipient_italic = False
        self.printers = QComboBox()
        self.load_printers()

        self.select_all_checkbox = QCheckBox("Sélectionner tous les fichiers")
        self.select_all_checkbox.setTristate(True)
        self.select_all_checkbox.stateChanged.connect(self.select_all_changed)
        export_button = QPushButton("Exporter le PDF")
        export_button.clicked.connect(self.export_pdf)
        print_button = QPushButton("Imprimer")
        print_button.clicked.connect(self.print_pdf)
        format_button = QPushButton("Formats...")
        format_button.clicked.connect(self.open_format_settings)
        self.options_button = QPushButton("Options...")
        self.options_button.clicked.connect(self.open_layout_options)

        layout_settings = QGroupBox("Mise en page")
        settings = QGridLayout(layout_settings)
        settings.addWidget(QLabel("Mode"), 0, 0)
        settings.addWidget(self.mode, 0, 1)
        settings.setColumnMinimumWidth(2, 12)
        settings.addWidget(self.preset_info, 0, 3)
        settings.addWidget(format_button, 0, 4)
        settings.addWidget(self.options_button, 0, 5)
        settings.setColumnStretch(6, 1)

        envelope_settings = QHBoxLayout()
        envelope_settings.addWidget(QLabel("Format"))
        envelope_settings.addWidget(self.envelope_format)
        envelope_edit_button = QPushButton("Ajuster visuellement...")
        envelope_edit_button.clicked.connect(self.open_envelope_editor)
        envelope_settings.addWidget(envelope_edit_button)
        envelope_settings.addStretch()
        self.envelope_panel = QWidget()
        self.envelope_panel.setLayout(envelope_settings)
        self.envelope_group = QGroupBox("Réglages enveloppe")
        envelope_layout = QVBoxLayout(self.envelope_group)
        envelope_layout.addWidget(self.envelope_panel)

        printer_group = QGroupBox("Sortie")
        printer_settings = QHBoxLayout(printer_group)
        printer_settings.addWidget(QLabel("Imprimante"))
        printer_settings.addWidget(self.printers)

        buttons = QHBoxLayout()
        preview_button = QPushButton("Aperçu")
        preview_button.clicked.connect(self.preview_pdf)
        buttons.addWidget(preview_button)
        buttons.addWidget(export_button)
        buttons.addWidget(print_button)
        printer_settings.addStretch()
        printer_settings.addLayout(buttons)

        layout = QVBoxLayout()
        files_header = QHBoxLayout()
        files_header.addWidget(QLabel("Fichiers CSV disponibles"))
        self.directory_info = QLabel(str(self.directory))
        self.directory_info.setToolTip(str(self.directory))
        self.directory_info.setStyleSheet("QLabel { color: #5c6873; }")
        files_header.addWidget(self.directory_info, 1)
        directory_button = QPushButton("Choisir le dossier...")
        directory_button.clicked.connect(self.choose_directory)
        files_header.addWidget(directory_button)
        files_header.addStretch()
        selection_header = QHBoxLayout()
        selection_header.addWidget(self.select_all_checkbox)
        selection_header.addStretch()
        layout.addLayout(files_header)
        layout.addLayout(selection_header)
        layout.addWidget(self.file_list)
        layout.addWidget(self.summary)
        layout.addWidget(layout_settings)
        layout.addWidget(self.envelope_group)
        layout.addWidget(printer_group)
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

    @staticmethod
    def _spin_box(value: int, minimum: int, maximum: int, step: int = 1) -> QSpinBox:
        control = QSpinBox()
        control.setRange(minimum, maximum)
        control.setValue(value)
        control.setSingleStep(step)
        return control

    def load_directory_files(self) -> None:
        for path in find_csv_files(self.directory):
            self.add_file(path)
        self.update_summary()

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
            warning = " [!]" if document.issues else ""
            label = f"{path.name} ({len(document.recipients)} étiquettes){warning}"
        except ValueError as error:
            label = f"{path.name} (erreur : {error})"
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, str(path))
        if document is not None and document.issues:
            item.setToolTip("\n".join(document.issues))
        item.setCheckState(Qt.CheckState.Unchecked)
        self.file_list.addItem(item)
        self.files[str(path)] = path

    def choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Sélectionner des CSV", str(self.directory), "CSV (*.csv)")
        for path in paths:
            self.add_file(Path(path))

    def load_printers(self) -> None:
        try:
            result = subprocess.run(["lpstat", "-a"], capture_output=True, text=True, check=False)
        except OSError:
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
            if item.checkState() == Qt.CheckState.Checked:
                documents.append(load_csv(Path(item.data(Qt.ItemDataRole.UserRole))))
        return documents

    def update_summary(self) -> None:
        documents = []
        selected_count = 0
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            selected_count += 1
            try:
                documents.append(load_csv(Path(item.data(Qt.ItemDataRole.UserRole))))
            except ValueError:
                continue
        total_count = self.file_list.count()
        if total_count and selected_count == total_count:
            checkbox_state = Qt.CheckState.Checked
        elif selected_count:
            checkbox_state = Qt.CheckState.PartiallyChecked
        else:
            checkbox_state = Qt.CheckState.Unchecked
        self.select_all_checkbox.blockSignals(True)
        self.select_all_checkbox.setCheckState(checkbox_state)
        self.select_all_checkbox.blockSignals(False)
        file_count = len(documents)
        label_count = sum(len(document.recipients) for document in documents)
        issue_count = sum(len(document.issues) for document in documents)
        if self.mode.currentIndex() == 1:
            page_count = label_count
        else:
            capacity = self.columns.value() * self.rows.value()
            first_capacity = capacity - ((self.start_row.value() - 1) * self.columns.value() + self.start_column.value() - 1)
            page_count = 0 if not label_count else 1 + max(0, math.ceil((label_count - first_capacity) / capacity))
        message = f"{file_count} fichier(s), {label_count} étiquette(s), {page_count} page(s)"
        if issue_count:
            message += f" - [!] {issue_count} avertissement(s)"
        self.summary.setText(message)

    def set_all_files(self, selected: bool) -> None:
        state = Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked
        for index in range(self.file_list.count()):
            self.file_list.item(index).setCheckState(state)
        self.update_summary()

    def select_all_changed(self, state: int) -> None:
        check_state = Qt.CheckState(state)
        if check_state == Qt.CheckState.PartiallyChecked:
            return
        self.set_all_files(check_state == Qt.CheckState.Checked)

    def update_mode_controls(self) -> None:
        is_envelope = self.mode.currentIndex() == 1
        self.envelope_group.setVisible(is_envelope)
        self.options_button.setEnabled(not is_envelope)
        self.start_column.setEnabled(not is_envelope)
        self.start_row.setEnabled(not is_envelope)

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
        self.envelope_page_width, self.envelope_page_height = self.envelope_format.currentData()

    def save_envelope_layout(self, layout_data: EnvelopeLayout) -> None:
        self.settings.setValue("envelope_layout", json.dumps(asdict(layout_data)))

    def restore_envelope_layout(self) -> None:
        saved_layout = self.settings.value("envelope_layout", "")
        if not saved_layout:
            return
        try:
            layout_data = EnvelopeLayout(**json.loads(saved_layout))
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
        self.envelope_recipient_font_family = layout_data.recipient_font_family
        self.envelope_recipient_font_size = layout_data.recipient_font_size
        self.envelope_recipient_bold = layout_data.recipient_bold
        self.envelope_recipient_italic = layout_data.recipient_italic
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
        )

    def open_envelope_editor(self) -> None:
        self.envelope_x.setMaximum(500)
        self.envelope_y.setMaximum(300)
        self.envelope_width.setMaximum(500)
        self.envelope_height.setMaximum(300)
        dialog = EnvelopeEditorDialog(self.envelope_layout(), self._sample_sender(),
                                      self._sample_recipient(), self)
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
        self.envelope_recipient_font_family = edited.recipient_font_family
        self.envelope_recipient_font_size = edited.recipient_font_size
        self.envelope_recipient_bold = edited.recipient_bold
        self.envelope_recipient_italic = edited.recipient_italic
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
                return "\n".join(value for value in (
                    recipient.name, recipient.address,
                    f"{recipient.postal_code} {recipient.city}") if value)
        return "Destinataire"

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
        self.sender_height_percent = values.get("sender_height_percent", 34)
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
        self.recipient_font_family = values.get("recipient_font_family", "DejaVu Sans")
        self.recipient_font_size = values.get("recipient_font_size", 15)
        self.recipient_bold = values.get("recipient_bold", True)
        self.recipient_italic = values.get("recipient_italic", False)
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
        self.sender_height_percent = selected.sender_height_percent
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
        self.recipient_font_family = selected.recipient_font_family
        self.recipient_font_size = selected.recipient_font_size
        self.recipient_bold = selected.recipient_bold
        self.recipient_italic = selected.recipient_italic
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
            self.sender_height_percent, self.sender_base_size, self.sender_min_size,
            self.sender_offset_x, self.sender_offset_y,
            self.recipient_offset_x, self.recipient_offset_y,
            self.sender_width, self.recipient_width, self.recipient_height,
            self.sender_font_family, self.sender_font_size, self.sender_bold,
            self.sender_italic, self.recipient_font_family, self.recipient_font_size,
            self.recipient_bold, self.recipient_italic,
            self.sender_enabled,
        )
        dialog = FormatSettingsDialog(
            current, self.directory / "formats.json", sample_sender,
            sample_recipient, self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dialog.format_result()
        self.available_formats = load_formats(self.format_storage_path)
        self.apply_format_values(selected)
        self.preset_info.setText(f"Format actif : {selected.name}")

    def create_pdf(self, show_guides: bool | None = None) -> tuple[Path, RenderStats]:
        documents = self.selected_documents()
        if not documents:
            raise ValueError("Sélectionnez au moins un fichier CSV")
        if show_guides is None:
            show_guides = self.show_guides.isChecked()
        file_descriptor, output_name = tempfile.mkstemp(prefix="etiquettes-", suffix=".pdf")
        Path(output_name).unlink(missing_ok=True)
        os.close(file_descriptor)
        output = Path(output_name)
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
                self.envelope_recipient_italic
            )
        else:
            stats = render_pdf(documents, output, self.columns.value(), self.rows.value(),
                               self.margin_left.value(), self.margin_top.value(),
                               self.gap_x.value(), self.gap_y.value(),
                               self.start_column.value(), self.start_row.value(),
                               self.page_width, self.page_height,
                               show_guides, self.sender_height_percent,
                               self.sender_base_size, self.sender_min_size,
                               self.sender_offset_x, self.sender_offset_y,
                               self.recipient_offset_x, self.recipient_offset_y,
                               self.sender_width, self.recipient_width, self.recipient_height,
                               self.sender_font_family, self.sender_font_size,
                               self.sender_bold, self.sender_italic,
                               self.recipient_font_family, self.recipient_font_size,
                               self.recipient_bold, self.recipient_italic,
                               6, self.sender_enabled)
        return output, stats

    @staticmethod
    def render_summary(stats: RenderStats, verb: str) -> str:
        message = f"{stats.labels} étiquette(s) {verb}."
        if stats.reduced:
            message += f"\n{stats.reduced} étiquette(s) ont été réduite(s) pour tenir."
        if stats.overflow:
            message += f"\nAttention : {stats.overflow} étiquette(s) restent trop longues."
        return message

    def export_pdf(self) -> None:
        try:
            temporary_pdf, stats = self.create_pdf(show_guides=False)
            output, _ = QFileDialog.getSaveFileName(self, "Exporter le PDF", str(self.directory / "etiquettes.pdf"), "PDF (*.pdf)")
            if output:
                Path(output).write_bytes(temporary_pdf.read_bytes())
            temporary_pdf.unlink(missing_ok=True)
            if output:
                QMessageBox.information(self, "PDF créé", self.render_summary(stats, "exportée(s)"))
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Impossible de générer le PDF", str(error))

    def preview_pdf(self) -> None:
        try:
            pdf_path, stats = self.create_pdf(show_guides=True)
            dialog = PdfPreviewDialog(
                pdf_path, self.render_summary(stats, "préparée(s)"),
                lambda show_guides: self.create_pdf(show_guides), self
            )
            dialog.exec()
            pdf_path.unlink(missing_ok=True)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Aperçu impossible", str(error))


    def print_pdf(self) -> None:
        try:
            pdf_path, stats = self.create_pdf(show_guides=False)
            printer_name = self.printers.currentData()
            command = ["lp"]
            if printer_name:
                command.extend(["-d", printer_name])
            command.append(str(pdf_path))
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            pdf_path.unlink(missing_ok=True)
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or "CUPS a refusé le document")
            QMessageBox.information(self, "Impression envoyée", self.render_summary(stats, "envoyée(s)"))
        except (OSError, ValueError, RuntimeError) as error:
            QMessageBox.warning(self, "Impression impossible", str(error))


class PdfPreviewDialog(QDialog):
    def __init__(self, pdf_path: Path, summary: str = "", regenerate=None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Aperçu des étiquettes")
        self.resize(850, 700)
        self.pdf_path = pdf_path
        self.summary_text = summary
        self.regenerate = regenerate
        self.document = QPdfDocument(self)
        self.document.load(str(pdf_path))

        view = QPdfView()
        self.view = view
        view.setDocument(self.document)
        view.setPageMode(QPdfView.PageMode.MultiPage)
        view.setZoomMode(QPdfView.ZoomMode.FitToWidth)

        zoom_out_button = QPushButton("−")
        zoom_out_button.setToolTip("Réduire le zoom")
        zoom_out_button.clicked.connect(self.zoom_out)
        zoom_in_button = QPushButton("+")
        zoom_in_button.setToolTip("Augmenter le zoom")
        zoom_in_button.clicked.connect(self.zoom_in)
        fit_button = QPushButton("Largeur")
        fit_button.setToolTip("Adapter à la largeur de la fenêtre")
        fit_button.clicked.connect(self.fit_width)
        self.guides_checkbox = QCheckBox("Contours des étiquettes")
        self.guides_checkbox.setChecked(True)
        self.guides_checkbox.stateChanged.connect(self.toggle_guides)
        toolbar = QHBoxLayout()
        toolbar.addWidget(zoom_out_button)
        toolbar.addWidget(zoom_in_button)
        toolbar.addWidget(fit_button)
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
        layout.addWidget(close_button)

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
                self.summary_label.setText(
                    f"{stats.labels} étiquette(s) préparée(s)."
                    + (f" {stats.reduced} réduite(s)." if stats.reduced else "")
                )
        except (OSError, ValueError):
            self.guides_checkbox.blockSignals(True)
            self.guides_checkbox.setChecked(not show_guides)
            self.guides_checkbox.blockSignals(False)

    def zoom_in(self) -> None:
        self.view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.view.setZoomFactor(min(self.view.zoomFactor() * 1.2, 5.0))

    def zoom_out(self) -> None:
        self.view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.view.setZoomFactor(max(self.view.zoomFactor() / 1.2, 0.2))

    def fit_width(self) -> None:
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)

    def closeEvent(self, event) -> None:
        self.pdf_path.unlink(missing_ok=True)
        super().closeEvent(event)


def main() -> int:
    directory = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "csv"
    application = QApplication(sys.argv)
    window = LabelWindow(directory)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())