#!/usr/bin/env python3
"""Delete per-reel analysis files so that the analysis can be rerun.

By default this script looks under the ``downloads`` directory and removes any
file named ``analysis.json`` it finds (recursively), including those in the
``irrelevant`` folder. It leaves other files untouched.

Usage
-----
    python reset_analysis.py [downloads_dir]
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


def delete_analysis_files(root: Path) -> int:
    """Recursively delete all ``analysis.json`` files under *root*.

    Returns
    -------
    int
        The number of files that were deleted.
    """
    count = 0
    for path in root.rglob("analysis.json"):
        try:
            path.unlink()
            print(f"Removed {path}")
            count += 1
        except Exception as exc:
            print(f"Failed to remove {path}: {exc}", file=sys.stderr)
    return count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delete all analysis.json files so analysis can be rerun."
    )
    parser.add_argument(
        "downloads_dir",
        nargs="?",
        default="downloads",
        help="Path to the downloads directory (default: %(default)s)",
    )
    args = parser.parse_args()

    root = Path(args.downloads_dir)
    if not root.exists() or not root.is_dir():
        parser.error(f"Directory not found: {root}")

    total = delete_analysis_files(root)
    print(f"Deleted {total} analysis.json file(s).")


if __name__ == "__main__":
    main() 