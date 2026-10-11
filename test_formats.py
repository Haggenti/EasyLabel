import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from format_settings import LabelFormat, PositionEditorDialog
from label_app import (EnvelopeFormatDialog, EnvelopeLayout, LabelWindow,
                       PrintOptionsDialog, RenderStats, render_envelope_pdf,
                       render_pdf)
from label_printer import load_csv


class FormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_label_defaults_include_sender(self):
        label_format = LabelFormat("test")

        self.assertTrue(label_format.sender_enabled)
        self.assertEqual(label_format.sender_font_size, 9)
        self.assertEqual(label_format.recipient_font_size, 15)

    def test_position_reset_restores_typography(self):
        label_format = LabelFormat(
            "test", sender_enabled=False, sender_font_size=20,
            sender_bold=False, recipient_font_size=7, recipient_italic=True,
        )
        dialog = PositionEditorDialog(label_format)
        dialog.reset_positions()

        self.assertTrue(dialog.canvas.format.sender_enabled)
        self.assertEqual(dialog.canvas.format.sender_font_size, 9)
        self.assertTrue(dialog.canvas.format.sender_bold)
        self.assertEqual(dialog.canvas.format.recipient_font_size, 15)
        self.assertFalse(dialog.canvas.format.recipient_italic)
        dialog.close()

    def test_envelope_layout_round_trip(self):
        layout = EnvelopeLayout(
            page_width=229, page_height=162, sender_enabled=False,
            sender_x=18, recipient_x=126, recipient_italic=True,
            postal_code_enabled=True, postal_code_x=24, postal_code_width=75,
        )
        restored = EnvelopeLayout(**json.loads(json.dumps(asdict(layout))))

        self.assertEqual(restored.page_width, 229)
        self.assertEqual(restored.sender_x, 18)
        self.assertEqual(restored.recipient_x, 126)
        self.assertFalse(restored.sender_enabled)
        self.assertTrue(restored.recipient_italic)
        self.assertTrue(restored.postal_code_enabled)
        self.assertEqual(restored.postal_code_x, 24)
        self.assertEqual(restored.postal_code_width, 75)

    def test_render_without_sender(self):
        csv_path = next(Path("csv").glob("*.csv"))
        output = Path("/tmp/tik-test-labels-no-sender.pdf")
        stats = render_pdf(
            [load_csv(csv_path)], output, 2, 5, 10, 10, 3, 3,
            sender_enabled=False,
        )

        self.assertTrue(output.exists())
        self.assertGreater(stats.labels, 0)
        output.unlink(missing_ok=True)

    def test_render_envelope_with_custom_layout(self):
        csv_path = next(Path("csv").glob("*.csv"))
        output = Path("/tmp/tik-test-envelope.pdf")
        stats = render_envelope_pdf(
            [load_csv(csv_path)], output, (229, 162),
            126, 45, 87, 70, sender_enabled=False,
            sender_font_size=11, recipient_font_size=13,
            recipient_italic=True,
            postal_code_enabled=True, postal_code_x=25, postal_code_y=118,
            postal_code_width=80, postal_code_height=12,
        )

        self.assertTrue(output.exists())
        self.assertGreater(stats.labels, 0)
        output.unlink(missing_ok=True)

    def test_invalid_envelope_presets_are_ignored(self):
        valid = asdict(EnvelopeLayout(page_width=229))

        class SettingsStub:
            def value(self, key, default=""):
                del key, default
                return json.dumps({"Valide": valid, "Invalide": {"page_width": 229}})

        window = LabelWindow.__new__(LabelWindow)
        window.settings = SettingsStub()
        presets = LabelWindow.load_envelope_presets(window)

        self.assertIn("Valide", presets)
        self.assertNotIn("Invalide", presets)

    def test_old_envelope_presets_keep_settings_after_alignment_upgrade(self):
        old_layout = asdict(EnvelopeLayout(page_width=245, recipient_x=130))
        old_layout.pop("sender_alignment")
        old_layout.pop("recipient_alignment")

        class SettingsStub:
            def value(self, key, default=""):
                del default
                if key == "envelope_formats":
                    return json.dumps({"Ancien": old_layout})
                return ""

        window = LabelWindow.__new__(LabelWindow)
        window.settings = SettingsStub()
        presets = LabelWindow.load_envelope_presets(window)

        self.assertEqual(presets["Ancien"]["page_width"], 245)
        self.assertEqual(presets["Ancien"]["recipient_x"], 130)
        self.assertEqual(presets["Ancien"]["sender_alignment"], "center")
        self.assertEqual(presets["Ancien"]["recipient_alignment"], "center")

    def test_cancel_envelope_edit_does_not_mutate_preset(self):
        layout = EnvelopeLayout(recipient_x=126)
        dialog = EnvelopeFormatDialog({"Test": asdict(layout)}, "Test")
        editor = Mock()
        editor.exec.return_value = QDialog.DialogCode.Rejected

        def create_editor(edited_layout, *args):
            edited_layout.recipient_x = 999
            return editor

        with patch("label_app.EnvelopeEditorDialog", side_effect=create_editor):
            dialog.edit_format()

        self.assertEqual(dialog.current_layout.recipient_x, 126)
        dialog.close()

    def test_export_cleans_temporary_pdf_on_error(self):
        window = LabelWindow(Path("csv"))
        output = Path(tempfile.mkstemp(suffix=".pdf")[1])
        window.create_pdf = lambda show_guides: (output, RenderStats())
        with patch("label_app.QFileDialog.getSaveFileName", side_effect=OSError("test")):
            with patch("label_app.QMessageBox.warning"):
                window.export_pdf()
        self.assertFalse(output.exists())
        window.close()

    def test_print_cleans_temporary_pdf_on_error(self):
        window = LabelWindow(Path("csv"))
        output = Path(tempfile.mkstemp(suffix=".pdf")[1])
        window.create_pdf = lambda show_guides: (output, RenderStats())
        options = Mock()
        options.exec.return_value = QDialog.DialogCode.Accepted
        options.test_page.isChecked.return_value = False
        options.copies.value.return_value = 1
        options.page_range.text.return_value = ""
        with patch("label_app.subprocess.run", side_effect=OSError("test")):
            with patch("label_app.PrintOptionsDialog", return_value=options):
                with patch("label_app.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
                    with patch("label_app.QMessageBox.warning"):
                        window.print_pdf()
        self.assertFalse(output.exists())
        window.close()

    def test_print_options_pass_copies_and_page_range_to_cups(self):
        window = LabelWindow(Path("csv"))
        output = Path(tempfile.mkstemp(suffix=".pdf")[1])
        window.create_pdf = lambda show_guides: (output, RenderStats())
        options = Mock()
        options.exec.return_value = QDialog.DialogCode.Accepted
        options.test_page.isChecked.return_value = False
        options.copies.value.return_value = 3
        options.page_range.text.return_value = "2-4"
        result = Mock(returncode=0)
        with patch("label_app.PrintOptionsDialog", return_value=options):
            with patch("label_app.subprocess.run", return_value=result) as run:
                with patch("label_app.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
                    with patch("label_app.QMessageBox.information"):
                        window.print_pdf()
        command = run.call_args.args[0]
        self.assertIn(["-n", "3"], [command[index:index + 2] for index in range(len(command) - 1)])
        self.assertIn(["-P", "2-4"], [command[index:index + 2] for index in range(len(command) - 1)])
        self.assertFalse(output.exists())
        window.close()

    def test_print_options_dialog_limits_test_page_to_first_page(self):
        dialog = PrintOptionsDialog()
        dialog.test_page.setChecked(True)
        self.assertFalse(dialog.page_range.isEnabled())
        dialog.test_page.setChecked(False)
        self.assertTrue(dialog.page_range.isEnabled())
        dialog.close()

    def test_page_range_parser_accepts_common_ranges(self):
        self.assertEqual(PrintOptionsDialog.parse_page_range("1"), [1])
        self.assertEqual(PrintOptionsDialog.parse_page_range("2-4"), [2, 3, 4])
        self.assertEqual(PrintOptionsDialog.parse_page_range("1, 3, 5"), [1, 3, 5])
        self.assertEqual(PrintOptionsDialog.parse_page_range("1,2-3,3"), [1, 2, 3])

    def test_page_range_parser_rejects_invalid_ranges(self):
        self.assertIsNone(PrintOptionsDialog.parse_page_range("0"))
        self.assertIsNone(PrintOptionsDialog.parse_page_range("4-2"))
        self.assertIsNone(PrintOptionsDialog.parse_page_range("1,a"))


if __name__ == "__main__":
    unittest.main()
