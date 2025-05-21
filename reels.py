#!/usr/bin/env python3
"""Unified CLI for scraping and analyzing Instagram reels."""
from __future__ import annotations

import argparse
import multiprocessing
from pathlib import Path

import reel_scraper
import analyze_reels
import consolidate_messages
import reset_analysis
import json_to_csv
import categorize_entries
import aggregate_entries


def cmd_download(args: argparse.Namespace) -> None:
    reel_scraper.run(args.message_file, args.output_dir)


def cmd_analyze(args: argparse.Namespace) -> None:
    analyze_reels.run(args.downloads_dir)


def cmd_consolidate(args: argparse.Namespace) -> None:
    consolidate_messages.run(args.output, args.inputs)


def cmd_reset(args: argparse.Namespace) -> None:
    reset_analysis.run(args.downloads_dir)


def cmd_json_to_csv(args: argparse.Namespace) -> None:
    json_to_csv.run(args.json_file, args.output)


def cmd_categorize(args: argparse.Namespace) -> None:
    categorize_entries.run(args.csv_file, args.out, args.workers)


def cmd_aggregate(args: argparse.Namespace) -> None:
    aggregate_entries.run()



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Tools for downloading and analyzing Instagram reels"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_download = sub.add_parser("download", help="Download reels from messages")
    p_download.add_argument("message_file", help="Consolidated messages JSON")
    p_download.add_argument(
        "output_dir", nargs="?", default="downloads", help="Folder for downloads"
    )
    p_download.set_defaults(func=cmd_download)

    p_consolidate = sub.add_parser(
        "consolidate", help="Combine multiple Messenger JSON exports"
    )
    p_consolidate.add_argument("output", help="Output consolidated JSON file")
    p_consolidate.add_argument("inputs", nargs="+", help="Source message files")
    p_consolidate.set_defaults(func=cmd_consolidate)

    p_analyze = sub.add_parser("analyze", help="Analyze downloaded reels")
    p_analyze.add_argument(
        "downloads_dir", nargs="?", default="downloads", help="Downloads folder"
    )
    p_analyze.set_defaults(func=cmd_analyze)

    p_reset = sub.add_parser(
        "reset-analysis", help="Remove all analysis.json files from downloads"
    )
    p_reset.add_argument(
        "downloads_dir", nargs="?", default="downloads", help="Downloads folder"
    )
    p_reset.set_defaults(func=cmd_reset)

    p_categorize = sub.add_parser("categorize", help="Categorize entries in CSV")
    p_categorize.add_argument("csv_file", help="CSV with name/description cols")
    p_categorize.add_argument("-o", "--out", default=None, help="Output CSV")
    p_categorize.add_argument(
        "-w",
        "--workers",
        type=int,
        default=max(1, multiprocessing.cpu_count() // 2),
        help="Number of worker processes",
    )
    p_categorize.set_defaults(func=cmd_categorize)

    p_aggregate = sub.add_parser(
        "aggregate", help="Combine attraction JSONL shards into one file"
    )
    p_aggregate.set_defaults(func=cmd_aggregate)

    p_csv = sub.add_parser("csv", help="Convert JSON array to CSV")
    p_csv.add_argument("json_file", help="Source JSON array file")
    p_csv.add_argument("-o", "--output", help="Destination CSV path")
    p_csv.set_defaults(func=cmd_json_to_csv)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
