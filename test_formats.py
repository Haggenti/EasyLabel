import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from format_settings import (FormatSettingsDialog, LabelFormat, PositionCanvas,
                              PositionEditorDialog, load_formats)
from label_app import (EnvelopeCanvas, EnvelopeFormatDialog, EnvelopeLayout, LabelWindow,
                       PrintMediaDialog,
                       RenderStats, render_envelope_pdf,
                       format_postal_code, render_pdf)
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
        self.assertEqual(label_format.corner_radius, 0)

    def test_missing_csv_directory_falls_back_to_project_csv(self):
        missing_directory = Path(tempfile.mkdtemp()) / "deleted-csv"
        fallback = LabelWindow.existing_csv_directory(missing_directory)
        self.assertEqual(fallback, Path(__file__).resolve().parent / "csv")

    def test_old_format_defaults_corner_radius_to_zero(self):
        path = Path(tempfile.mktemp(suffix=".json"))
        path.write_text(json.dumps({"Ancien": {"page_width": 210}}), encoding="utf-8")
        try:
            formats = load_formats(path)
            self.assertEqual(formats["Ancien"]["corner_radius"], 0)
        finally:
            path.unlink(missing_ok=True)

    def test_format_corner_radius_round_trip_and_clamp(self):
        path = Path(tempfile.mktemp(suffix=".json"))
        path.write_text(json.dumps({"Rond": {"page_width": 210, "corner_radius": 30}}), encoding="utf-8")
        try:
            formats = load_formats(path)
            self.assertEqual(formats["Rond"]["corner_radius"], 30)
            dialog = FormatSettingsDialog(LabelFormat("Rond", label_width=40,
                                                       label_height=20, corner_radius=30), path)
            dialog.label_width.setValue(40)
            dialog.label_height.setValue(20)
            dialog.update_corner_radius_range()
            self.assertEqual(dialog.corner_radius.maximum(), 10)
            self.assertEqual(dialog.corner_radius.value(), 10)
            dialog.close()
        finally:
            path.unlink(missing_ok=True)

    def test_postal_code_is_padded_to_five_digits(self):
        self.assertEqual(format_postal_code("3250"), "03250")
        self.assertEqual(format_postal_code("03250"), "03250")
        self.assertEqual(format_postal_code("48000"), "48000")

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

    def test_position_editor_detects_all_resize_edges(self):
        preview = PositionCanvas(LabelFormat("test"))
        rect = preview.geometry_for("recipient")
        self.assertEqual(preview.resize_edges("recipient", QPointF(rect.left(), rect.center().y())), "l")
        self.assertEqual(preview.resize_edges("recipient", QPointF(rect.right(), rect.center().y())), "r")
        self.assertEqual(preview.resize_edges("recipient", QPointF(rect.center().x(), rect.top())), "t")
        self.assertEqual(preview.resize_edges("recipient", QPointF(rect.center().x(), rect.bottom())), "b")
        self.assertEqual(preview.resize_edges("recipient", QPointF(rect.left(), rect.top())), "lt")
        preview.close()

    def test_sender_height_does_not_move_recipient_frame(self):
        preview = PositionCanvas(LabelFormat("test"))
        original = preview.geometry_for("recipient")
        preview.format.sender_height = 30
        updated = preview.geometry_for("recipient")
        self.assertEqual(updated.top(), original.top())
        self.assertEqual(updated.height(), original.height())
        preview.close()

    def test_horizontal_position_has_gentle_magnetic_snapping(self):
        preview = PositionCanvas(LabelFormat("test"))
        page_width, _ = preview.label_dimensions()
        base_x, _, width, _ = preview.base_geometry("recipient")
        tolerance = preview.SNAP_DISTANCE_MM * preview.LOGICAL_WIDTH / page_width
        center_position = (preview.LOGICAL_WIDTH - width) / 2 - base_x
        self.assertAlmostEqual(
            preview.snap_horizontal_position(
                "recipient", center_position + tolerance / 2, base_x, width, page_width
            ),
            center_position,
        )
        self.assertAlmostEqual(
            preview.snap_horizontal_position(
                "recipient", center_position + tolerance * 2, base_x, width, page_width
            ),
            center_position + tolerance * 2,
        )
        preview.close()

    def test_envelope_editor_detects_all_resize_edges(self):
        canvas = EnvelopeCanvas(EnvelopeLayout())
        rect = canvas.rect_for("recipient")
        self.assertEqual(canvas.resize_edges("recipient", QPointF(rect.left(), rect.center().y())), "l")
        self.assertEqual(canvas.resize_edges("recipient", QPointF(rect.right(), rect.center().y())), "r")
        self.assertEqual(canvas.resize_edges("recipient", QPointF(rect.center().x(), rect.top())), "t")
        self.assertEqual(canvas.resize_edges("recipient", QPointF(rect.center().x(), rect.bottom())), "b")
        self.assertEqual(canvas.resize_edges("recipient", QPointF(rect.left(), rect.top())), "lt")
        canvas.close()

    def test_automatic_centering_disables_margin_controls(self):
        dialog = FormatSettingsDialog(LabelFormat("test"), Path("/tmp/tik-formats.json"))
        dialog.auto_center_horizontal.setChecked(True)
        expected_left = (dialog.page_width.value()
                         - dialog.columns.value() * dialog.label_width.value()
                         - (dialog.columns.value() - 1) * dialog.gap_x.value()) / 2
        self.assertFalse(dialog.margin_left.isEnabled())
        self.assertAlmostEqual(dialog.margin_left.value(), expected_left, places=1)
        dialog.auto_center_horizontal.setChecked(False)
        self.assertTrue(dialog.margin_left.isEnabled())
        dialog.close()

    def test_active_format_has_green_check_marker(self):
        dialog = FormatSettingsDialog(LabelFormat("A4 - 2 x 5"), Path("/tmp/tik-formats.json"))
        active_item = dialog.find_format_item("A4 - 2 x 5")
        other_item = dialog.find_format_item("A4 - 3 x 8")
        self.assertFalse(active_item.icon().isNull())
        self.assertTrue(other_item.icon().isNull())
        dialog.close()

    def test_save_button_only_enables_for_unsaved_changes(self):
        dialog = FormatSettingsDialog(LabelFormat("test"), Path("/tmp/tik-formats.json"))
        self.assertFalse(dialog.save_button.isEnabled())

        original_width = dialog.page_width.value()
        dialog.page_width.setValue(original_width + 1)
        self.assertTrue(dialog.save_button.isEnabled())

        dialog.page_width.setValue(original_width)
        self.assertFalse(dialog.save_button.isEnabled())
        dialog.close()

    def test_changing_format_does_not_enable_save_button(self):
        path = Path(tempfile.mktemp(suffix=".json"))
        path.write_text(json.dumps({
            "Format 1": asdict(LabelFormat("Format 1")),
            "Format 2": asdict(LabelFormat("Format 2", columns=2)),
        }), encoding="utf-8")
        try:
            dialog = FormatSettingsDialog(LabelFormat("Format 1"), path)
            dialog.preset_list.setCurrentItem(dialog.find_format_item("Format 2"))
            self.assertFalse(dialog.save_button.isEnabled())
            dialog.close()
        finally:
            path.unlink(missing_ok=True)

    def test_apply_button_only_enables_for_an_inactive_format(self):
        path = Path(tempfile.mktemp(suffix=".json"))
        path.write_text(json.dumps({
            "Format 1": asdict(LabelFormat("Format 1")),
            "Format 2": asdict(LabelFormat("Format 2", columns=2)),
        }), encoding="utf-8")
        try:
            dialog = FormatSettingsDialog(LabelFormat("Format 1"), path)
            self.assertFalse(dialog.apply_button.isEnabled())

            dialog.preset_list.setCurrentItem(dialog.find_format_item("Format 2"))
            self.assertTrue(dialog.apply_button.isEnabled())
            dialog.close()
        finally:
            path.unlink(missing_ok=True)

    def test_deleting_active_format_activates_previous_format(self):
        path = Path(tempfile.mktemp(suffix=".json"))
        path.write_text(json.dumps({
            "Format 1": asdict(LabelFormat("Format 1")),
            "Format 2": asdict(LabelFormat("Format 2", columns=2)),
            "Format 3": asdict(LabelFormat("Format 3", columns=3)),
        }), encoding="utf-8")
        applied = []
        try:
            dialog = FormatSettingsDialog(
                LabelFormat("Format 2"), path, format_saved_callback=applied.append
            )
            with patch.object(QMessageBox, "question",
                              return_value=QMessageBox.StandardButton.Yes):
                dialog.delete_format()
            self.assertEqual(dialog.active_format_name, "Format 1")
            self.assertEqual(applied[-1].name, "Format 1")
            self.assertEqual(dialog.preset_list.currentItem().text().split(" (")[0], "Format 1")
            dialog.close()
        finally:
            path.unlink(missing_ok=True)

    def test_envelope_layout_round_trip(self):
        layout = EnvelopeLayout(
            page_width=229, page_height=162, sender_enabled=False,
            sender_x=18, recipient_x=126, recipient_italic=True,
            postal_code_enabled=True, postal_code_x=24, postal_code_width=75,
            background_image="/tmp/envelope-scan.png",
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
        self.assertEqual(restored.background_image, "/tmp/envelope-scan.png")

    def test_render_without_sender(self):
        csv_path = next(Path("csv").glob("*.csv"))
        output = Path("/tmp/tik-test-labels-no-sender.pdf")
        stats = render_pdf(
            [load_csv(csv_path)], output, 2, 5, 10, 10, 3, 3,
            sender_enabled=False,
        )

        self.assertTrue(output.exists())
        self.assertGreater(stats.labels, 0)
        self.assertEqual(stats.pages, (stats.labels + 9) // 10)
        output.unlink(missing_ok=True)

    def test_render_with_rounded_guides(self):
        csv_path = next(Path("csv").glob("*.csv"))
        output = Path("/tmp/tik-test-rounded-labels.pdf")
        stats = render_pdf(
            [load_csv(csv_path)], output, 2, 5, 10, 10, 3, 3,
            show_guides=True, corner_radius=6,
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
        self.assertEqual(stats.pages, stats.labels)
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
        with patch("label_app.subprocess.run", side_effect=OSError("test")):
            with patch("label_app.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
                with patch("label_app.QMessageBox.warning"):
                    window.print_pdf()
        self.assertFalse(output.exists())
        window.close()

    def test_print_sends_all_pages_to_cups(self):
        window = LabelWindow(Path("csv"))
        output = Path(tempfile.mkstemp(suffix=".pdf")[1])
        window.create_pdf = lambda show_guides: (output, RenderStats())
        result = Mock(returncode=0)
        with patch("label_app.subprocess.run", return_value=result) as run:
            with patch("label_app.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
                with patch("label_app.QMessageBox.information"):
                    window.print_pdf()
        command = run.call_args.args[0]
        self.assertIn(["-n", "1"], [command[index:index + 2] for index in range(len(command) - 1)])
        self.assertNotIn("-P", command)
        self.assertFalse(output.exists())
        window.close()

    def test_cups_page_size_matches_envelope_format(self):
        window = LabelWindow(Path("csv"))
        window.mode.setCurrentIndex(1)
        window.envelope_page_width = 220
        window.envelope_page_height = 110
        self.assertEqual(window.cups_page_size(), "EnvDL")
        window.envelope_page_width = 229
        window.envelope_page_height = 162
        self.assertEqual(window.cups_page_size(), "EnvC5")
        window.close()

    def test_envelope_print_dialog_defaults_to_multipurpose_source(self):
        dialog = PrintMediaDialog(
            [("Enveloppe", "Envelope")],
            [("Automatique", ""), ("Multipurpose", "Multipurpose"), ("Manual", "Manual")],
            "Envelope",
            "Multipurpose",
        )
        self.assertEqual(dialog.source.currentData(), "Multipurpose")
        dialog.close()

    def test_csv_print_button_does_not_enter_test_page_mode(self):
        window = LabelWindow(Path("csv"))
        window.print_button.setEnabled(True)
        with patch.object(window, "print_pdf") as print_pdf:
            window.print_button.click()
        print_pdf.assert_called_once_with()
        window.close()

    def test_file_filter_only_matches_file_name(self):
        window = LabelWindow(Path("csv"))
        window.filter_files("29")
        visible_names = [
            window.file_list.item(index).text()
            for index in range(window.file_list.count())
            if not window.file_list.item(index).isHidden()
        ]
        self.assertEqual(visible_names, [])
        window.filter_files("12")
        visible_names = [
            window.file_list.item(index).text()
            for index in range(window.file_list.count())
            if not window.file_list.item(index).isHidden()
        ]
        self.assertTrue(visible_names)
        self.assertTrue(all("12" in name.casefold() for name in visible_names))
        window.close()



if __name__ == "__main__":
    unittest.main()
