#!/usr/bin/env python3
"""Analyze downloaded reels using the Gemini API.

This script scans the downloads directory created by ``reel_scraper.py``
and for each reel video does the following:

1. Ask Gemini if the reel is relevant to food, self care or tourist attractions.
2. If relevant, ask Gemini again to extract structured details about any
   businesses or places mentioned in the reel. The output includes name,
   category (food/self care/attraction), address and website. Multiple
   entries may be returned for a single video.

The structured results are saved as ``analysis.json`` inside each reel
folder.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List
import os

from google import genai
from google.genai.types import GenerateContentConfig, Part, Tool, GoogleSearch
from dotenv import load_dotenv
load_dotenv()

RELEVANCE_PROMPT = (
    "Return JSON only in the form {'relevant': true} if the video contains "
    "any business or place related to food, self care, or an attraction. "
    "Return {'relevant': false} otherwise."
)

EXTRACTION_PROMPT = (
    "You are an AI that extracts businesses or attractions from a video. "
    "Respond ONLY with a JSON array where each item has the fields "
    "name, category (food, self care, attraction), address, and website."
)

MODEL_NAME = "gemini-2.5-flash"


def load_video_file(folder: Path) -> Path | None:
    """Return the first video file inside a reel folder."""
    for file in folder.iterdir():
        if file.suffix.lower() in {".mp4", ".mov", ".webm"}:
            return file
    return None


def call_gemini(parts: List[Part], prompt: str, *, tools: bool = False) -> str:
    """Call the Gemini API with optional search grounding."""
    client = genai.Client(GOOGLE_API_KEY=os.environ["GOOGLE_API_KEY"])
    config = GenerateContentConfig(
        temperature=0.0,
        tools=[Tool(google_search=GoogleSearch())] if tools else None,
    )
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=parts + [prompt],
        config=config,
    )
    return response.text


def parse_bool(text: str) -> bool:
    try:
        data = json.loads(text)
        return bool(data.get("relevant"))
    except Exception:
        return False


def parse_json(text: str) -> List[Dict[str, Any]]:
    cleaned = text.strip().strip("`")
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def analyze_reel(folder: Path) -> None:
    analysis_file = folder / "analysis.json"
    if analysis_file.exists():
        return
    video = load_video_file(folder)
    if not video:
        print(f"No video found in {folder}")
        return
    with video.open("rb") as f:
        video_part = Part.from_file(f, mime_type="video/mp4")
        relevance_text = call_gemini([video_part], RELEVANCE_PROMPT)
        if not parse_bool(relevance_text):
            print(f"Skipping irrelevant reel {folder.name}")
            analysis_file.write_text(json.dumps({"relevant": False}, indent=2))
            return
        details_text = call_gemini([video_part], EXTRACTION_PROMPT, tools=True)
        results = parse_json(details_text)
    output = {"relevant": True, "entries": results}
    analysis_file.write_text(json.dumps(output, indent=2))
    print(f"Analyzed {folder.name}: {len(results)} entries")


def analyze_directory(downloads_dir: Path) -> None:
    for child in sorted(downloads_dir.iterdir()):
        if child.is_dir() and child.name.startswith("reel_"):
            analyze_reel(child)


def run(downloads_dir: str = "downloads") -> None:
    analyze_directory(Path(downloads_dir))


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze downloaded reels")
    parser.add_argument(
        "downloads_dir",
        nargs="?",
        default="downloads",
        help="Path to the downloads directory",
    )
    args = parser.parse_args()
    run(args.downloads_dir)


if __name__ == "__main__":
    main()
