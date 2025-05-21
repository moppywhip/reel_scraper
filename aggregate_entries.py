#!/usr/bin/env python3
"""
aggregate_entries_hardcoded.py

Hard-coded variant that reads the specific JSONL files already present in
./data and concatenates every attraction entry into one big list.
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import List, Dict, Any

# ---------------------------------------------------------------------------
# Files to read – adjust here if you add/remove shards
# ---------------------------------------------------------------------------
FILES = [
    "data/aggregated.jsonl",
    "data/aggregated_88321.jsonl",
    "data/aggregated_88322.jsonl",
    "data/aggregated_88323.jsonl",
    "data/aggregated_88324.jsonl",
    "data/aggregated_88325.jsonl",
    "data/aggregated_88326.jsonl",
    "data/aggregated_88327.jsonl",
]

OUTPUT = Path("data/all_entries.json")


def collect_entries(path_str: str) -> List[Dict[str, Any]]:
    """Load one JSONL file and return every dict inside its `entries` list."""
    entries: List[Dict[str, Any]] = []
    path = Path(path_str)
    if not path.exists():
        print(f"⚠️  Skipping missing file: {path}")
        return entries

    with path.open(encoding="utf-8") as fp:
        for line in fp:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                entries.extend(obj.get("entries", []))
            except json.JSONDecodeError:
                print(f"⚠️  Invalid JSON in {path}: {line[:80]}…")
    return entries


def main() -> None:
    aggregated: List[Dict[str, Any]] = []
    for file in FILES:
        print(f"Reading {file}")
        aggregated.extend(collect_entries(file))

    OUTPUT.write_text(json.dumps(aggregated, ensure_ascii=False, indent=2))
    print(f"\n✅ Wrote {len(aggregated)} combined entries to {OUTPUT}")


if __name__ == "__main__":
    main()