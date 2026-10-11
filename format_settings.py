from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFontComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
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
    formats = dict(PRESETS)
    if storage_path.exists():
        try:
            formats.update(json.loads(storage_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    return formats


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


class FormatPreview(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.format = LabelFormat("Aperçu")
        self.setMinimumSize(300, 360)

    def set_format(self, label_format: LabelFormat) -> None:
        self.format = label_format
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        page = QRectF(24, 16, self.width() - 48, self.height() - 32)
        scale = min(page.width() / self.format.page_width,
                    page.height() / self.format.page_height)
        page.setWidth(self.format.page_width * scale)
        page.setHeight(self.format.page_height * scale)
        page.moveCenter(QRectF(self.rect()).center())
        painter.fillRect(page, Qt.GlobalColor.white)
        painter.setPen(QPen(Qt.GlobalColor.darkGray, 1))
        painter.drawRect(page)

        available_width = self.format.page_width - self.format.margin_left * 2
        available_height = self.format.page_height - self.format.margin_top * 2
        label_width = (available_width - self.format.gap_x * (self.format.columns - 1)) / self.format.columns
        label_height = (available_height - self.format.gap_y * (self.format.rows - 1)) / self.format.rows
        painter.setPen(QPen(Qt.GlobalColor.black, 1))
        for row in range(self.format.rows):
            for column in range(self.format.columns):
                x = self.format.margin_left + column * (label_width + self.format.gap_x)
                y = self.format.margin_top + row * (label_height + self.format.gap_y)
                painter.drawRect(QRectF(page.left() + x * scale, page.top() + y * scale,
                                        label_width * scale, label_height * scale))


class PositionCanvas(QWidget):
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
        self.setMinimumSize(560, 360)

    def set_format(self, label_format: LabelFormat) -> None:
        self.format = label_format
        self.update()

    def geometry_for(self, element: str) -> QRectF:
        scale = min((self.width() - 80) / 100, (self.height() - 80) / 60)
        origin = QRectF(40, 40, 100 * scale, 60 * scale)
        if element == "sender":
            sender_height = max(10, min(28, self.format.sender_height_percent * 0.5))
            return QRectF(origin.left() + (2 + self.format.sender_offset_x) * scale,
                          origin.top() + (6 + self.format.sender_offset_y) * scale,
                          self.format.sender_width * scale, sender_height * scale)
        return QRectF(origin.left() + (2 + self.format.recipient_offset_x) * scale,
                      origin.top() + (22 + self.format.recipient_offset_y) * scale,
                      self.format.recipient_width * scale,
                      self.format.recipient_height * 0.6 * scale)

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
        scale = min((self.width() - 80) / 100, (self.height() - 80) / 60)
        page = QRectF(40, 40, 100 * scale, 60 * scale)
        painter.fillRect(page, Qt.GlobalColor.white)
        painter.setPen(QPen(Qt.GlobalColor.darkGray, 1))
        painter.drawRect(page)
        painter.setPen(QPen(Qt.GlobalColor.lightGray, 1))
        for x in range(0, 101, 2):
            for y in range(0, 61, 2):
                painter.drawPoint(page.left() + x * scale, page.top() + y * scale)
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
            painter.drawText(rect.adjusted(3, 3, -3, -3),
                             Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, sample)

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
        scale = min((self.width() - 80) / 100, (self.height() - 80) / 60)
        delta = event.position() - self.drag_start
        base_x, base_y, element_width, element_height = self.base_geometry(self.active)
        if self.drag_mode == "resize":
            original_width, original_height = self.original_size
            new_width = self.snap_size(original_width + delta.x() / scale)
            new_height = self.snap_size(original_height + delta.y() / scale)
            new_width = max(30, min(100 - base_x, new_width))
            new_height = max(10, min(60 - base_y, new_height))
            if self.active == "sender":
                self.format.sender_width = new_width
                self.format.sender_height_percent = new_height * 2
            else:
                self.format.recipient_width = new_width
                self.format.recipient_height = new_height / 0.6
            self.clamp_offsets()
            self.update()
            return
        new_x = self.original_offset[0] + delta.x() / scale
        new_y = self.original_offset[1] + delta.y() / scale
        new_x = self.snap_size(new_x)
        new_y = self.snap_size(new_y)
        new_x = max(-base_x, min(new_x, 100 - base_x - element_width))
        new_y = max(-base_y, min(new_y, 60 - base_y - element_height))
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
        self.drag_start = None

    def clamp_offsets(self) -> None:
        for element in ("sender", "recipient"):
            base_x, base_y, element_width, element_height = self.base_geometry(element)
            offset_x = max(-base_x, min(getattr(self.format, f"{element}_offset_x"),
                                       100 - base_x - element_width))
            offset_y = max(-base_y, min(getattr(self.format, f"{element}_offset_y"),
                                       60 - base_y - element_height))
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
        self.recipient_font = QFontComboBox()
        self.recipient_font.setCurrentFont(QFont(label_format.recipient_font_family))
        self.recipient_size = self._number(label_format.recipient_font_size, 4, 40)
        self.recipient_bold = QCheckBox("Gras")
        self.recipient_bold.setChecked(label_format.recipient_bold)
        self.recipient_italic = QCheckBox("Italique")
        self.recipient_italic.setChecked(label_format.recipient_italic)
        for control in (self.sender_enabled, self.sender_height, self.sender_font, self.sender_size,
                        self.sender_bold, self.sender_italic, self.recipient_font,
                        self.recipient_size, self.recipient_bold, self.recipient_italic):
            if hasattr(control, "valueChanged"):
                control.valueChanged.connect(self.update_sender_settings)
            if hasattr(control, "currentFontChanged"):
                control.currentFontChanged.connect(self.update_sender_settings)
            if hasattr(control, "stateChanged"):
                control.stateChanged.connect(self.update_sender_settings)
        instructions = QLabel("Faites glisser les blocs Expéditeur et Destinataire dans l'étiquette.")
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
        settings.addRow("Style expéditeur", sender_style)
        settings.addRow("Police destinataire", self.recipient_font)
        recipient_style = QHBoxLayout()
        recipient_style.addWidget(self.recipient_size)
        recipient_style.addWidget(self.recipient_bold)
        recipient_style.addWidget(self.recipient_italic)
        settings.addRow("Style destinataire", recipient_style)
        layout.addLayout(settings)
        layout.addWidget(self.canvas)
        layout.addLayout(buttons)

    @staticmethod
    def _number(value: float, minimum: float, maximum: float) -> QDoubleSpinBox:
        control = QDoubleSpinBox()
        control.setRange(minimum, maximum)
        control.setValue(value)
        control.setDecimals(1)
        control.setSingleStep(1)
        return control

    def update_sender_settings(self) -> None:
        self.canvas.format.sender_enabled = self.sender_enabled.isChecked()
        self.canvas.format.sender_height_percent = self.sender_height.value()
        self.canvas.format.sender_font_family = self.sender_font.currentFont().family()
        self.canvas.format.sender_font_size = self.sender_size.value()
        self.canvas.format.sender_bold = self.sender_bold.isChecked()
        self.canvas.format.sender_italic = self.sender_italic.isChecked()
        self.canvas.format.recipient_font_family = self.recipient_font.currentFont().family()
        self.canvas.format.recipient_font_size = self.recipient_size.value()
        self.canvas.format.recipient_bold = self.recipient_bold.isChecked()
        self.canvas.format.recipient_italic = self.recipient_italic.isChecked()
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
        self.canvas.format.recipient_font_family = defaults.recipient_font_family
        self.canvas.format.recipient_font_size = defaults.recipient_font_size
        self.canvas.format.recipient_bold = defaults.recipient_bold
        self.canvas.format.recipient_italic = defaults.recipient_italic
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


class FormatSettingsDialog(QDialog):
    def __init__(self, current: LabelFormat, storage_path: Path,
                 sender_text: str = "Expéditeur", recipient_text: str = "Destinataire",
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Formats d'étiquettes")
        self.resize(820, 560)
        self.storage_path = storage_path
        self.sender_text = sender_text
        self.recipient_text = recipient_text
        self.formats = self.load_formats()
        self.current_format = current

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
        self.preview = FormatPreview()
        self.controls = (self.name, self.page_width, self.page_height, self.columns,
                         self.rows, self.margin_left, self.margin_top, self.gap_x, self.gap_y)
        for control in self.controls:
            if hasattr(control, "textChanged"):
                control.textChanged.connect(self.update_preview)
            else:
                control.valueChanged.connect(self.update_preview)

        form = QFormLayout()
        for label, control in (
            ("Nom", self.name), ("Largeur page (mm)", self.page_width),
            ("Hauteur page (mm)", self.page_height), ("Colonnes", self.columns),
            ("Lignes", self.rows), ("Marge gauche (mm)", self.margin_left),
            ("Marge haut (mm)", self.margin_top), ("Espace horizontal (mm)", self.gap_x),
            ("Espace vertical (mm)", self.gap_y),
        ):
            form.addRow(label, control)

        self.save_feedback = QLabel()
        self.save_feedback.setVisible(False)
        self.save_feedback.setStyleSheet(
            "QLabel { background: #e8f5e9; color: #216e39; border: 1px solid #9bd1a5; "
            "border-radius: 4px; padding: 7px 9px; }"
        )
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

        editor = QVBoxLayout()
        editor.addLayout(form)
        editor.addWidget(position_button)
        editor.addWidget(save_button)
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
        layout.addWidget(self.preview, 2)
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

    def load_formats(self) -> dict[str, dict]:
        return load_formats(self.storage_path)

    def select_format(self, item: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        del previous
        if item is None:
            return
        values = self.formats[item.text()]
        self.name.setText(item.text())
        defaults = asdict(LabelFormat(item.text()))
        for field in ("page_width", "page_height", "columns", "rows", "margin_left", "margin_top", "gap_x", "gap_y"):
            getattr(self, field).setValue(values.get(field, defaults[field]))
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
                      "recipient_italic"):
            setattr(self, field, values.get(field, defaults[field]))

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
        )

    def update_preview(self) -> None:
        self.preview.set_format(self.current_values())

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
        if item is None or item.text() in PRESETS:
            QMessageBox.information(self, "Format protégé", "Les formats prédéfinis ne peuvent pas être supprimés.")
            return
        self.formats.pop(item.text(), None)
        self.storage_path.write_text(json.dumps(self.formats, indent=2), encoding="utf-8")
        self.preset_list.takeItem(self.preset_list.row(item))

    def format_result(self) -> LabelFormat:
        return self.current_values()