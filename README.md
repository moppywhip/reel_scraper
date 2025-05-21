# Reel Scraper

A command line tool to download and analyze Instagram reels shared in Messenger chat exports.

## Setup

The project uses `uv` for environment management and package installation.

1. Install dependencies:

```bash
# Create and activate virtual environment
uv venv
source .venv/bin/activate

# Install required packages
uv pip install -r requirements.txt
```

When your uv virtual environment is active, run the CLI like so:

```bash
uv python reels.py <command>
```

## Usage

### Consolidate Message Files

Combine multiple Messenger export files into one JSON:

```bash
python reels.py consolidate consolidated.json messages/*.json
```

### Download Reels

Download all reels referenced in your consolidated messages file:

```bash
python reels.py download consolidated.json downloads
```

## How it Works

1. The script parses the Messenger JSON export file
2. It extracts all Instagram reel links
3. It uses yt-dlp to download the reels
4. The downloaded videos are saved with the format: "Video by [uploader] [id].mp4"

## Notes

- Instagram rate limits requests, so don't download too many videos at once
- Some reels may not be downloadable due to privacy settings

### Analyze Reels

After downloading, analyze the reels with Gemini:

```bash
python reels.py analyze downloads
```

Each `reel_<id>` folder will contain an `analysis.json` file with the extracted entries.

### Other Commands

``reels.py`` also exposes a few helper subcommands:

- ``categorize`` – label attractions in a CSV file using Gemini
- ``aggregate`` – merge attraction JSONL shards into one file
- ``csv`` – convert a JSON array of objects to CSV
- ``reset-analysis`` – remove all ``analysis.json`` files so analysis can be rerun
