"""Export the prototype DuckDB blob to per-table CSV files.

One-shot developer step (Design §11 / Discovery §22 L3). The output CSVs are
gitignored; only the schema and this script are committed.

Every table is exported in FK-safe order. JSON columns
(``variant_annotations.annotations_json``) are serialised as compact JSON
strings so ``psql \\copy`` reads them back as ``jsonb`` cleanly.

Usage
-----
::

    python db/seed/export_from_duckdb.py \\
        --duckdb ../test_data/clinical_genetics.duckdb \\
        --out    db/seed/data
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

# ── Table order (FK-safe on both export and load) ────────────────────
# Parents first, then children.
TABLE_ORDER: list[str] = [
    "patients",
    "prs_annotations",
    "variant_annotations",
    "kinship_history_annotations",
    "diagnoses",
    "patient_prs",
    "patient_variants",
    "patient_pgx_status",
    "pgx_annotations",
    "patient_kinship_history",
]

# Columns that Postgres will interpret as ``jsonb``. Serialise as compact JSON.
JSON_COLUMNS: dict[str, set[str]] = {
    "variant_annotations": {"annotations_json"},
}


def _cell_to_csv(value: Any, is_json: bool) -> str | None:
    """Convert a DuckDB cell value to a string suitable for CSV.

    - ``None`` stays as ``None`` — the CSV writer emits an empty field, and
      ``load.sql`` interprets empty fields as SQL NULL via ``NULL AS ''``.
    - ``date`` → ISO 8601.
    - JSON columns → ``json.dumps`` compact form.
    - Everything else → ``str(value)``.
    """
    if value is None:
        return None
    if is_json:
        # DuckDB may return a Python str, dict, or list depending on JSON type.
        if isinstance(value, (dict, list)):
            return json.dumps(value, separators=(",", ":"))
        if isinstance(value, str):
            # Round-trip to validate + normalise whitespace.
            try:
                parsed = json.loads(value)
                return json.dumps(parsed, separators=(",", ":"))
            except json.JSONDecodeError:
                # Fall through — preserve the raw string.
                return value
        return json.dumps(value, separators=(",", ":"))
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _export_table(con: Any, table: str, out_dir: Path) -> int:
    """Write one CSV file for ``table`` and return the row count."""
    out_path = out_dir / f"{table}.csv"
    cursor = con.execute(f"SELECT * FROM {table}")
    columns = [d[0] for d in cursor.description]
    json_cols = JSON_COLUMNS.get(table, set())

    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(columns)
        rows_written = 0
        for row in cursor.fetchall():
            writer.writerow(
                _cell_to_csv(cell, name in json_cols)
                for cell, name in zip(row, columns, strict=True)
            )
            rows_written += 1
    return rows_written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip() if __doc__ else "")
    parser.add_argument("--duckdb", type=Path, required=True, help="Path to DuckDB blob.")
    parser.add_argument("--out", type=Path, required=True, help="Output directory for CSVs.")
    args = parser.parse_args()

    if not args.duckdb.is_file():
        print(f"ERROR: DuckDB file not found at {args.duckdb}", file=sys.stderr)
        return 2

    args.out.mkdir(parents=True, exist_ok=True)

    try:
        import duckdb  # noqa: PLC0415
    except ImportError:
        print(
            "ERROR: duckdb Python package not installed. "
            "Install with `pip install duckdb` or `pip install -e '.[dev]'`.",
            file=sys.stderr,
        )
        return 2

    con = duckdb.connect(str(args.duckdb), read_only=True)
    try:
        print(f"Exporting from {args.duckdb} to {args.out}")
        total = 0
        for table in TABLE_ORDER:
            count = _export_table(con, table, args.out)
            print(f"  {table:<40} {count:>10,} rows")
            total += count
        print(f"Done. {total:,} rows across {len(TABLE_ORDER)} tables.")
    finally:
        con.close()

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
