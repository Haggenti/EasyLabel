#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
import tempfile
import os
import math
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from PySide6.QtCore import QMarginsF, QSettings, QRectF, QSizeF, Qt
from PySide6.QtGui import QAction, QActionGroup, QFont, QFontMetricsF, QMouseEvent, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen
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
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
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
        self.pages = 0
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
    sender_alignment: str = "center"
    recipient_alignment: str = "center"
    postal_code_enabled: bool = False
    postal_code_x: float = 20
    postal_code_y: float = 78
    postal_code_width: float = 60
    postal_code_height: float = 16


def alignment_flag(value: str, vertical: Qt.AlignmentFlag) -> Qt.AlignmentFlag:
    horizontal = {
        "left": Qt.AlignmentFlag.AlignLeft,
        "right": Qt.AlignmentFlag.AlignRight,
    }.get(value, Qt.AlignmentFlag.AlignHCenter)
    return horizontal | vertical


def format_recipient_text(recipient, include_postal: bool = True) -> str:
    values = [recipient.name, recipient.address]
    if include_postal:
        values.append(f"{recipient.postal_code} {recipient.city}")
    else:
        values.append(recipient.city)
    return "\n".join(value for value in values if value)


def remove_postal_code_from_text(text: str, postal_code: str) -> str:
    digits = "".join(character for character in postal_code if character.isdigit())
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


