import json
import unittest
from dataclasses import asdict
from pathlib import Path

from PySide6.QtWidgets import QApplication

from format_settings import LabelFormat, PositionEditorDialog
from label_app import EnvelopeLayout, render_envelope_pdf, render_pdf
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
        )
        restored = EnvelopeLayout(**json.loads(json.dumps(asdict(layout))))

        self.assertEqual(restored.page_width, 229)
        self.assertEqual(restored.sender_x, 18)
        self.assertEqual(restored.recipient_x, 126)
        self.assertFalse(restored.sender_enabled)
        self.assertTrue(restored.recipient_italic)

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
        )

        self.assertTrue(output.exists())
        self.assertGreater(stats.labels, 0)
        output.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
