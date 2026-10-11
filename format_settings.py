from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
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
    },
    "A4 - 3 x 8": {
        "page_width": 210, "page_height": 297, "columns": 3, "rows": 8,
        "margin_left": 8, "margin_top": 10, "gap_x": 2, "gap_y": 2,
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


class FormatSettingsDialog(QDialog):
    def __init__(self, current: LabelFormat, storage_path: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Formats d'étiquettes")
        self.resize(820, 560)
        self.storage_path = storage_path
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
        editor.addWidget(save_button)
        editor.addWidget(delete_button)
        editor.addStretch()
        editor.addWidget(apply_button)
        editor.addWidget(cancel_button)

        left = QVBoxLayout()
        left.addWidget(QLabel("Formats disponibles"))
        left.addWidget(self.preset_list)
        layout = QHBoxLayout(self)
        layout.addLayout(left, 1)
        layout.addLayout(editor, 2)
        layout.addWidget(self.preview, 2)
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
        for field in ("page_width", "page_height", "columns", "rows", "margin_left", "margin_top", "gap_x", "gap_y"):
            getattr(self, field).setValue(values[field])

    def current_values(self) -> LabelFormat:
        return LabelFormat(
            self.name.text().strip() or "Format personnalisé",
            self.page_width.value(), self.page_height.value(), int(self.columns.value()),
            int(self.rows.value()), self.margin_left.value(), self.margin_top.value(),
            self.gap_x.value(), self.gap_y.value(),
        )

    def update_preview(self) -> None:
        self.preview.set_format(self.current_values())

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
        QMessageBox.information(self, "Format enregistré", label_format.name)

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