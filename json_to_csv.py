#!/usr/bin/env python3
"""
Convert a JSON array of objects (e.g. data/all_entries.json) to CSV.

Usage:
  python scripts/json_to_csv.py data/all_entries.json
  # or specify a custom output path
  python scripts/json_to_csv.py data/all_entries.json -o output/my_places.csv
"""
import argparse
import csv
import json
from pathlib import Path


def json_to_csv(json_path: Path, csv_path: Path) -> None:
    # Load the JSON data
    with json_path.open(encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("Input JSON must contain a top-level array of objects.")

    # Collect all unique keys that appear in the objects
    all_keys = {k for item in data for k in item.keys()}

    # Put the most common fields first, others alphabetically after
    preferred_order = ["name", "description", "url", "address"]
    header = [k for k in preferred_order if k in all_keys] + sorted(
        all_keys - set(preferred_order)
    )

    # Write the CSV
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        for row in data:
            writer.writerow(row)

    print(f"✓ Wrote {len(data)} rows to {csv_path}")


def run(json_file: str, output: str | None = None) -> None:
    """Convert *json_file* (array of objects) to CSV."""
    json_path = Path(json_file)
    csv_path = Path(output) if output else json_path.with_suffix(".csv")
    json_to_csv(json_path, csv_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert JSON array to CSV.")
    parser.add_argument("json_file", help="Path to the source JSON file.")
    parser.add_argument(
        "-o",
        "--output",
        help="Destination CSV file (defaults to same name with .csv).",
    )
    args = parser.parse_args()

    run(args.json_file, args.output)


if __name__ == "__main__":
    main()