class EnvelopeCanvas(QWidget):
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
        self.setMinimumSize(700, 400)

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

    def draw_postal_code(self, painter: QPainter, rect: QRectF) -> None:
        postal_code = "".join(character for character in self.postal_code_text if character.isdigit())
        if not postal_code:
            return
        cell_width = rect.width() / len(postal_code)
        for index, character in enumerate(postal_code):
            cell = QRectF(rect.left() + index * cell_width, rect.top(), cell_width, rect.height())
            painter.drawText(
                cell.adjusted(2, 2, -2, -2),
                Qt.AlignmentFlag.AlignCenter,
                character,
            )

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale, page = self.scale_and_page()
        painter.fillRect(page, Qt.GlobalColor.white)
        painter.setPen(QPen(Qt.GlobalColor.darkGray, 1))
        painter.drawRect(page)
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
            painter.setBrush(color)
            painter.drawRect(self.handle_rect(element))
            font = QFont(getattr(self.layout_data, f"{element}_font_family"),
                         int(getattr(self.layout_data, f"{element}_font_size")))
            font.setBold(getattr(self.layout_data, f"{element}_bold"))
            font.setItalic(getattr(self.layout_data, f"{element}_italic"))
            painter.setFont(font)
            painter.drawText(
                rect.adjusted(3, 3, -3, -3),
                alignment_flag(
                    getattr(self.layout_data, f"{element}_alignment"),
                    Qt.AlignmentFlag.AlignVCenter,
                ) | Qt.TextFlag.TextWordWrap,
                text,
            )
        if self.layout_data.postal_code_enabled:
            rect = self.rect_for("postal_code")
            painter.setPen(QPen(Qt.GlobalColor.darkRed, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            painter.setBrush(Qt.GlobalColor.darkRed)
            painter.drawRect(self.handle_rect("postal_code"))
            painter.setPen(Qt.GlobalColor.darkRed)
            self.draw_postal_code(painter, rect)
        del scale

    def mousePressEvent(self, event) -> None:
        elements = ("postal_code", "recipient", "sender")
        for element in elements:
            if element == "postal_code" and not self.layout_data.postal_code_enabled:
                continue
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


def draw_postal_code(painter: QPainter, rect: QRectF, postal_code: str,
                     font: QFont, draw_guides: bool = False) -> None:
    digits = "".join(character for character in postal_code if character.isdigit())
    if not digits:
        return
    cell_width = rect.width() / len(digits)
    painter.setFont(font)
    for index, digit in enumerate(digits):
        cell = QRectF(rect.left() + index * cell_width, rect.top(), cell_width, rect.height())
        if draw_guides:
            painter.save()
            painter.setPen(QPen(Qt.GlobalColor.gray, 0.5, Qt.PenStyle.DashLine))
            painter.drawRect(cell)
            painter.restore()
        painter.drawText(cell, Qt.AlignmentFlag.AlignCenter, digit)


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
               recipient_min_size: float = 6, sender_enabled: bool = True,
               sender_alignment: str = "center", recipient_alignment: str = "center") -> RenderStats:
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
            if stats.labels == 0:
                stats.pages = 1
            if slot == columns * rows:
                writer.newPage()
                stats.pages += 1
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
                sender_flags = (alignment_flag(sender_alignment, Qt.AlignmentFlag.AlignTop)
                                | Qt.TextFlag.TextWordWrap)
                sender_bounds = QFontMetricsF(sender_font).boundingRect(
                    sender_rect, int(sender_flags), sender_text
                )
                if sender_bounds.width() > sender_rect.width() or sender_bounds.height() > sender_rect.height():
                    stats.overflow += 1
                painter.setFont(sender_font)
                painter.drawText(sender_rect, sender_flags, sender_text)

            recipient_text = format_recipient_text(recipient)
            recipient_font, was_reduced = fit_font(
                recipient_text, recipient_rect, int(recipient_font_size), int(recipient_min_size),
                recipient_font_family, recipient_bold, recipient_italic
            )
            if was_reduced:
                stats.reduced += 1
            text_flags = (alignment_flag(recipient_alignment, Qt.AlignmentFlag.AlignVCenter)
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
                        recipient_bold: bool = True, recipient_italic: bool = False,
                        sender_alignment: str = "center", recipient_alignment: str = "center",
                        postal_code_enabled: bool = False, postal_code_x: float = 20,
                        postal_code_y: float = 78, postal_code_width: float = 60,
                        postal_code_height: float = 16) -> RenderStats:
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
                sender_font, sender_was_reduced = fit_font(
                    sender_text, sender_rect, int(sender_font_size), 4,
                    sender_font_family, sender_bold, sender_italic
                )
                if sender_was_reduced:
                    stats.reduced += 1
                painter.setFont(sender_font)
                painter.drawText(sender_rect,
                                 alignment_flag(sender_alignment, Qt.AlignmentFlag.AlignTop)
                                 | Qt.TextFlag.TextWordWrap, sender_text)

            recipient_rect = QRectF(mm(recipient_x), mm(recipient_y),
                                    mm(recipient_width), mm(recipient_height))
            if show_guides:
                painter.save()
                painter.setPen(QPen(Qt.GlobalColor.gray, 0.5, Qt.PenStyle.DashLine))
                painter.drawRect(QRectF(0, 0, mm(width_mm), mm(height_mm)))
                painter.drawRect(recipient_rect)
                painter.restore()
            recipient_text = format_recipient_text(recipient, not postal_code_enabled)
            recipient_font, was_reduced = fit_font(
                recipient_text, recipient_rect, int(recipient_font_size), 4,
                recipient_font_family, recipient_bold, recipient_italic
            )
            if was_reduced:
                stats.reduced += 1
            text_flags = (alignment_flag(recipient_alignment, Qt.AlignmentFlag.AlignVCenter)
                          | Qt.TextFlag.TextWordWrap)
            bounds = QFontMetricsF(recipient_font).boundingRect(
                recipient_rect, int(text_flags), recipient_text
            )
            if bounds.width() > recipient_rect.width() or bounds.height() > recipient_rect.height():
                stats.overflow += 1
            painter.setFont(recipient_font)
            painter.drawText(recipient_rect, text_flags, recipient_text)
            if postal_code_enabled:
                postal_rect = QRectF(mm(postal_code_x), mm(postal_code_y),
                                     mm(postal_code_width), mm(postal_code_height))
                postal_font = QFont(recipient_font)
                postal_code = recipient.postal_code
                draw_postal_code(painter, postal_rect, postal_code, postal_font, show_guides)
            stats.labels += 1

    painter.end()
    return stats


class EnvelopeEditorDialog(QDialog):
    def __init__(self, layout_data: EnvelopeLayout, sender_text: str = "Expéditeur",
                 recipient_text: str = "Destinataire", parent: QWidget | None = None,
                 postal_code_text: str = "00000"):
        super().__init__(parent)
        self.setWindowTitle("Ajuster l’enveloppe")
        self.resize(820, 620)
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
        self.sender_alignment = self._alignment(layout_data.sender_alignment)
        self.recipient_font = QFontComboBox()
        self.recipient_font.setCurrentFont(QFont(layout_data.recipient_font_family))
        self.recipient_size = self.number(layout_data.recipient_font_size, 4, 40)
        self.recipient_bold = QCheckBox("Gras")
        self.recipient_bold.setChecked(layout_data.recipient_bold)
        self.recipient_italic = QCheckBox("Italique")
        self.recipient_italic.setChecked(layout_data.recipient_italic)
        self.recipient_alignment = self._alignment(layout_data.recipient_alignment)
        self.postal_code_enabled = QCheckBox("Afficher le code postal dans des cases")
        self.postal_code_enabled.setChecked(layout_data.postal_code_enabled)
        for control in (self.sender_enabled, self.sender_font, self.sender_size, self.sender_bold,
                self.sender_italic, self.sender_alignment, self.recipient_font,
                self.recipient_size, self.recipient_bold, self.recipient_italic,
            self.recipient_alignment, self.postal_code_enabled):
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
        sender_style.addWidget(self.sender_alignment)
        settings.addLayout(sender_style, 1, 2, 1, 2)
        settings.addWidget(self.sender_enabled, 2, 0, 1, 4)
        settings.addWidget(QLabel("Police destinataire"), 3, 0)
        settings.addWidget(self.recipient_font, 3, 1)
        recipient_style = QHBoxLayout()
        recipient_style.addWidget(self.recipient_size)
        recipient_style.addWidget(self.recipient_bold)
        recipient_style.addWidget(self.recipient_italic)
        recipient_style.addWidget(self.recipient_alignment)
        settings.addLayout(recipient_style, 3, 2, 1, 2)
        settings.addWidget(self.postal_code_enabled, 4, 0, 1, 4)
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

    @staticmethod
    def _alignment(value: str) -> QComboBox:
        control = QComboBox()
        for label, data in (("Gauche", "left"), ("Centré", "center"), ("Droite", "right")):
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
        self.layout_data.recipient_font_family = self.recipient_font.currentFont().family()
        self.layout_data.recipient_font_size = self.recipient_size.value()
        self.layout_data.recipient_bold = self.recipient_bold.isChecked()
        self.layout_data.recipient_italic = self.recipient_italic.isChecked()
        self.layout_data.recipient_alignment = self.recipient_alignment.currentData()
        self.layout_data.postal_code_enabled = self.postal_code_enabled.isChecked()
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
        self.layout_data.sender_alignment = defaults.sender_alignment
        self.layout_data.recipient_font_family = defaults.recipient_font_family
        self.layout_data.recipient_font_size = defaults.recipient_font_size
        self.layout_data.recipient_bold = defaults.recipient_bold
        self.layout_data.recipient_italic = defaults.recipient_italic
        self.layout_data.recipient_alignment = defaults.recipient_alignment
        self.layout_data.postal_code_enabled = defaults.postal_code_enabled
        self.sender_enabled.setChecked(defaults.sender_enabled)
        self.sender_font.setCurrentFont(QFont(defaults.sender_font_family))
        self.sender_size.setValue(defaults.sender_font_size)
        self.sender_bold.setChecked(defaults.sender_bold)
        self.sender_italic.setChecked(defaults.sender_italic)
        self.sender_alignment.setCurrentIndex(self.sender_alignment.findData(defaults.sender_alignment))
        self.recipient_font.setCurrentFont(QFont(defaults.recipient_font_family))
        self.recipient_size.setValue(defaults.recipient_font_size)
        self.recipient_bold.setChecked(defaults.recipient_bold)
        self.recipient_italic.setChecked(defaults.recipient_italic)
        self.recipient_alignment.setCurrentIndex(self.recipient_alignment.findData(defaults.recipient_alignment))
        self.postal_code_enabled.setChecked(defaults.postal_code_enabled)
        self.canvas.update()


class EnvelopeFormatDialog(QDialog):
    def __init__(self, formats: dict[str, dict], active_name: str,
                 sender_text: str = "Expéditeur", recipient_text: str = "Destinataire",
                 parent: QWidget | None = None, postal_code_text: str = "00000"):
        super().__init__(parent)
        self.setWindowTitle("Formats d'enveloppes")
        self.resize(560, 420)
        self.formats = json.loads(json.dumps(formats))
        self.sender_text = sender_text
        self.recipient_text = recipient_text
        self.postal_code_text = postal_code_text
        self.active_name = active_name
        self.current_layout = EnvelopeLayout()

        self.preset_list = QListWidget()
        self.preset_list.currentItemChanged.connect(self.select_format)
        self.name = QLineEdit()
        edit_button = QPushButton("Modifier la mise en page...")
        edit_button.clicked.connect(self.edit_format)
        save_button = QPushButton("Enregistrer le format")
        save_button.clicked.connect(self.save_format)
        delete_button = QPushButton("Supprimer")
        delete_button.clicked.connect(self.delete_format)
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
        buttons.addWidget(delete_button)
        buttons.addStretch()
        buttons.addWidget(cancel_button)
        buttons.addWidget(use_button)
        form.addLayout(buttons)
        left = QVBoxLayout()
        left.addWidget(QLabel("Formats disponibles"))
        left.addWidget(self.preset_list)
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
        self.active_name = item.text()
        self.name.setText(self.active_name)
        self.current_layout = EnvelopeLayout(**self.formats[self.active_name])

    def edit_format(self) -> None:
        edited_layout = EnvelopeLayout(**asdict(self.current_layout))
        dialog = EnvelopeEditorDialog(
            edited_layout, self.sender_text, self.recipient_text, self,
            self.postal_code_text
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.current_layout = dialog.layout_data

    def save_format(self) -> None:
        name = self.name.text().strip()
        if not name:
            return
        self.formats[name] = asdict(self.current_layout)
        self.active_name = name
        self.refresh_list(name)

    def delete_format(self) -> None:
        if len(self.formats) <= 1 or self.active_name not in self.formats:
            return
        del self.formats[self.active_name]
        self.active_name = next(iter(self.formats))
        self.refresh_list(self.active_name)

    def format_result(self) -> tuple[str, EnvelopeLayout, dict[str, dict]]:
        self.save_format()
        return self.active_name, self.current_layout, self.formats


class PrintOptionsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Options d'impression")
        self.copies = QSpinBox()
        self.copies.setRange(1, 99)
        self.page_range = QLineEdit()
        self.page_range.setPlaceholderText("Toutes les pages")
        self.test_page = QCheckBox("Imprimer une page de test avec les contours")
        self.test_page.toggled.connect(self.update_test_page)

        grid = QGridLayout()
        grid.addWidget(QLabel("Nombre de copies"), 0, 0)
        grid.addWidget(self.copies, 0, 1)
        grid.addWidget(QLabel("Pages à imprimer"), 1, 0)
        grid.addWidget(self.page_range, 1, 1)
        grid.addWidget(self.test_page, 2, 0, 1, 2)
        cancel_button = QPushButton("Annuler")
        cancel_button.clicked.connect(self.reject)
        print_button = QPushButton("Imprimer")
        print_button.clicked.connect(self.validate_and_accept)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel_button)
        buttons.addWidget(print_button)
        layout = QVBoxLayout(self)
        layout.addLayout(grid)
        layout.addLayout(buttons)

    def update_test_page(self, checked: bool) -> None:
        self.page_range.setEnabled(not checked)
        if checked:
            self.page_range.clear()

    def validate_and_accept(self) -> None:
        if self.test_page.isChecked() or self.parse_page_range(self.page_range.text()) is not None:
            self.accept()
            return
        QMessageBox.warning(
            self, "Plage de pages invalide",
            "Utilisez par exemple : 1, 2-4 ou 1,3,5."
        )

    @staticmethod
    def parse_page_range(value: str) -> list[int] | None:
        value = value.strip()
        if not value:
            return []
        pages: set[int] = set()
        for part in value.split(","):
            part = part.strip()
            if re.fullmatch(r"[1-9][0-9]*", part):
                pages.add(int(part))
                continue
            match = re.fullmatch(r"([1-9][0-9]*)\s*-\s*([1-9][0-9]*)", part)
            if not match:
                return None
            start, end = (int(group) for group in match.groups())
            if start > end:
                return None
            pages.update(range(start, end + 1))
        return sorted(pages)


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
        self.sender_alignment = "center"
        self.recipient_font_family = "DejaVu Sans"
        self.recipient_font_size = 15.0
        self.recipient_bold = True
        self.recipient_italic = False
        self.recipient_alignment = "center"
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
        self.envelope_recipient_font_family = "DejaVu Sans"
        self.envelope_recipient_font_size = 14.0
        self.envelope_recipient_bold = True
        self.envelope_recipient_italic = False
        self.envelope_recipient_alignment = "center"
        self.envelope_postal_code_enabled = False
        self.envelope_postal_code_x = 20.0
        self.envelope_postal_code_y = 78.0
        self.envelope_postal_code_width = 60.0
        self.envelope_postal_code_height = 16.0
        self.printers = QComboBox()
        self.load_printers()

        self.select_all_checkbox = QCheckBox("Sélectionner tous les fichiers")
        self.select_all_checkbox.setTristate(True)
        self.select_all_checkbox.stateChanged.connect(self.select_all_changed)
        self.file_filter = QLineEdit()
        self.file_filter.setPlaceholderText("Filtrer les fichiers...")
        self.file_filter.setClearButtonEnabled(True)
        self.file_filter.textChanged.connect(self.filter_files)
        export_button = QPushButton("Exporter le PDF")
        export_button.clicked.connect(self.export_pdf)
        print_button = QPushButton("Imprimer")
        print_button.clicked.connect(self.print_pdf)

        file_menu = self.menuBar().addMenu("Fichier")
        choose_directory_action = file_menu.addAction("Choisir le dossier CSV...")
        choose_directory_action.triggered.connect(self.choose_directory)
        self.directory_action = file_menu.addAction(str(self.directory))
        self.directory_action.setEnabled(False)

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

        layout_menu = self.menuBar().addMenu("Mise en page")
        self.format_action = layout_menu.addAction("Formats...")
        self.format_action.triggered.connect(self.open_format_settings)
        self.options_action = layout_menu.addAction("Options...")
        self.options_action.triggered.connect(self.open_layout_options)
        self.envelope_layout_separator = layout_menu.addSeparator()
        self.envelope_format_menu = layout_menu.addMenu("Format enveloppe")
        self.envelope_format_actions = []
        for index in range(self.envelope_format.count()):
            action = self.envelope_format_menu.addAction(self.envelope_format.itemText(index))
            action.setCheckable(True)
            action.triggered.connect(lambda checked=False, selected=index: self.envelope_format.setCurrentIndex(selected))
            self.envelope_format_actions.append(action)
        self.envelope_formats_action = layout_menu.addAction("Gérer les formats...")
        self.envelope_formats_action.triggered.connect(self.open_envelope_formats)

        printer_menu = self.menuBar().addMenu("Imprimante")
        self.printer_actions = []
        printer_group = QActionGroup(self)
        for index in range(self.printers.count()):
            action = printer_menu.addAction(self.printers.itemText(index))
            action.setCheckable(True)
            action.triggered.connect(lambda checked=False, selected=index: self.printers.setCurrentIndex(selected))
            printer_group.addAction(action)
            self.printer_actions.append(action)
        self.printers.currentIndexChanged.connect(self.update_printer_menu)

        printer_settings = QHBoxLayout()
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
        self.update_printer_menu()
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
        self.directory_action.setText(str(directory))
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

    def filter_files(self, text: str) -> None:
        query = text.strip().casefold()
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            item.setHidden(bool(query) and query not in item.text().casefold())
        self.update_summary()

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

    def update_printer_menu(self) -> None:
        if not hasattr(self, "printer_actions"):
            return
        for index, action in enumerate(self.printer_actions):
            action.setChecked(index == self.printers.currentIndex())

    def selected_documents(self) -> list[CsvDocument]:
        documents = []
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                documents.append(load_csv(Path(item.data(Qt.ItemDataRole.UserRole))))
        return documents

    def update_summary(self) -> None:
        documents = []
        active_selected_count = 0
        active_count = 0
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            if not item.isHidden():
                active_count += 1
                if item.checkState() == Qt.CheckState.Checked:
                    active_selected_count += 1
            if item.checkState() != Qt.CheckState.Checked:
                continue
            try:
                documents.append(load_csv(Path(item.data(Qt.ItemDataRole.UserRole))))
            except ValueError:
                continue
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
            item = self.file_list.item(index)
            if not item.isHidden():
                item.setCheckState(state)
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
        self.format_action.setVisible(not is_envelope)
        self.options_action.setVisible(not is_envelope)
        self.envelope_layout_separator.setVisible(is_envelope)
        self.envelope_format_menu.menuAction().setVisible(is_envelope)
        self.envelope_formats_action.setVisible(is_envelope)
        for index, action in enumerate(self.envelope_format_actions):
            action.setChecked(index == self.envelope_format.currentIndex())
        self.update_active_format_display()
        self.start_column.setEnabled(not is_envelope)
        self.start_row.setEnabled(not is_envelope)

    def update_active_format_display(self) -> None:
        if self.mode.currentIndex() == 1:
            text = f"Format enveloppe actif : {self.envelope_format.currentText()}"
        else:
            text = f"Format actif : {self.format_name}"
        self.preset_info.setText(text)

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
        for index, action in enumerate(self.envelope_format_actions):
            action.setChecked(index == self.envelope_format.currentIndex())
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
        self.envelope_recipient_font_family = layout_data.recipient_font_family
        self.envelope_recipient_font_size = layout_data.recipient_font_size
        self.envelope_recipient_bold = layout_data.recipient_bold
        self.envelope_recipient_italic = layout_data.recipient_italic
        self.envelope_recipient_alignment = layout_data.recipient_alignment
        self.envelope_postal_code_enabled = layout_data.postal_code_enabled
        self.envelope_postal_code_x = layout_data.postal_code_x
        self.envelope_postal_code_y = layout_data.postal_code_y
        self.envelope_postal_code_width = layout_data.postal_code_width
        self.envelope_postal_code_height = layout_data.postal_code_height
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
        self.envelope_format_menu.clear()
        self.envelope_format_actions = []
        for index in range(self.envelope_format.count()):
            action = self.envelope_format_menu.addAction(self.envelope_format.itemText(index))
            action.setCheckable(True)
            action.triggered.connect(
                lambda checked=False, selected=index: self.envelope_format.setCurrentIndex(selected)
            )
            self.envelope_format_actions.append(action)
        self.apply_envelope_preset(active_name)

    def open_envelope_formats(self) -> None:
        dialog = EnvelopeFormatDialog(
            self.envelope_presets, self.envelope_preset_name,
            self._sample_sender(), self._sample_recipient(), self,
            self._sample_postal_code()
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, layout_data, formats = dialog.format_result()
        self.envelope_presets = formats
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
        self.envelope_recipient_font_family = layout_data.recipient_font_family
        self.envelope_recipient_font_size = layout_data.recipient_font_size
        self.envelope_recipient_bold = layout_data.recipient_bold
        self.envelope_recipient_italic = layout_data.recipient_italic
        self.envelope_recipient_alignment = layout_data.recipient_alignment
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
        )

    def open_envelope_editor(self) -> None:
        self.envelope_x.setMaximum(500)
        self.envelope_y.setMaximum(300)
        self.envelope_width.setMaximum(500)
        self.envelope_height.setMaximum(300)
        dialog = EnvelopeEditorDialog(
            self.envelope_layout(), self._sample_sender(), self._sample_recipient(), self,
            self._sample_postal_code()
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
        self.envelope_recipient_font_family = edited.recipient_font_family
        self.envelope_recipient_font_size = edited.recipient_font_size
        self.envelope_recipient_bold = edited.recipient_bold
        self.envelope_recipient_italic = edited.recipient_italic
        self.envelope_recipient_alignment = edited.recipient_alignment
        self.envelope_postal_code_enabled = edited.postal_code_enabled
        self.envelope_postal_code_x = edited.postal_code_x
        self.envelope_postal_code_y = edited.postal_code_y
        self.envelope_postal_code_width = edited.postal_code_width
        self.envelope_postal_code_height = edited.postal_code_height
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
        self.sender_alignment = values.get("sender_alignment", "center")
        self.recipient_font_family = values.get("recipient_font_family", "DejaVu Sans")
        self.recipient_font_size = values.get("recipient_font_size", 15)
        self.recipient_bold = values.get("recipient_bold", True)
        self.recipient_italic = values.get("recipient_italic", False)
        self.recipient_alignment = values.get("recipient_alignment", "center")
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
        self.sender_alignment = selected.sender_alignment
        self.recipient_font_family = selected.recipient_font_family
        self.recipient_font_size = selected.recipient_font_size
        self.recipient_bold = selected.recipient_bold
        self.recipient_italic = selected.recipient_italic
        self.recipient_alignment = selected.recipient_alignment
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
            self.sender_alignment, self.recipient_alignment,
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
                self.envelope_recipient_italic,
                self.envelope_sender_alignment, self.envelope_recipient_alignment,
                self.envelope_postal_code_enabled, self.envelope_postal_code_x,
                self.envelope_postal_code_y, self.envelope_postal_code_width,
                self.envelope_postal_code_height,
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
                               6, self.sender_enabled,
                               self.sender_alignment, self.recipient_alignment)
        return output, stats

    @staticmethod
    def render_summary(stats: RenderStats, verb: str) -> str:
        message = f"{stats.labels} étiquette(s) {verb}.\n{stats.pages} page(s) à imprimer."
        if stats.overflow:
            message += f"\nAttention : {stats.overflow} étiquette(s) trop longue(s)."
        return message

    def export_pdf(self) -> None:
        temporary_pdf = None
        try:
            temporary_pdf, stats = self.create_pdf(show_guides=False)
            output, _ = QFileDialog.getSaveFileName(self, "Exporter le PDF", str(self.directory / "etiquettes.pdf"), "PDF (*.pdf)")
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


    def print_pdf(self) -> None:
        options = PrintOptionsDialog(self)
        if options.exec() != QDialog.DialogCode.Accepted:
            return
        pdf_path = None
        try:
            test_page = options.test_page.isChecked()
            pdf_path, stats = self.create_pdf(show_guides=test_page)
            printer_name = self.printers.currentData()
            command = ["lp"]
            if printer_name:
                command.extend(["-d", printer_name])
            command.extend(["-n", str(options.copies.value())])
            page_range = "1" if test_page else options.page_range.text().strip()
            if page_range:
                command.extend(["-P", page_range])
            command.append(str(pdf_path))
            page_summary = "page de test (page 1)" if test_page else (page_range or "toutes les pages")
            printer_summary = self.printers.currentText()
            mode_summary = "enveloppes" if self.mode.currentIndex() == 1 else "étiquettes"
            confirmation = (
                f"Imprimante : {printer_summary}\n"
                f"Mode : {mode_summary}\n"
                f"Copies : {options.copies.value()}\n"
                f"Pages : {page_summary}\n\n"
                "Lancer l'impression ?"
            )
            if QMessageBox.question(
                self, "Confirmer l'impression", confirmation,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            ) != QMessageBox.StandardButton.Yes:
                return
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or "CUPS a refusé le document")
            verb = "de test envoyée(s)" if test_page else "envoyée(s)"
            QMessageBox.information(self, "Impression envoyée", self.render_summary(stats, verb))
        except (OSError, ValueError, RuntimeError) as error:
            QMessageBox.warning(self, "Impression impossible", str(error))
        finally:
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
                if stats.overflow:
                    summary += f"\nAttention : {stats.overflow} étiquette(s) trop longue(s)."
                self.summary_label.setText(summary)
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