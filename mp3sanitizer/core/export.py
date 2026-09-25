"""Export naar CSV voor Nederlandse Excel: UTF-8 met BOM en puntkomma als scheidingsteken."""

from __future__ import annotations

import csv
from collections.abc import Iterable, Sequence
from pathlib import Path

CSV_ENCODING = "utf-8-sig"  # BOM: Excel herkent dan UTF-8 (accenten blijven goed)
CSV_DELIMITER = ";"  # Nederlandse Excel gebruikt ; als lijstscheidingsteken


def export_csv(path: Path, headers: Sequence[str], rows: Iterable[Sequence[object]]) -> int:
    """Schrijf een CSV-bestand; geeft het aantal datarijen terug."""
    count = 0
    with path.open("w", encoding=CSV_ENCODING, newline="") as fh:
        writer = csv.writer(fh, delimiter=CSV_DELIMITER, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(["" if v is None else v for v in row])
            count += 1
    return count
