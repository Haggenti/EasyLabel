import tempfile
import unittest
from pathlib import Path

from label_printer import load_csv


class CsvLoadingTests(unittest.TestCase):
    def test_loads_sender_metadata_and_recipients(self):
        content = (
            "#EXPEDITEUR;SUD PTT 81 - 12 - 46 - 82\n"
            "#EXPEDITEUR;59, rue Raymond Sommer - 81000 ALBI\n"
            "#EXPEDITEUR;05 63 38 43 81 - sud81laposte@gmail.com\n"
            "Destinataire;Adresse;Code postal;Ville\n"
            "LA POSTE;Le Bourg;46500;ALVIGNAC\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "labels.csv"
            path.write_text(content, encoding="utf-8")

            document = load_csv(path)

        self.assertEqual(document.sender.lines[0], "SUD PTT 81 - 12 - 46 - 82")
        self.assertEqual(document.sender.lines[2], "05 63 38 43 81 - sud81laposte@gmail.com")
        self.assertEqual(document.recipients[0].city, "ALVIGNAC")

    def test_loads_existing_csv_without_sender(self):
        content = (
            "Destinataire;Adresse;Code postal;Ville\n"
            "LA POSTE;Le Bourg;46500;ALVIGNAC\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "labels.csv"
            path.write_text(content, encoding="utf-8")

            document = load_csv(path)

        self.assertEqual(document.sender.lines, ())
        self.assertEqual(len(document.recipients), 1)
        self.assertIn("expéditeur absent", document.issues)

    def test_reports_incomplete_recipient_row(self):
        content = (
            "#EXPEDITEUR;SUD PTT\n"
            "Destinataire;Adresse;Code postal;Ville\n"
            "LA POSTE;Rue du Test;;RODEZ\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "labels.csv"
            path.write_text(content, encoding="utf-8")

            document = load_csv(path)

        self.assertTrue(any("Code postal" in issue for issue in document.issues))


if __name__ == "__main__":
    unittest.main()