
#!/usr/bin/env python3

import argparse
import csv
import re
import sys
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

NS = {
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}

POSTCODE_CITY = re.compile(r"^\s*(\d{5})\s+(.+?)\s*$")


def paragraph_text(paragraph):
    parts = []
    for node in paragraph.iter():
        if node.tag == f"{{{NS['text']}}}s":
            count = int(node.attrib.get(f"{{{NS['text']}}}c", "1"))
            parts.append(" " * count)
        elif node.tag in (
            f"{{{NS['text']}}}tab",
            f"{{{NS['text']}}}line-break",
        ):
            parts.append(" ")
        elif node.text:
            parts.append(node.text)
        if node.tail:
            parts.append(node.tail)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def extract_labels(input_path):
    with zipfile.ZipFile(input_path) as archive:
        xml_data = archive.read("content.xml")

    root = ET.fromstring(xml_data)
    rows = []

    for frame in root.findall(".//draw:page/draw:frame", NS):
        lines = [
            paragraph_text(p)
            for p in frame.findall(".//text:p", NS)
        ]
        lines = [line for line in lines if line]

        if not lines:
            continue

        has_la_poste = any(
            line.strip().upper() == "LA POSTE" for line in lines
        )

        try:
            index = next(
                i for i, line in enumerate(lines)
                if line.strip().upper() == "LA POSTE"
            )
            recipient_lines = lines[index + 1:]
        except StopIteration:
            recipient_lines = lines

        code_postal = ""
        ville = ""
        adresse = ""
        city_index = None

        for i in range(len(recipient_lines) - 1, -1, -1):
            match = POSTCODE_CITY.match(recipient_lines[i])
            if match:
                code_postal, ville = match.groups()
                city_index = i
                break

        if city_index is not None:
            adresse = " ".join(recipient_lines[:city_index]).strip()
        elif recipient_lines:
            adresse = " ".join(recipient_lines).strip()

        rows.append({
            "Destinataire": "LA POSTE" if has_la_poste else "",
            "Adresse": adresse,
            "Code postal": code_postal,
            "Ville": ville,
        })

    return rows


def convert_file(input_path, output_path):
    rows = extract_labels(input_path)

    if not rows:
        raise ValueError("Aucune étiquette trouvée")

    with output_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["Destinataire", "Adresse", "Code postal", "Ville"],
            delimiter=";",
        )
        writer.writeheader()
        writer.writerows(rows)

    return len(rows)


def main():
    parser = argparse.ArgumentParser(
        description="Convertit un ou plusieurs fichiers ODG en CSV pour Calc."
    )
    parser.add_argument(
        "chemin",
        help="Fichier ODG ou répertoire contenant des fichiers ODG"
    )
    parser.add_argument(
        "-o", "--output-dir",
        help="Répertoire de sortie (par défaut : à côté des fichiers source)"
    )
    parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Cherche aussi dans les sous-répertoires"
    )
    args = parser.parse_args()

    source = Path(args.chemin)
    output_dir = Path(args.output_dir) if args.output_dir else None

    if source.is_file():
        files = [source] if source.suffix.lower() == ".odg" else []
    elif source.is_dir():
        pattern = "**/*" if args.recursive else "*"
        files = sorted(
            p for p in source.glob(pattern)
            if p.is_file() and p.suffix.lower() == ".odg"
        )
    else:
        print(f"Chemin introuvable : {source}", file=sys.stderr)
        return 1

    if not files:
        print("Aucun fichier .odg trouvé.", file=sys.stderr)
        return 1

    successes = 0
    failures = 0

    for input_path in files:
        destination_dir = output_dir if output_dir else input_path.parent
        destination_dir.mkdir(parents=True, exist_ok=True)
        output_path = destination_dir / (input_path.stem + ".csv")

        try:
            count = convert_file(input_path, output_path)
            print(f"OK : {input_path} -> {output_path} ({count} étiquettes)")
            successes += 1
        except Exception as exc:
            print(f"ERREUR : {input_path} : {exc}", file=sys.stderr)
            failures += 1

    print(f"\nTerminé : {successes} réussi(s), {failures} erreur(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
