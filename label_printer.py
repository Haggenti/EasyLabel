#!/usr/bin/env python3

"""Data loading and layout primitives for the label printer."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


REQUIRED_COLUMNS = ("Destinataire", "Adresse", "Code postal", "Ville")


@dataclass(frozen=True)
class Sender:
    lines: tuple[str, ...]


@dataclass(frozen=True)
class Recipient:
    name: str
    address: str
    postal_code: str
    city: str


@dataclass(frozen=True)
class CsvDocument:
    path: Path
    sender: Sender
    recipients: tuple[Recipient, ...]


def load_csv(path: Path) -> CsvDocument:
    """Load a semicolon-separated label file.

    Sender metadata is optional and consists of one or more lines beginning
    with ``#EXPEDITEUR``. The first non-metadata row is the CSV header.
    """
    sender_lines: list[str] = []
    csv_rows: list[list[str]] = []

    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        for row in csv.reader(csv_file, delimiter=";"):
            if row and row[0].strip().upper() == "#EXPEDITEUR":
                sender_lines.extend(value.strip() for value in row[1:] if value.strip())
            else:
                csv_rows.append(row)

    if not csv_rows:
        raise ValueError(f"Le fichier {path.name} est vide")

    headers = [header.strip() for header in csv_rows[0]]
    missing = [column for column in REQUIRED_COLUMNS if column not in headers]
    if missing:
        raise ValueError(
            f"Colonnes manquantes dans {path.name} : {', '.join(missing)}"
        )

    indexes = {column: headers.index(column) for column in REQUIRED_COLUMNS}
    recipients: list[Recipient] = []
    for line_number, row in enumerate(csv_rows[1:], start=2):
        if not any(value.strip() for value in row):
            continue
        values = [row[index].strip() if index < len(row) else "" for index in indexes.values()]
        if not any(values):
            continue
        recipients.append(Recipient(*values))

    return CsvDocument(path, Sender(tuple(sender_lines)), tuple(recipients))


def find_csv_files(directory: Path) -> list[Path]:
    """Return CSV files directly contained in a directory, sorted by name."""
    return sorted(
        path for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() == ".csv"
    )