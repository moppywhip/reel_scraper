# Reel Scraper

A tool to download Instagram reels from Messenger chat export files.

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

## Usage

### Consolidate Message Files

If you have multiple message JSON files from Messenger exports, you can consolidate them first:

```bash
python consolidate_messages.py consolidated_messages.json message_1.json message_2.json
```

### Download Reels

To download all reels from the consolidated messages file:

```bash
./download_reels.sh
```

Or run the Python script directly:

```bash
python reel_scraper.py consolidated_messages.json downloads
```

Where:
- First argument: The input JSON message file
- Second argument (optional): The output directory (defaults to "downloads")

## How it Works

1. The script parses the Messenger JSON export file
2. It extracts all Instagram reel links
3. It uses yt-dlp to download the reels
4. The downloaded videos are saved with the format: "Video by [uploader] [id].mp4"

## Notes

- Instagram rate limits requests, so don't download too many videos at once
- Some reels may not be downloadable due to privacy settings

### Analyze Reels

Once reels are downloaded you can analyze them with Gemini 2.5 Flash:

```bash
python analyze_reels.py downloads
```

This creates an `analysis.json` file inside each `reel_<id>` folder with the
extracted entries.
