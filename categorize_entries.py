#!/usr/bin/env python3
"""
Assign a simple category (food | shopping | beauty | fun) to each attraction in a CSV
using Google Gemini 2.5-flash.

Requirements
------------
pip install google-generativeai pydantic python-dotenv

Before running, make sure you have GOOGLE_API_KEY in your environment
( `.env` works too – see analyze_reels.py ).

Usage
-----
python scripts/categorize_entries.py data/all_entries.csv \
       --out data/all_entries_labeled.csv \
       --workers 8
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import time
from pathlib import Path
from multiprocessing import Pool, cpu_count

from dotenv import load_dotenv
from google import genai
from pydantic import BaseModel, field_validator

# ------------------------ config & prompt text ------------------------ #

MODEL_NAME = "gemini-2.5-flash-preview-05-20"

# NEW taxonomy
CATEGORIES = [
    "food",
    "shopping",
    "beauty & skin care",
    "other attractions",
]

PROMPT_TEMPLATE = """\
You are helping categorize vacation attractions for a travel guide.

Given the attraction below, choose ONE best-fitting category from:
  • food
  • shopping
  • beauty & skin care
  • other attractions   (use this when none of the above clearly apply)

Respond ONLY with JSON of the form: {{"category": "<one_of_{categories}>"}}.

Attraction:
Name: {name}
Description: {desc}
"""

# ----------------------------- schema -------------------------------- #

class CatResp(BaseModel):
    category: str

    @field_validator("category")
    @classmethod
    def valid(cls, v: str) -> str:
        v = v.lower().strip()
        # normalise common shortcuts from the model
        if v in {"beauty", "beauty & skincare", "beauty and skin care"}:
            v = "beauty & skin care"
        if v not in CATEGORIES:
            raise ValueError(f"must be one of {CATEGORIES}")
        return v

# ------------------------- helper functions -------------------------- #

def ask_gemini(prompt: str) -> str:
    client = genai.Client()
    resp = client.models.generate_content(
        model=MODEL_NAME,
        contents=[prompt],
        config={
            "response_mime_type": "application/json",
            "response_schema": CatResp,
            "temperature": 0.0,
        },
    )
    # SDK >= 0.5 adds .parsed when response_schema used
    if getattr(resp, "parsed", None):
        return resp.parsed.category
    # fallback – parse text manually
    match = re.search(r'"category"\s*:\s*"([^"]+)"', resp.text, re.I)
    cat = match.group(1).lower().strip() if match else "other attractions"
    if cat in {"beauty", "beauty & skincare", "beauty and skin care"}:
        cat = "beauty & skin care"
    return cat


def process_row(row: dict[str, str]) -> dict[str, str]:
    prompt = PROMPT_TEMPLATE.format(
        name=row.get("name", ""),
        desc=row.get("description", ""),
        categories="|".join(CATEGORIES),
    )
    # Simple retry loop for transient API errors / quota hiccups
    for attempt in range(3):
        try:
            row["category"] = ask_gemini(prompt)
            break
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                print(f"FAILED for “{row.get('name')}”: {e}")
                row["category"] = "other attractions"
            else:
                time.sleep(1 + attempt)
    return row

# ------------------------------- main -------------------------------- #

def run(csv_file: str, out: str | None = None, workers: int | None = None) -> None:
    """Label attractions in *csv_file* and write the results."""
    load_dotenv()

    workers = workers or max(1, cpu_count() // 2)

    src = Path(csv_file)
    dst = Path(out) if out else src.with_name(src.stem + "_labeled.csv")

    rows: list[dict[str, str]]
    with src.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"Processing {len(rows)} rows with {workers} workers …")

    with Pool(processes=workers) as pool:
        rows = pool.map(process_row, rows)

    fieldnames = list(rows[0].keys())
    if "category" not in fieldnames:
        fieldnames.append("category")

    with dst.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"✓ Labeled CSV written to {dst}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Label attractions with a category.")
    parser.add_argument("csv_file", help="Source CSV (must have columns name, description)")
    parser.add_argument("-o", "--out", default=None, help="Destination CSV")
    parser.add_argument("-w", "--workers", type=int, default=None)
    args = parser.parse_args()

    run(args.csv_file, args.out, args.workers)


if __name__ == "__main__":
    main()
