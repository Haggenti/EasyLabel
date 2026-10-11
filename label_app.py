#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
import tempfile
import os
from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, Qt
from PySide6.QtGui import QFont, QFontMetricsF, QPageLayout, QPageSize, QPainter, QPdfWriter
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
    QSpinBox,
    QVBoxLayout,
    QHBoxLayout,
    QComboBox,
    QWidget,
)

from label_printer import CsvDocument, find_csv_files, load_csv


POINTS_PER_MM = 72 / 25.4


def mm(value: float) -> float:
    return value * POINTS_PER_MM


class RenderStats:
    def __init__(self) -> None:
        self.labels = 0
        self.reduced = 0
        self.overflow = 0


def fit_font(text: str, rect: QRectF, base_size: int = 15, minimum_size: int = 9) -> tuple[QFont, bool]:
    flags = (Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
             | Qt.TextFlag.TextWordWrap)
    for size in range(base_size, minimum_size - 1, -1):
        font = QFont("DejaVu Sans", size)
        font.setBold(True)
        bounds = QFontMetricsF(font).boundingRect(rect, int(flags), text)
        if bounds.width() <= rect.width() and bounds.height() <= rect.height():
            return font, size < base_size

    font = QFont("DejaVu Sans", minimum_size)
    font.setBold(True)
    return font, False


def render_pdf(documents: list[CsvDocument], output_path: Path, columns: int, rows: int,
               margin_left: float, margin_top: float, gap_x: float, gap_y: float) -> RenderStats:
    writer = QPdfWriter(str(output_path))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
    writer.setResolution(72)

    page_width = mm(210)
    page_height = mm(297)
    label_width = (page_width - mm(margin_left) - mm(10) - mm(gap_x * (columns - 1))) / columns
    label_height = (page_height - mm(margin_top) - mm(10) - mm(gap_y * (rows - 1))) / rows
    painter = QPainter(writer)
    painter.setPen(Qt.GlobalColor.black)
    stats = RenderStats()
    slot = 0

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
            sender_height = label_height * 0.34
            sender_rect = label_rect.adjusted(mm(2), mm(2), -mm(2), -label_height + sender_height)
            recipient_rect = label_rect.adjusted(mm(2), sender_height, -mm(2), -mm(2))

            sender_font = QFont("DejaVu Sans", 9)
            sender_font.setBold(True)
            painter.setFont(sender_font)
            painter.drawText(sender_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                             "\n".join(document.sender.lines))

            recipient_text = "\n".join(
                value for value in (recipient.name, recipient.address,
                                    f"{recipient.postal_code} {recipient.city}") if value
            )
            recipient_font, was_reduced = fit_font(recipient_text, recipient_rect)
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


class LabelWindow(QMainWindow):
    def __init__(self, directory: Path):
        super().__init__()
        self.setWindowTitle("Impression d'étiquettes")
        self.resize(760, 520)
        self.directory = directory
        self.files: dict[str, Path] = {}
        self.file_list = QListWidget()
        self.file_list.itemChanged.connect(self.update_summary)
        self.summary = QLabel()
        self.columns = self._spin_box(2, 1, 8)
        self.rows = self._spin_box(5, 1, 20)
        self.margin_left = self._spin_box(10, 0, 50, 1)
        self.margin_top = self._spin_box(10, 0, 50, 1)
        self.gap_x = self._spin_box(3, 0, 30, 1)
        self.gap_y = self._spin_box(3, 0, 30, 1)
        self.printers = QComboBox()
        self.load_printers()

        choose_button = QPushButton("Ajouter des fichiers CSV")
        choose_button.clicked.connect(self.choose_files)
        export_button = QPushButton("Exporter le PDF")
        export_button.clicked.connect(self.export_pdf)
        print_button = QPushButton("Imprimer")
        print_button.clicked.connect(self.print_pdf)

        settings = QHBoxLayout()
        for label, control in (
            ("Colonnes", self.columns), ("Lignes", self.rows),
            ("Marge gauche (mm)", self.margin_left), ("Marge haut (mm)", self.margin_top),
            ("Espace X (mm)", self.gap_x), ("Espace Y (mm)", self.gap_y),
        ):
            settings.addWidget(QLabel(label))
            settings.addWidget(control)
        settings.addStretch()

        printer_settings = QHBoxLayout()
        printer_settings.addWidget(QLabel("Imprimante"))
        printer_settings.addWidget(self.printers)
        printer_settings.addStretch()

        buttons = QHBoxLayout()
        buttons.addWidget(choose_button)
        buttons.addStretch()
        preview_button = QPushButton("Aperçu")
        preview_button.clicked.connect(self.preview_pdf)
        buttons.addWidget(preview_button)
        buttons.addWidget(export_button)
        buttons.addWidget(print_button)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Fichiers CSV disponibles"))
        layout.addWidget(self.file_list)
        layout.addWidget(self.summary)
        layout.addLayout(settings)
        layout.addLayout(printer_settings)
        layout.addLayout(buttons)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)
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

    def add_file(self, path: Path) -> None:
        if str(path) in self.files:
            return
        try:
            document = load_csv(path)
            label = f"{path.name} ({len(document.recipients)} étiquettes)"
        except ValueError as error:
            label = f"{path.name} (erreur : {error})"
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, str(path))
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
        count = sum(
            1 for index in range(self.file_list.count())
            if self.file_list.item(index).checkState() == Qt.CheckState.Checked
        )
        self.summary.setText(f"{count} fichier(s) sélectionné(s)")

    def create_pdf(self) -> tuple[Path, RenderStats]:
        documents = self.selected_documents()
        if not documents:
            raise ValueError("Sélectionnez au moins un fichier CSV")
        file_descriptor, output_name = tempfile.mkstemp(prefix="etiquettes-", suffix=".pdf")
        Path(output_name).unlink(missing_ok=True)
        os.close(file_descriptor)
        output = Path(output_name)
        stats = render_pdf(documents, output, self.columns.value(), self.rows.value(),
                           self.margin_left.value(), self.margin_top.value(),
                           self.gap_x.value(), self.gap_y.value())
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
            temporary_pdf, stats = self.create_pdf()
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
            pdf_path, _ = self.create_pdf()
            dialog = PdfPreviewDialog(pdf_path, self)
            dialog.exec()
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Aperçu impossible", str(error))


    def print_pdf(self) -> None:
        try:
            pdf_path, stats = self.create_pdf()
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
    def __init__(self, pdf_path: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Aperçu des étiquettes")
        self.resize(850, 700)
        self.pdf_path = pdf_path
        self.document = QPdfDocument(self)
        self.document.load(str(pdf_path))

        view = QPdfView()
        view.setDocument(self.document)
        view.setPageMode(QPdfView.PageMode.MultiPage)
        view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        close_button = QPushButton("Fermer")
        close_button.clicked.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addWidget(view)
        layout.addWidget(close_button)

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