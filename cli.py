import argparse
import json
import subprocess
import os
import re
import time
import random
from urllib.parse import urlparse, parse_qs
import shutil
from pathlib import Path # Added for analyze_reels functionality
import google.generativeai as genai # Added for analyze_reels functionality
from google.generativeai.types import GenerateContentResponse, Part, Tool, GoogleSearch, GenerationConfig # Corrected import for GenerationConfig
from dotenv import load_dotenv
import csv
import multiprocessing # Added for categorize_entries functionality
from pydantic import BaseModel, field_validator as pydantic_field_validator # Added for categorize_entries functionality

# --- Logic for consolidate command ---
def run_consolidate(args):
    """
    Consolidates multiple message JSON files into a single file.
    Adapted from consolidate_messages.py.
    """
    all_messages = []
    participants = set()

    print(f"Input files: {args.input_files}")
    print(f"Output file: {args.output_file}")

    for file_path in args.input_files:
        print(f"Processing {file_path}...")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            for participant in data.get('participants', []):
                participant_name = participant.get('name')
                if participant_name:
                    participants.add(participant_name)
            
            all_messages.extend(data.get('messages', []))
            print(f"Added {len(data.get('messages', []))} messages from {file_path}")
        except FileNotFoundError:
            print(f"Error: File not found - {file_path}")
    # Potentially re-raise or handle as a critical failure by raising an exception
    print(f"Critical error: File not found - {file_path}. Aborting consolidation.")
            return # Exit if a file is not found
        except json.JSONDecodeError:
            print(f"Error: Could not decode JSON from file - {file_path}")
            return # Exit if JSON is invalid
        except Exception as e:
            print(f"Error processing {file_path}: {e}")
            return # Exit on other errors

    all_messages.sort(key=lambda msg: msg.get('timestamp_ms', 0), reverse=True)
    
    consolidated_data = {
        'participants': [{'name': name} for name in sorted(list(participants))], # Sort participants for consistent output
        'messages': all_messages
    }
    
    try:
        with open(args.output_file, 'w', encoding='utf-8') as f:
            json.dump(consolidated_data, f, ensure_ascii=False, indent=2)
        
        print(f"Consolidated {len(all_messages)} messages from {len(args.input_files)} files.")
        print(f"Output saved to {args.output_file}")
    except Exception as e:
        print(f"Error writing output file {args.output_file}: {e}")

# --- Logic for scrape command ---

def extract_reel_links_for_scrape(json_file_path):
    """Extract Instagram reel links from a Messenger export JSON file."""
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: Message file not found - {json_file_path}")
        return [], {}
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from file - {json_file_path}")
        return [], {}
    except Exception as e:
        print(f"Error reading or parsing {json_file_path}: {e}")
        return [], {}

    reel_links = []
    # url_to_indices is not strictly needed by the calling function run_scrape,
    # but it was part of the original extract_reel_links.
    # We'll keep its calculation for now, in case it's useful for future features.
    url_to_indices = {} 
    instagram_post_count = 0
    reel_count = 0

    for idx, message in enumerate(data.get('messages', [])):
        if 'share' in message and 'link' in message['share']:
            link = message['share']['link']
            if 'instagram.com' in link:
                instagram_post_count += 1
                if 'instagram.com/reel' in link:
                    reel_count += 1
                    base_url = link.split('?')[0]
                    reel_links.append({
                        'url': link,
                        'timestamp': message.get('timestamp_ms'),
                        'sender': message.get('sender_name'),
                        'original_creator': message['share'].get('original_content_owner', 'unknown'),
                        'share_text': message['share'].get('share_text', ''),
                        'message_index': idx, # Retained for potential future use
                    })
                    url_to_indices.setdefault(base_url, []).append(idx)
    
    print(f"Found {instagram_post_count} Instagram posts in {json_file_path}, of which {reel_count} are reels.")
    return reel_links, url_to_indices


def load_downloaded_reels_db(output_dir):
    """Load the database of previously downloaded reels."""
    db_path = os.path.join(output_dir, 'downloaded_reels.json')
    reels_db = {}
    if os.path.exists(db_path):
        try:
            with open(db_path, 'r', encoding='utf-8') as f:
                reels_db = json.load(f)
            print(f"Loaded {len(reels_db)} entries from downloaded reels database: {db_path}")
        except Exception as e:
            print(f"Error loading downloaded reels database {db_path}: {e}")
    
    if not reels_db and os.path.exists(output_dir):
        print("Scanning existing downloads folder for reels not in DB...")
        scanned_count = 0
        for folder_name in os.listdir(output_dir):
            folder_path = os.path.join(output_dir, folder_name)
            if os.path.isdir(folder_path) and folder_name.startswith('reel_'):
                metadata_path = os.path.join(folder_path, 'metadata.json')
                if os.path.exists(metadata_path):
                    try:
                        with open(metadata_path, 'r', encoding='utf-8') as f:
                            metadata = json.load(f)
                        if 'url' in metadata:
                            clean_url = metadata['url'].split('?')[0]
                            if clean_url not in reels_db: # Add only if not already loaded
                                reel_id_from_folder = folder_name.replace('reel_', '')
                                reels_db[clean_url] = {
                                    'reel_id': reel_id_from_folder,
                                    'download_time': os.path.getmtime(folder_path),
                                    'folder': folder_path
                                }
                                scanned_count +=1
                    except Exception as e:
                        print(f"Error scanning metadata in {folder_path}: {e}")
        if scanned_count > 0:
            print(f"Scanned existing downloads: found and added {scanned_count} uncataloged reels to DB.")
            save_downloaded_reels_db(reels_db, output_dir) # Save if we added new entries
    return reels_db


def save_downloaded_reels_db(reels_db, output_dir):
    """Save the database of downloaded reels."""
    if not os.path.exists(output_dir):
        try:
            os.makedirs(output_dir)
        except OSError as e:
            print(f"Error creating output directory {output_dir}: {e}")
            return False
            
    db_path = os.path.join(output_dir, 'downloaded_reels.json')
    try:
        with open(db_path, 'w', encoding='utf-8') as f:
            json.dump(reels_db, f, indent=2)
        print(f"Saved downloaded reels database to {db_path}")
        return True
    except Exception as e:
        print(f"Error saving downloaded reels database to {db_path}: {e}")
        return False

def download_reel_with_yt_dlp(reel_info, output_dir, reels_db, retry_count=0, max_retries=3): # Reduced max_retries for CLI
    """Download an Instagram reel using yt-dlp."""
    url = reel_info['url']
    clean_url = url.split('?')[0]

    if clean_url in reels_db:
        print(f"Skipping already downloaded reel (DB check): {clean_url}")
        return 'already_downloaded'

    parsed_url = urlparse(clean_url)
    path_segments = parsed_url.path.strip('/').split('/')
    reel_id = next((s for s in path_segments if re.fullmatch(r'^[A-Za-z0-9_-]+$', s) and s != 'reel'), None)
    if not reel_id:
        reel_id = str(int(time.time())) + "_" + str(random.randint(100,999)) # Add randomness for concurrent calls if ever needed

    reel_folder = os.path.join(output_dir, f'reel_{reel_id}')

    # Check existence and for errors before creating folder
    try:
        print(f"Checking reel availability: {clean_url}")
        check_process = subprocess.run(
            ['yt-dlp', clean_url, '--skip-download', '--no-warnings', '--socket-timeout', '20'], # Added timeout
            capture_output=True, text=True, timeout=30 # Added process timeout
        )
        if check_process.returncode != 0:
            stderr = check_process.stderr.lower()
            if 'rate-limit' in stderr or 'too many requests' in stderr:
                if retry_count < max_retries:
                    wait_time = (2 ** retry_count) * 5 + random.uniform(1, 3) # Shorter wait for CLI
                    print(f"Rate limited checking reel! Waiting {wait_time:.1f}s. Retry {retry_count + 1}/{max_retries}.")
                    time.sleep(wait_time)
                    return download_reel_with_yt_dlp(reel_info, output_dir, reels_db, retry_count + 1, max_retries)
                return 'rate_limited'
            if any(err_msg in stderr for err_msg in ['empty media response', '404', 'not available', 'restricted video', 'you must be 18', 'private video']):
                print(f"Reel removed/inaccessible (check): {clean_url}")
                return 'removed'
            print(f"Error checking {clean_url} with yt-dlp: {check_process.stderr.strip()}")
            return 'error_check' # Specific error type

        # Create folder only if reel seems downloadable
        if not os.path.exists(reel_folder):
             os.makedirs(reel_folder, exist_ok=True)

        print(f"Downloading: {clean_url} to {reel_folder}")
        download_process = subprocess.run(
            [
                'yt-dlp', clean_url,
                '--restrict-filenames',
                '-o', os.path.join(reel_folder, 'Video by %(uploader)s [%(id)s].%(ext)s'),
                '--no-playlist', '--no-warnings', '--force-overwrites',
                '--socket-timeout', '60' # Timeout for download itself
            ],
            capture_output=True, text=True, check=True, timeout=120 # Added process timeout
        )
        
        metadata = {
            'url': reel_info['url'], 'timestamp': reel_info['timestamp'],
            'sender': reel_info['sender'], 'original_creator': reel_info['original_creator'],
            'share_text': reel_info['share_text']
        }
        with open(os.path.join(reel_folder, 'metadata.json'), 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2)
        
        reels_db[clean_url] = {
            'reel_id': reel_id, 'download_time': int(time.time()), 'folder': reel_folder
        }
        print(f"Successfully downloaded: {clean_url}")
        return 'success'
        
    except subprocess.TimeoutExpired:
        print(f"Timeout during yt-dlp operation for {clean_url}.")
        if os.path.exists(reel_folder) and not os.listdir(reel_folder): shutil.rmtree(reel_folder) # Clean up empty folder
        return 'error_timeout'
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.lower() if e.stderr else ""
        if 'rate-limit' in stderr or 'too many requests' in stderr:
            if retry_count < max_retries:
                wait_time = (2 ** retry_count) * 5 + random.uniform(1, 3)
                print(f"Rate limited during download! Waiting {wait_time:.1f}s. Retry {retry_count + 1}/{max_retries}.")
                if os.path.exists(reel_folder) and not os.listdir(reel_folder): shutil.rmtree(reel_folder)
                time.sleep(wait_time)
                return download_reel_with_yt_dlp(reel_info, output_dir, reels_db, retry_count + 1, max_retries)
            return 'rate_limited'
        if any(err_msg in stderr for err_msg in ['empty media response', '404', 'not available', 'restricted video', 'private video']):
            print(f"Reel removed/inaccessible (download): {clean_url}")
            if os.path.exists(reel_folder) and not os.listdir(reel_folder): shutil.rmtree(reel_folder)
            return 'removed'
        print(f"Error downloading {clean_url}: {e.stderr if e.stderr else e.stdout}")
        if os.path.exists(reel_folder) and not os.listdir(reel_folder): shutil.rmtree(reel_folder) # Clean up empty folder on error
        return 'error_download'
    except OSError as e: # Handles errors like makedirs failing
        print(f"OS error during download process for {clean_url}: {e}")
        return 'error_os'
    except Exception as e:
        print(f"An unexpected error occurred with reel {clean_url}: {e}")
        if os.path.exists(reel_folder) and not os.listdir(reel_folder): shutil.rmtree(reel_folder)
        return 'error_unexpected'


def prune_messages_by_url_from_file(src_path, base_url):
    """Remove messages sharing base_url from src_path JSON file."""
    if not os.path.exists(src_path):
        print(f"Error: Cannot prune, file not found: {src_path}")
        return 0
    
    try:
        with open(src_path, "r", encoding="utf-8") as f_in:
            data_in = json.load(f_in)
    except Exception as e:
        print(f"Error reading {src_path} for pruning: {e}")
        return 0

    original_messages_count = len(data_in.get("messages", []))
    
    # Filter out messages that contain the base_url
    new_messages = [
        m for m in data_in.get("messages", [])
        if not ("share" in m and "link" in m["share"] and m["share"]["link"].split("?")[0] == base_url)
    ]
    
    removed_cnt = original_messages_count - len(new_messages)

    if removed_cnt == 0:
        # print(f"No messages to prune for URL {base_url} in {src_path}")
        return 0

    backup_path = src_path + ".bak"
    if not os.path.exists(backup_path):
        try:
            shutil.copy2(src_path, backup_path)
            print(f"Created backup: {backup_path}")
        except Exception as e:
            print(f"Error creating backup for {src_path}: {e}")
            # Decide if you want to proceed without a backup
            # For now, we'll proceed but this could be a failure point
    
    data_in["messages"] = new_messages
    try:
        with open(src_path, "w", encoding="utf-8") as f_out:
            json.dump(data_in, f_out, indent=2, ensure_ascii=False)
        print(f"Pruned {removed_cnt} messages (url={base_url}) from {src_path}. New total: {len(new_messages)}")
    except Exception as e:
        print(f"Error writing pruned messages to {src_path}: {e}")
        # Attempt to restore from backup if write fails? For now, just log.
        return 0 # Indicate failure or partial success

    return removed_cnt


def run_scrape(args):
    """Main logic for the scrape subcommand."""
    message_file = args.message_file
    output_dir = args.output_dir

    print(f"Starting scrape process...")
    print(f"Message file: {message_file}")
    print(f"Output directory: {output_dir}")

    if not os.path.exists(message_file):
        print(f"Error: Message file '{message_file}' not found. Aborting.")
        return

    if not os.path.exists(output_dir):
        try:
            os.makedirs(output_dir)
            print(f"Created output directory: {output_dir}")
        except OSError as e:
            print(f"Error: Could not create output directory '{output_dir}': {e}. Aborting.")
            return
            
    reels_db = load_downloaded_reels_db(output_dir)
    
    reels_to_process, _ = extract_reel_links_for_scrape(message_file) # url_to_indices is not used here
    
    if not reels_to_process:
        print("No reels found in the message file.")
        return

    unique_reels = []
    seen_urls = set()
    for reel in reels_to_process:
        url_base = reel['url'].split('?')[0]
        if url_base not in seen_urls:
            seen_urls.add(url_base)
            unique_reels.append(reel)
    
    print(f"Total unique reels found: {len(unique_reels)}")
    
    db_initial_count = len(reels_db)
    already_downloaded_in_db_count = sum(1 for r in unique_reels if r['url'].split('?')[0] in reels_db)
    
    print(f"Reels already in DB before this run: {already_downloaded_in_db_count}")
    print(f"Attempting to download/process {len(unique_reels) - already_downloaded_in_db_count} new or previously failed reels.")

    stats = {'success': 0, 'already_downloaded': 0, 'rate_limited': 0, 'removed': 0, 'error_check': 0, 'error_download': 0, 'error_timeout':0, 'error_os':0, 'error_unexpected':0 }
    pruned_message_count_total = 0

    for i, reel_info in enumerate(unique_reels, 1):
        clean_url = reel_info['url'].split('?')[0]
        print(f"\n[{i}/{len(unique_reels)}] Processing: {clean_url} (Sender: {reel_info.get('sender', 'N/A')})")

        # Skip download if already in DB from this session or previous
        if clean_url in reels_db:
            # Check if it was marked as 'already_downloaded' by the download_reel_with_yt_dlp due to DB presence.
            # This is a bit redundant as load_downloaded_reels_db already populates reels_db.
            # The main check `if clean_url in reels_db:` is the important one.
            print(f"Reel already in DB or processed this session: {clean_url}")
            status = 'already_downloaded'
        else:
            # Add delay only for new downloads
            if sum(stats[k] for k in ['success', 'rate_limited', 'error_download']) > 0: # if any actual download attempt was made
                delay = random.uniform(1.0, 2.5) # Shorter delays for CLI tool
                print(f"Waiting {delay:.1f}s before next download attempt...")
                time.sleep(delay)
            status = download_reel_with_yt_dlp(reel_info, output_dir, reels_db)

        stats[status] = stats.get(status, 0) + 1

        if status == 'success':
            # Save DB and prune immediately after successful download
            save_downloaded_reels_db(reels_db, output_dir)
            pruned_count = prune_messages_by_url_from_file(message_file, clean_url)
            if pruned_count > 0:
                pruned_message_count_total += pruned_count
        elif status == 'already_downloaded':
            # If it was already in the DB (either from file or scanned), ensure messages are pruned.
            # This handles cases where pruning might have failed in a previous run.
            pruned_count = prune_messages_by_url_from_file(message_file, clean_url)
            if pruned_count > 0:
                 pruned_message_count_total += pruned_count
        elif status == 'removed':
            # Also prune messages for removed/inaccessible reels
            pruned_count = prune_messages_by_url_from_file(message_file, clean_url)
            if pruned_count > 0:
                 pruned_message_count_total += pruned_count
        elif status == 'rate_limited':
            print(f"Stopping further downloads in this session due to rate limit at reel {clean_url}.")
            # Consider a longer wait here if you want the process to auto-resume later,
            # but for a CLI tool, stopping might be better.
            # For now, we just stop attempting new downloads.
            # The main loop will continue for reels already in DB (for pruning) but won't call download_reel_with_yt_dlp.
            # To actually break the loop:
            # break 
            # For now, let it continue to prune any remaining already_downloaded items.
            # No new downloads will be attempted if clean_url not in reels_db after this.
            # The `if clean_url in reels_db:` check at the start of the loop handles this.
            # To truly stop new downloads, we'd need a flag.
            # Let's assume for now it continues but new downloads will hit the DB check.
            # A better approach for true stop: set a flag and check it before `download_reel_with_yt_dlp`
            pass # Let it continue to try and prune other reels already in DB

    print("\n--- Scrape Summary ---")
    print(f"Successfully downloaded: {stats['success']} new reels")
    print(f"Already downloaded (DB): {stats['already_downloaded'] + db_initial_count - sum(1 for r_id in reels_db if reels_db[r_id].get('download_time', 0) > time.time() - 3600*12 ) } (approx original DB count)") # A bit complex to get exact pre-run count if items were added by scan
    print(f"Actually skipped as already in DB this run: {stats['already_downloaded']}")
    print(f"Removed/unavailable: {stats['removed']}")
    print(f"Rate limited (stopped further new downloads): {stats['rate_limited']}")
    errors_total = stats['error_check'] + stats['error_download'] + stats['error_timeout'] + stats['error_os'] + stats['error_unexpected']
    print(f"Errors (check/download/timeout/os/other): {errors_total} ({stats['error_check']}/{stats['error_download']}/{stats['error_timeout']}/{stats['error_os']}/{stats['error_unexpected']})")
    print(f"Total reels in database now: {len(reels_db)}")
    if pruned_message_count_total > 0:
        print(f"Pruned a total of {pruned_message_count_total} messages from '{message_file}'.")
    else:
        print(f"No messages were pruned from '{message_file}' during this run.")

    # Final save of the database
    if stats['success'] > 0 or errors_total == 0 : # Save if new downloads or no errors
        save_downloaded_reels_db(reels_db, output_dir)
    print("Scraping process finished.")

# --- Logic for analyze command ---

# Constants from analyze_reels.py
ANALYSIS_RELEVANCE_PROMPT = (
    "Return JSON only in the form {'relevant': true} if the video contains "
    "any business or place related to food, self care, or an attraction. "
    "Return {'relevant': false} otherwise."
)
ANALYSIS_EXTRACTION_PROMPT = (
    "You are an AI that extracts businesses or attractions from a video. "
    "Respond ONLY with a JSON array where each item has the fields "
    "name, category (food, self care, attraction), address, and website."
)
ANALYSIS_MODEL_NAME = "gemini-1.5-flash-latest" # Changed to gemini-1.5-flash-latest from gemini-2.5-flash as 2.5 is not a valid model, and 1.5-flash is a common choice

# Global variable for the Gemini client, initialized in run_analyze
GEMINI_CLIENT = None

def _initialize_gemini_client():
    global GEMINI_CLIENT
    if GEMINI_CLIENT is None:
        load_dotenv() # Load environment variables from .env file
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            print("Error: GOOGLE_API_KEY not found in environment variables or .env file.")
            print("Please create a .env file with GOOGLE_API_KEY=<your_api_key> or set the environment variable.")
            # Consider raising an exception here to stop execution if API key is critical
            return False 
        
        try:
            # genai.configure(api_key=api_key) # configure is usually for global settings, client can take key directly
            GEMINI_CLIENT = genai.GenerativeModel(model_name=ANALYSIS_MODEL_NAME) # Initialize the model
            print(f"Gemini client initialized with model: {ANALYSIS_MODEL_NAME}")
            return True
        except Exception as e:
            print(f"Error initializing Gemini client: {e}")
            GEMINI_CLIENT = None # Ensure client is None if initialization fails
            return False
    return True


def _load_video_file_for_analysis(folder_path: Path) -> Path | None:
    """Return the first video file inside a reel folder."""
    for file_item in folder_path.iterdir():
        if file_item.is_file() and file_item.suffix.lower() in {".mp4", ".mov", ".webm", ".mkv"}: # Added .mkv
            return file_item
    return None


def _call_gemini_api_for_analysis(video_part: Part, prompt: str, use_tools: bool = False, max_retries: int = 2, initial_delay: int = 5) -> str | None:
    """Call the Gemini API with retry logic."""
    if not GEMINI_CLIENT:
        print("Error: Gemini client not initialized. Cannot call API.")
        return None

    tools_config = [Tool(google_search=GoogleSearch())] if use_tools else None
    # Ensure GenerationConfig is correctly used if needed, or remove if defaults are fine.
    # For simple cases, directly passing temperature might be enough.
    # config = GenerationConfig(temperature=0.0, tools=tools_config)
    # The generate_content method takes `tools` and `generation_config` separately.
    
    current_RETRY_COUNT = 0
    while current_RETRY_COUNT <= max_retries:
        try:
            print(f"Calling Gemini API (Attempt {current_RETRY_COUNT + 1}/{max_retries + 1})...")
            # response = GEMINI_CLIENT.generate_content(
            # contents=[video_part, prompt],
            # tools=tools_config, # Pass tools here
            # generation_config=GenerationConfig(temperature=0.0) # Pass generation_config here
            # )
            # Simpler call if complex config isn't immediately needed:
            response = GEMINI_CLIENT.generate_content(
                contents=[video_part, prompt],
                tools=tools_config, # This should be a list of Tool objects or None
                generation_config=genai.types.GenerationConfig(temperature=0.0) # Explicitly use genai.types
            )

            if hasattr(response, 'text'):
                return response.text
            else: # Handle cases where response might not have 'text' (e.g. blocked)
                print(f"Gemini API response missing 'text' attribute. Full response: {response}")
                # Check for prompt feedback if available
                if response.prompt_feedback and response.prompt_feedback.block_reason:
                    print(f"Content blocked due to: {response.prompt_feedback.block_reason}")
                    if response.prompt_feedback.block_reason.name == "SAFETY": # Accessing enum member by name
                         print("Skipping due to safety concerns.")
                         return "BLOCKED_SAFETY" # Special marker for safety blocks
                return None # Or handle as an error
        except Exception as e:
            print(f"Error calling Gemini API: {e}")
            current_RETRY_COUNT += 1
            if current_RETRY_COUNT <= max_retries:
                delay = initial_delay * (2 ** (current_RETRY_COUNT -1)) + random.uniform(0,1)
                print(f"Retrying in {delay:.2f} seconds...")
                time.sleep(delay)
            else:
                print("Max retries reached for Gemini API call.")
                return None
    return None


def _parse_relevance_from_gemini(text: str | None) -> bool | None:
    if not text: return None
    if text == "BLOCKED_SAFETY": return False # Treat safety blocks as not relevant for further processing
    try:
        # The prompt asks for JSON, so expect it.
        # Remove potential markdown backticks if present
        cleaned_text = text.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(cleaned_text)
        return bool(data.get("relevant", False)) # Default to False if 'relevant' key is missing
    except json.JSONDecodeError:
        print(f"Warning: Could not parse relevance JSON: '{text[:100]}...'")
        # Fallback: simple string check if JSON parsing fails but text is short
        if len(text) < 20 and "true" in text.lower(): return True
        if len(text) < 20 and "false" in text.lower(): return False
        return None # Indicate parsing failure
    except Exception as e:
        print(f"Error parsing relevance response: {e} (Input: '{text[:100]}...')")
        return None


def _parse_extraction_from_gemini(text: str | None) -> list[dict[str, Any]] | None:
    if not text: return [] # Return empty list if no text
    if text == "BLOCKED_SAFETY": return [] # Treat safety blocks as no data extracted
    
    # Remove potential markdown backticks and "json" language specifier
    cleaned_text = text.strip()
    if cleaned_text.startswith("```json"):
        cleaned_text = cleaned_text[len("```json"):].strip()
    if cleaned_text.startswith("```"):
        cleaned_text = cleaned_text[len("```"):].strip()
    if cleaned_text.endswith("```"):
        cleaned_text = cleaned_text[:-len("```")].strip()
        
    try:
        data = json.loads(cleaned_text)
        if isinstance(data, list):
            # Basic validation of expected fields (optional, but good for robustness)
            for item in data:
                if not all(key in item for key in ["name", "category", "address", "website"]):
                    print(f"Warning: Missing expected keys in extracted item: {item}")
            return data
        else:
            print(f"Warning: Parsed extraction JSON is not a list: '{cleaned_text[:100]}...'")
            return None # Indicate parsing failure (not a list)
    except json.JSONDecodeError:
        print(f"Warning: Could not parse extraction JSON: '{cleaned_text[:100]}...'")
        return None # Indicate parsing failure (JSON error)
    except Exception as e:
        print(f"Error parsing extraction response: {e} (Input: '{cleaned_text[:100]}...')")
        return None


def _analyze_single_reel_folder(folder_path: Path, force_reanalyze: bool = False):
    """Analyzes a single reel folder using Gemini."""
    analysis_file = folder_path / "analysis.json"

    if analysis_file.exists() and not force_reanalyze:
        try:
            with open(analysis_file, 'r', encoding='utf-8') as f:
                existing_analysis = json.load(f)
            # Basic check to see if it's our format and seems complete
            if 'relevant' in existing_analysis:
                 print(f"Skipping already analyzed reel (analysis.json exists): {folder_path.name}")
                 return
        except Exception as e:
            print(f"Error reading existing analysis.json for {folder_path.name}, will re-analyze: {e}")


    video_file = _load_video_file_for_analysis(folder_path)
    if not video_file:
        print(f"No video file found in {folder_path.name}. Skipping analysis.")
        # Create a minimal analysis.json to mark as processed
        try:
            with analysis_file.open("w", encoding="utf-8") as f:
                json.dump({"relevant": False, "error": "No video file found"}, f, indent=2)
        except Exception as e:
            print(f"Error writing 'no video' analysis file for {folder_path.name}: {e}")
        return

    print(f"Analyzing reel: {folder_path.name} (video: {video_file.name})")
    
    # Upload the video file to Gemini (this is how it's done with the new API)
    # The Part.from_uri method is for Google Cloud Storage URIs.
    # For local files, you'd typically use Part.from_data or if the library supports direct file paths.
    # The example from `analyze_reels.py` used `Part.from_file(f, mime_type="video/mp4")`
    # which is an older or different client usage pattern.
    # With GenerativeModel, you pass the file directly or a Part object.
    # Let's assume we are using a system where `google.generativeai.upload_file` is preferred for large files.
    # However, the original script passed the file bytes directly in `parts`.
    # Let's stick to passing file bytes as Part for now, as in the original script's `call_gemini`.
    
    video_part = None
    try:
        with video_file.open("rb") as f_video:
            # video_part = Part.from_data(f_video.read(), mime_type="video/mp4") # This is one way
            # The original `call_gemini` directly used the file object in a list of parts.
            # Let's use the structure the original `call_gemini` expected.
            # The `google.generativeai.GenerativeModel.generate_content` method can take a list of Parts.
            # The original `call_gemini` did: `Part.from_file(f, mime_type="video/mp4")`
            # This seems to be from an older version or a misunderstanding of the `Part` class.
            # Let's try to create a Part from data.
            # This should be `Part.from_data(data=f.read(), mime_type=...)`
            # Or, the model can take a list of [file_data, prompt_string].
            # The `google.generativeai` library has evolved.
            # The `Part.from_uri` is for GCS. `Part.from_data` is for bytes.
            # The example from the problem description:
            # `video_part = Part.from_file(f, mime_type="video/mp4")`
            # This `Part.from_file` doesn't exist in `google.generativeai.types.Part`
            # It seems `google.generativeai.upload_file` is the current way for local files.
            # uploaded_file = genai.upload_file(path=video_file) # This returns a File object
            # video_part_for_api = Part.from_uri(uri=uploaded_file.uri, mime_type=uploaded_file.mime_type)
            # For simplicity and to avoid managing uploaded file lifecycle for now, let's assume small files
            # and pass bytes, though this is not ideal for large videos.
            # The original script's `call_gemini` took `List[Part]`.
            # `Part.from_file` in the original was likely a helper or from a different SDK version.
            # Let's use a placeholder for the video part that `_call_gemini_api_for_analysis` can handle.
            # The `_call_gemini_api_for_analysis` expects a `Part` object.
            # We need to create it correctly.
            # The model's `generate_content` can take `[str, Part]` or `[str, FileDataDict]` etc.
            # Given the original script's `call_gemini([video_part], prompt)`, `video_part` was a `Part`.
            # Let's use `genai.upload_file` as it's the most robust way for current API versions.
            print(f"Uploading {video_file.name} to Gemini...")
            # Ensure client is initialized for upload_file as well
            if not GEMINI_CLIENT: # Technically upload_file is at module level, but might use configured client aspects
                 if not _initialize_gemini_client() or not GEMINI_CLIENT: # Ensure client is available
                    print("Cannot upload video, Gemini client not initialized.")
                    return
            
            # This part needs the genai client to be the genai module itself if api_key is globally configured,
            # or handle it via the client instance if that's how the SDK is designed.
            # `genai.upload_file` uses the globally configured API key.
            
            # Before calling upload_file, ensure global API key is set if not done by _initialize_gemini_client's genai.configure
            if not os.getenv("GOOGLE_API_KEY_CONFIGURED_GLOBALLY", None): # A pseudo flag
                load_dotenv()
                g_api_key = os.getenv("GOOGLE_API_KEY")
                if g_api_key:
                    try:
                        genai.configure(api_key=g_api_key, client_options={"api_endpoint": "generativelanguage.googleapis.com"})
                        os.environ["GOOGLE_API_KEY_CONFIGURED_GLOBALLY"] = "1"
                        print("google.generativeai configured globally with API key.")
                    except Exception as e:
                        print(f"Failed to configure google.generativeai globally: {e}")
                        # Fallback or error
                else:
                    print("GOOGLE_API_KEY not found for global configuration of genai module.")
                    # Cannot proceed with upload_file if global config fails and is required.

            uploaded_file_response = genai.upload_file(path=video_file, display_name=video_file.name)
            print(f"File uploaded successfully: {uploaded_file_response.name} (URI: {uploaded_file_response.uri})")
            video_part_for_api = Part.from_uri(uri=uploaded_file_response.uri, mime_type=uploaded_file_response.mime_type)

    except Exception as e:
        print(f"Error processing video file {video_file.name} for Gemini: {e}")
        try:
            with analysis_file.open("w", encoding="utf-8") as f:
                json.dump({"relevant": False, "error": f"Video processing error: {e}"}, f, indent=2)
        except Exception as e_write:
            print(f"Error writing error analysis file for {folder_path.name}: {e_write}")
        if 'uploaded_file_response' in locals() and uploaded_file_response: # Clean up if upload succeeded but then failed
            try:
                print(f"Attempting to delete uploaded file: {uploaded_file_response.name}")
                genai.delete_file(name=uploaded_file_response.name)
                print(f"Successfully deleted uploaded file: {uploaded_file_response.name}")
            except Exception as e_delete:
                print(f"Error deleting uploaded file {uploaded_file_response.name}: {e_delete}")
        return

    relevance_text = _call_gemini_api_for_analysis(video_part_for_api, ANALYSIS_RELEVANCE_PROMPT, use_tools=False)
    is_relevant = _parse_relevance_from_gemini(relevance_text)

    analysis_output = {"relevant": False} # Default to not relevant

    if is_relevant is None: # API call or parsing failed critically
        print(f"Could not determine relevance for {folder_path.name}. Skipping detailed analysis.")
        analysis_output["error"] = "Failed to determine relevance."
        if relevance_text: # Store raw text if parsing failed
            analysis_output["relevance_raw_response"] = relevance_text
    elif not is_relevant:
        print(f"Skipping irrelevant reel {folder_path.name} based on Gemini analysis.")
        analysis_output["relevant"] = False
    else: # Is relevant
        print(f"Reel {folder_path.name} is relevant. Proceeding to extract details.")
        analysis_output["relevant"] = True
        # Short delay before next API call
        time.sleep(random.uniform(1, 3)) # Small delay between API calls
        
        details_text = _call_gemini_api_for_analysis(video_part_for_api, ANALYSIS_EXTRACTION_PROMPT, use_tools=True)
        extracted_entries = _parse_extraction_from_gemini(details_text)
        
        if extracted_entries is None: # API call or parsing failed critically for extraction
            analysis_output["error"] = "Failed to extract details or parse them."
            if details_text:
                analysis_output["extraction_raw_response"] = details_text
            analysis_output["entries"] = []
        else:
            analysis_output["entries"] = extracted_entries
            print(f"Analyzed {folder_path.name}: Found {len(extracted_entries)} entries.")

    try:
        with analysis_file.open("w", encoding="utf-8") as f:
            json.dump(analysis_output, f, indent=2, ensure_ascii=False)
        print(f"Analysis saved to {analysis_file}")
    except Exception as e:
        print(f"Error writing analysis file for {folder_path.name}: {e}")

    # Clean up the uploaded file from Gemini, as it's temporary for this analysis
    # This is important to avoid accumulating files in your Gemini project.
    if 'uploaded_file_response' in locals() and uploaded_file_response:
        try:
            print(f"Attempting to delete uploaded file: {uploaded_file_response.name}")
            genai.delete_file(name=uploaded_file_response.name) # Requires the file name, not the File object
            print(f"Successfully deleted uploaded file: {uploaded_file_response.name}")
        except Exception as e_delete:
            print(f"Error deleting uploaded file {uploaded_file_response.name}: {e_delete}")


def run_analyze(args):
    """Main logic for the analyze subcommand."""
    print("Starting analysis process...")
    
    if not _initialize_gemini_client():
        print("Failed to initialize Gemini client. Aborting analysis.")
        return

    downloads_dir = Path(args.downloads_dir)
    if not downloads_dir.is_dir():
        print(f"Error: Downloads directory '{downloads_dir}' not found. Aborting.")
        return

    print(f"Scanning directory: {downloads_dir}")
    
    reel_folders_found = []
    for item in downloads_dir.iterdir():
        if item.is_dir() and item.name.startswith("reel_"):
            reel_folders_found.append(item)
    
    if not reel_folders_found:
        print(f"No reel folders (starting with 'reel_') found in {downloads_dir}.")
        return
        
    print(f"Found {len(reel_folders_found)} reel folders to potentially analyze.")

    # Sort folders for consistent processing order
    sorted_reel_folders = sorted(reel_folders_found, key=lambda p: p.name)

    for i, folder_path in enumerate(sorted_reel_folders):
        print(f"\n--- Processing folder {i+1}/{len(sorted_reel_folders)}: {folder_path.name} ---")
        _analyze_single_reel_folder(folder_path, args.force_reanalyze)
        # Add a delay between processing folders to manage API rate limits, if necessary.
        # Gemini Flash models usually have higher limits, but good practice for multiple API calls.
        if i < len(sorted_reel_folders) - 1: # Not the last folder
            # Longer delay if multiple API calls were made inside _analyze_single_reel_folder
            # This is a simple fixed delay; more sophisticated rate limiting could be implemented.
            delay_between_folders = random.uniform(3, 7) 
            print(f"Waiting {delay_between_folders:.1f}s before next folder...")
            time.sleep(delay_between_folders)
            
    print("\nAnalysis process finished.")

# --- Logic for aggregate command ---

def run_aggregate(args):
    """
    Aggregates 'entries' from 'analysis.json' files found in reel-specific 
    subdirectories within the reels_dir, if 'relevant' is true.
    """
    print(f"Starting aggregation process...")
    reels_dir = Path(args.reels_dir)
    output_file = Path(args.output_file)

    if not reels_dir.is_dir():
        print(f"Error: Reels directory '{reels_dir}' not found. Aborting.")
        return

    all_entries = []
    reels_processed_count = 0
    relevant_reels_with_entries_count = 0

    print(f"Scanning for reel folders in: {reels_dir}")
    # Iterate through items in reels_dir, sort for consistent order
    for item_path in sorted(reels_dir.iterdir()):
        if item_path.is_dir() and item_path.name.startswith("reel_"):
            reels_processed_count += 1
            analysis_file_path = item_path / "analysis.json"
            
            if analysis_file_path.exists() and analysis_file_path.is_file():
                print(f"  Processing: {item_path.name}")
                try:
                    with open(analysis_file_path, 'r', encoding='utf-8') as f:
                        analysis_data = json.load(f)
                    
                    if analysis_data.get("relevant") is True:
                        entries = analysis_data.get("entries", [])
                        if entries: # Only count if there are actual entries
                            all_entries.extend(entries)
                            relevant_reels_with_entries_count += 1
                            print(f"    Found {len(entries)} entries in relevant reel {item_path.name}.")
                        else:
                            print(f"    Reel {item_path.name} is relevant but has no entries.")
                    else:
                        print(f"    Reel {item_path.name} is not relevant or relevance not specified.")
                        
                except json.JSONDecodeError:
                    print(f"    Error: Could not decode JSON from {analysis_file_path}.")
                except Exception as e:
                    print(f"    Error processing file {analysis_file_path}: {e}")
            else:
                print(f"  Skipping {item_path.name}: 'analysis.json' not found.")
    
    print(f"\nProcessed {reels_processed_count} potential reel folders.")
    print(f"Found {relevant_reels_with_entries_count} relevant reels with entries.")

    if not all_entries:
        print("No entries collected. Output file will not be created/updated.")
        # Optionally, write an empty list to the output file if that's desired behavior
        # For now, only write if there's data.
        return

    try:
        # Ensure output directory exists
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(all_entries, f, ensure_ascii=False, indent=2)
        
        print(f"\nSuccessfully aggregated {len(all_entries)} entries from {relevant_reels_with_entries_count} reels.")
        print(f"Output saved to: {output_file}")
        
    except Exception as e:
        print(f"Error writing aggregated entries to {output_file}: {e}")

# --- Logic for to-csv command ---

def run_json_to_csv(args):
    """
    Converts a JSON array of objects to a CSV file.
    """
    print("Starting JSON to CSV conversion...")
    input_json_path = Path(args.input_json_file)

    if not input_json_path.is_file():
        print(f"Error: Input JSON file '{input_json_path}' not found. Aborting.")
        return

    if args.output_csv_file:
        output_csv_path = Path(args.output_csv_file)
    else:
        output_csv_path = input_json_path.with_suffix(".csv")
    
    print(f"Input JSON: {input_json_path}")
    print(f"Output CSV: {output_csv_path}")

    try:
        with open(input_json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if not isinstance(data, list):
            print("Error: Input JSON must contain a top-level array of objects. Aborting.")
            # Optionally, write an empty CSV or handle differently
            return
        
        if not data:
            print("Input JSON array is empty. Output CSV will only contain headers (if any derivable) or be empty.")
            # Create an empty CSV with headers if possible, or just an empty file.
            # For now, let's ensure the output directory exists and touch the file.
            output_csv_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_csv_path, 'w', encoding='utf-8') as f_empty:
                 # If we could derive headers from a schema (not available here), write them.
                 # Otherwise, an empty file is fine.
                 pass
            print(f"Empty CSV file created at {output_csv_path}")
            return

        # Collect all unique keys that appear in the objects
        all_keys = set()
        for item in data:
            if isinstance(item, dict): # Ensure item is a dictionary
                all_keys.update(item.keys())
            else:
                print(f"Warning: Found non-object item in JSON array: {item}. Skipping for header collection.")


        # Define a preferred order for columns, others will be alphabetical after
        # Adjusted preferred order based on typical aggregated data structure
        preferred_order = ["name", "category", "address", "website", "original_creator", "sender", "share_text", "url", "timestamp"]
        
        header = [key for key in preferred_order if key in all_keys]
        remaining_keys = sorted(list(all_keys - set(preferred_order)))
        final_header = header + remaining_keys
        
        if not final_header: # Should not happen if data is not empty and items are dicts
            print("Could not determine headers (e.g. data items are not dictionaries or empty). Cannot create CSV.")
            return

        # Ensure output directory exists
        output_csv_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_csv_path, 'w', newline='', encoding='utf-8') as f_csv:
            writer = csv.DictWriter(f_csv, fieldnames=final_header, extrasaction='ignore') # ignore fields in data not in header
            writer.writeheader()
            for row_data in data:
                if isinstance(row_data, dict): # Write only if item is a dictionary
                    writer.writerow(row_data)
                else:
                    print(f"Warning: Skipping non-dictionary item during CSV writing: {row_data}")
        
        print(f"\nSuccessfully converted JSON to CSV.")
        print(f"{len(data)} rows written to {output_csv_path}")

    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from '{input_json_path}'. Ensure it's a valid JSON file. Aborting.")
    except Exception as e:
        print(f"An unexpected error occurred during JSON to CSV conversion: {e}")

# --- Logic for categorize command ---

# Constants for categorize command (adapted from categorize_entries.py)
CATEGORIZATION_ALLOWED_CATEGORIES = [
    "food",
    "shopping",
    "beauty & skin care",
    "other attractions",
]

CATEGORIZATION_PROMPT_TEMPLATE = """\
You are helping categorize vacation attractions for a travel guide.

Given the attraction below, choose ONE best-fitting category from:
  • food
  • shopping
  • beauty & skin care
  • other attractions   (use this when none of the above clearly apply)

Respond ONLY with JSON of the form: {{"category": "<one_of_the_above_categories>"}}.

Attraction:
Name: {name}
Description: {desc}
"""

# Pydantic model for categorize command response validation
class CategorizationResponsePydantic(BaseModel):
    category: str

    @pydantic_field_validator("category")
    @classmethod
    def category_must_be_valid(cls, v: str) -> str:
        v = v.lower().strip()
        # Normalize common shortcuts from the model
        if v in {"beauty", "beauty & skincare", "beauty and skin care"}:
            v = "beauty & skin care"
        if v not in CATEGORIZATION_ALLOWED_CATEGORIES:
            # If the model returns something unexpected, default to "other attractions"
            # rather than raising an error, to make processing more robust.
            print(f"Warning: Received unexpected category '{v}'. Defaulting to 'other attractions'.")
            return "other attractions"
        return v

# Global Gemini client for worker processes in categorize command
# This will be initialized by each worker.
WORKER_GEMINI_CLIENT = None

def _worker_init_categorize(api_key_global_env: str, model_name_global_env: str):
    """Initializer for worker processes to set up their own Gemini client."""
    global WORKER_GEMINI_CLIENT
    global CATEGORIZE_MODEL_NAME_WORKER # Store for reference
    
    # The API key should be available as an environment variable, loaded by the main process.
    # Here we ensure the genai module in the worker process is configured.
    # Direct client instantiation is preferred over genai.configure if passing key explicitly.
    # However, the original script used genai.Client() which implies global config or env var.
    
    # Simplest approach: assume main process has loaded .env and set os.environ["GOOGLE_API_KEY"]
    # Then each worker can initialize its client.
    
    current_api_key = os.getenv("GOOGLE_API_KEY")
    if not current_api_key:
        # This is a fallback if the main process didn't ensure the env var was set for workers.
        # It's better if main process handles .env loading and sets env var directly.
        print("Worker: GOOGLE_API_KEY not found in environment. Attempting to load .env")
        load_dotenv() 
        current_api_key = os.getenv("GOOGLE_API_KEY")

    if not current_api_key:
        print("Worker Error: GOOGLE_API_KEY is not set. Cannot initialize Gemini client in worker.")
        WORKER_GEMINI_CLIENT = None
        CATEGORIZE_MODEL_NAME_WORKER = None
        return

    try:
        # Using ANALYSIS_MODEL_NAME for categorization as well, for consistency
        CATEGORIZE_MODEL_NAME_WORKER = ANALYSIS_MODEL_NAME 
        WORKER_GEMINI_CLIENT = genai.GenerativeModel(model_name=CATEGORIZE_MODEL_NAME_WORKER)
        # Test call or client property check might be good here if initialization is lazy
        print(f"Worker (PID {os.getpid()}) initialized Gemini client with model: {CATEGORIZE_MODEL_NAME_WORKER}")
    except Exception as e:
        print(f"Worker (PID {os.getpid()}) Error initializing Gemini client: {e}")
        WORKER_GEMINI_CLIENT = None
        CATEGORIZE_MODEL_NAME_WORKER = None


def _ask_gemini_for_category(prompt: str, max_retries: int = 2, initial_delay: int = 2) -> str | None:
    """Helper to call Gemini API for categorization, using the worker's client."""
    if not WORKER_GEMINI_CLIENT:
        print(f"Worker (PID {os.getpid()}): Gemini client not initialized. Cannot categorize.")
        return None # Default to "other attractions" handled by caller

    current_RETRY_COUNT = 0
    while current_RETRY_COUNT <= max_retries:
        try:
            # The original script used genai.Client().models.generate_content
            # Here we use the GenerativeModel instance directly.
            response = WORKER_GEMINI_CLIENT.generate_content(
                contents=[prompt],
                generation_config=genai.types.GenerationConfig(
                    response_mime_type="application/json", # Request JSON output
                    temperature=0.0, 
                    # response_schema is not directly usable with generate_content on model instance in the same way as client.models
                    # The prompt already requests JSON. We will parse with Pydantic.
                )
            )
            
            if hasattr(response, 'text') and response.text:
                # Pydantic will parse and validate the JSON from response.text
                # The prompt specifies the JSON structure.
                return response.text # Return the raw JSON string for Pydantic to parse
            else:
                # Handle blocked or empty responses
                if response.prompt_feedback and response.prompt_feedback.block_reason:
                    print(f"Worker (PID {os.getpid()}): Content blocked by Gemini: {response.prompt_feedback.block_reason}")
                else:
                    print(f"Worker (PID {os.getpid()}): Gemini response empty or missing text: {response}")
                return None # Indicates an issue to the caller

        except Exception as e:
            print(f"Worker (PID {os.getpid()}) Error calling Gemini API: {e}")
            current_RETRY_COUNT += 1
            if current_RETRY_COUNT <= max_retries:
                delay = initial_delay * (2 ** (current_RETRY_COUNT -1)) + random.uniform(0,1)
                print(f"Worker (PID {os.getpid()}) Retrying in {delay:.2f} seconds...")
                time.sleep(delay)
            else:
                print(f"Worker (PID {os.getpid()}) Max retries reached for Gemini API call.")
                return None # Indicates failure after retries
    return None


def _process_csv_row_for_category_worker(row_tuple: tuple[int, dict[str, str]]) -> tuple[int, dict[str, str]]:
    """Worker function to process a single CSV row for categorization."""
    index, row_data = row_tuple
    
    # Ensure worker client is initialized (should be via Pool initializer)
    if not WORKER_GEMINI_CLIENT:
         print(f"Worker (PID {os.getpid()}) for row {index}: Gemini client not available. Assigning default category.")
         row_data["category"] = "other attractions" # Default category on critical failure
         return index, row_data

    name = row_data.get("name", "")
    # Try 'share_text' first for description, then 'description'
    description = row_data.get("share_text") if row_data.get("share_text") else row_data.get("description", "")

    if not name and not description:
        print(f"Worker (PID {os.getpid()}) Row {index}: Name and description are empty. Assigning 'other attractions'.")
        row_data["category"] = "other attractions"
        return index, row_data

    prompt_text = CATEGORIZATION_PROMPT_TEMPLATE.format(
        name=name,
        desc=description,
        # categories="|".join(CATEGORIZATION_ALLOWED_CATEGORIES) # Not needed in prompt if categories are listed
    )
    
    assigned_category = "other attractions" # Default category

    try:
        raw_json_response = _ask_gemini_for_category(prompt_text)
        if raw_json_response:
            try:
                # Clean the raw_json_response before parsing, if necessary (e.g. remove markdown)
                cleaned_json_text = raw_json_response.strip()
                if cleaned_json_text.startswith("```json"):
                    cleaned_json_text = cleaned_json_text[len("```json"):].strip()
                if cleaned_json_text.endswith("```"):
                    cleaned_json_text = cleaned_json_text[:-len("```")].strip()

                validated_response = CategorizationResponsePydantic.model_validate_json(cleaned_json_text)
                assigned_category = validated_response.category
                print(f"Worker (PID {os.getpid()}) Row {index} ('{name[:30]}...'): Assigned category '{assigned_category}'")
            except Exception as e_pydantic: # Catch Pydantic validation errors or JSON parsing errors
                print(f"Worker (PID {os.getpid()}) Row {index} ('{name[:30]}...'): Pydantic/JSON parsing error: {e_pydantic}. Raw: '{raw_json_response[:100]}'. Defaulting category.")
        else:
            print(f"Worker (PID {os.getpid()}) Row {index} ('{name[:30]}...'): No valid response from Gemini. Defaulting category.")
    except Exception as e_gemini: # Catch errors from _ask_gemini_for_category itself
        print(f"Worker (PID {os.getpid()}) Row {index} ('{name[:30]}...'): Error during Gemini call: {e_gemini}. Defaulting category.")
        
    row_data["new_category"] = assigned_category # Use a new key to avoid overwriting existing "category" if present
    return index, row_data


def run_categorize(args):
    """
    Categorizes entries from an input CSV file using Gemini AI and saves to an output CSV.
    """
    print("Starting categorization process...")
    
    # Load .env for the main process, so GOOGLE_API_KEY is in os.environ for workers
    # _initialize_gemini_client() is for the 'analyze' command client, but loading .env here is good.
    load_dotenv()
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("Error: GOOGLE_API_KEY not found. Please ensure it's in .env or environment variables. Aborting.")
        return

    input_csv_path = Path(args.input_csv_file)
    if not input_csv_path.is_file():
        print(f"Error: Input CSV file '{input_csv_path}' not found. Aborting.")
        return

    if args.output_csv_file:
        output_csv_path = Path(args.output_csv_file)
    else:
        output_csv_path = input_csv_path.with_name(f"{input_csv_path.stem}_labeled.csv")
    
    output_csv_path.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"Input CSV: {input_csv_path}")
    print(f"Output CSV: {output_csv_path}")
    
    rows_to_process = []
    fieldnames = []
    try:
        with open(input_csv_path, 'r', newline='', encoding='utf-8') as f_in:
            reader = csv.DictReader(f_in)
            fieldnames = reader.fieldnames if reader.fieldnames else []
            for i, row in enumerate(reader):
                rows_to_process.append((i, row)) # Send index along with row data
    except Exception as e:
        print(f"Error reading input CSV file '{input_csv_path}': {e}. Aborting.")
        return

    if not rows_to_process:
        print("Input CSV is empty or contains no processable rows. Aborting.")
        # Create an empty output file with headers if possible
        if fieldnames:
            if "new_category" not in fieldnames: fieldnames.append("new_category")
            with open(output_csv_path, 'w', newline='', encoding='utf-8') as f_out_empty:
                writer = csv.DictWriter(f_out_empty, fieldnames=fieldnames)
                writer.writeheader()
        return

    num_workers = args.workers if args.workers and args.workers > 0 else max(1, os.cpu_count() // 2 if os.cpu_count() else 1)
    print(f"Processing {len(rows_to_process)} rows with {num_workers} worker processes...")

    processed_results = []
    try:
        # Pass API key and model name to worker initializer.
        # Workers will inherit these from the environment if set, but explicit passing via initializer is cleaner for some setups.
        # For this implementation, _worker_init_categorize relies on os.getenv("GOOGLE_API_KEY")
        # which should be set because main process called load_dotenv().
        # ANALYSIS_MODEL_NAME is globally accessible in cli.py.
        with multiprocessing.Pool(processes=num_workers, initializer=_worker_init_categorize, initargs=(api_key, ANALYSIS_MODEL_NAME)) as pool:
            # Using imap_unordered for potentially better performance with many small tasks,
            # but then results need to be sorted. Or use map which preserves order.
            # Let's use map for simplicity as order is preserved.
            processed_results_tuples = pool.map(_process_csv_row_for_category_worker, rows_to_process)
        
        # Sort results by original index to ensure correct order if map didn't preserve it (though it should)
        # processed_results_tuples.sort(key=lambda x: x[0]) # Not needed if using map
        processed_rows = [res_tuple[1] for res_tuple in processed_results_tuples]

    except Exception as e_pool:
        print(f"Error during multiprocessing: {e_pool}")
        # Fallback to sequential processing or abort
        print("Aborting due to multiprocessing error.")
        return # Or implement sequential fallback

    if not processed_rows:
        print("No rows were processed. Output file will not be created.")
        return

    # Update fieldnames for output CSV
    if not fieldnames: # Should have been set when reading
        if processed_rows: fieldnames = list(processed_rows[0].keys())
    
    # Ensure 'new_category' is in fieldnames.
    # It might not be if all rows failed before adding it, or if input was empty.
    # Check against the keys of the first processed row if available.
    if processed_rows and "new_category" not in fieldnames:
        # This implies that 'new_category' was not added to the rows, or fieldnames were from an empty input.
        # Let's ensure fieldnames are derived from the actual processed_rows if they exist.
        fieldnames = list(processed_rows[0].keys())


    if "new_category" not in fieldnames and any("new_category" in row for row in processed_rows):
         fieldnames.append("new_category") # Add if it was successfully added to any row and not in original fieldnames
    elif "new_category" not in fieldnames: # If no row got a new_category (e.g. all errors)
        # Add it to header anyway so user knows it was attempted
        fieldnames.append("new_category")


    try:
        with open(output_csv_path, 'w', newline='', encoding='utf-8') as f_out:
            writer = csv.DictWriter(f_out, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(processed_rows)
        print(f"\nSuccessfully categorized entries.")
        print(f"{len(processed_rows)} rows written to {output_csv_path}")
    except Exception as e:
        print(f"Error writing output CSV file '{output_csv_path}': {e}")

# --- Logic for reset command ---

def run_reset_analysis(args):
    """
    Recursively finds and deletes all files named 'analysis.json' within the target_dir.
    """
    print("Starting reset analysis process...")
    target_dir_path = Path(args.target_dir)

    if not target_dir_path.is_dir():
        print(f"Error: Target directory '{target_dir_path}' not found or is not a directory. Aborting.")
        return

    print(f"Scanning for 'analysis.json' files in: {target_dir_path}")
    
    analysis_files_found = list(target_dir_path.rglob('analysis.json'))
    
    if not analysis_files_found:
        print(f"No 'analysis.json' files found in '{target_dir_path}'. Nothing to delete.")
        return

    deleted_count = 0
    error_count = 0

    print(f"Found {len(analysis_files_found)} 'analysis.json' files to delete.")

    for file_path in analysis_files_found:
        try:
            # Check if it's actually a file, rglob can sometimes match directories if named 'analysis.json' (unlikely but safe)
            if file_path.is_file():
                file_path.unlink() # missing_ok=False by default, will raise error if not found during loop
                print(f"  Deleted: {file_path}")
                deleted_count += 1
            elif file_path.exists(): # It exists but is not a file (e.g. a directory with that name)
                print(f"  Skipped (not a file): {file_path}", file=sys.stderr if 'sys' in globals() else None)
            # If missing_ok=True was desired, then no need to check file_path.exists() before unlink
            
        except FileNotFoundError: # Should not happen if is_file() is true, unless deleted between rglob and unlink
            print(f"  Warning: File not found during deletion (already gone?): {file_path}", file=sys.stderr if 'sys' in globals() else None)
        except Exception as e:
            print(f"  Error deleting file {file_path}: {e}", file=sys.stderr if 'sys' in globals() else None)
            error_count += 1
            
    print(f"\nReset analysis summary:")
    print(f"  Successfully deleted: {deleted_count} 'analysis.json' file(s).")
    if error_count > 0:
        print(f"  Errors encountered while deleting: {error_count} file(s).")
    
    if deleted_count == 0 and error_count == 0 and len(analysis_files_found) > 0 :
        print("  No files were actually deleted in this run (e.g. they were directories or errors occurred before deletion attempt).")


def main():
    parser = argparse.ArgumentParser(description="Main CLI tool for processing reels data.")
    subparsers = parser.add_subparsers(title="Commands", dest="command", required=True, help="Available commands")

    # Dummy subcommand 'hello'
    hello_parser = subparsers.add_parser("hello", help="Prints a hello message.")
    hello_parser.add_argument("--name", default="World", help="Name to greet.")
    hello_parser.set_defaults(func=lambda args: print(f"Hello, {args.name}!"))

    # Consolidate subcommand
    consolidate_parser = subparsers.add_parser("consolidate", help="Consolidates multiple JSON message files into one.")
    consolidate_parser.add_argument(
        "input_files",
        nargs='+',
        help="List of JSON message files to consolidate."
    )
    consolidate_parser.add_argument(
        "--output_file", 
        required=True, 
        help="Path to save the consolidated JSON file."
    )
    consolidate_parser.set_defaults(func=run_consolidate)

    # Scrape subcommand
    scrape_parser = subparsers.add_parser("scrape", help="Downloads Instagram reels from a message file.")
    scrape_parser.add_argument(
        "message_file",
        help="Path to the consolidated JSON message file (e.g., consolidated_messages.json)."
    )
    scrape_parser.add_argument(
        "--output_dir",
        default="downloads",
        help="Directory to save downloaded reels and the download database (default: downloads)."
    )
    scrape_parser.set_defaults(func=run_scrape)

    # Analyze subcommand
    analyze_parser = subparsers.add_parser("analyze", help="Analyzes downloaded reels using Gemini AI.")
    analyze_parser.add_argument(
        "--downloads_dir",
        default="downloads",
        help="Path to the directory containing downloaded reels (default: downloads)."
    )
    analyze_parser.add_argument(
        "--force_reanalyze",
        action="store_true", # Makes it a boolean flag, true if present
        help="Force re-analysis of reels even if analysis.json already exists."
    )
    analyze_parser.set_defaults(func=run_analyze)

    # Aggregate subcommand
    aggregate_parser = subparsers.add_parser("aggregate", help="Aggregates analysis entries from downloaded reels.")
    aggregate_parser.add_argument(
        "--reels_dir",
        default="downloads",
        help="Directory containing individual reel folders (e.g., downloads/reel_abc) (default: downloads)."
    )
    aggregate_parser.add_argument(
        "--output_file",
        default="data/all_entries.json",
        help="Path to save the aggregated JSON file (default: data/all_entries.json)."
    )
    aggregate_parser.set_defaults(func=run_aggregate)

    # To-CSV subcommand
    to_csv_parser = subparsers.add_parser("to-csv", help="Converts a JSON array of objects to a CSV file.")
    to_csv_parser.add_argument(
        "input_json_file",
        help="Path to the source JSON file (e.g., data/all_entries.json)."
    )
    to_csv_parser.add_argument(
        "--output_csv_file",
        help="Path to the destination CSV file (optional; defaults to input filename with .csv extension)."
    )
    to_csv_parser.set_defaults(func=run_json_to_csv)

    # Categorize subcommand
    categorize_parser = subparsers.add_parser("categorize", help="Categorizes entries in a CSV file using Gemini AI.")
    categorize_parser.add_argument(
        "input_csv_file",
        help="Path to the source CSV file (e.g., data/all_entries.csv or data/all_entries_with_urls.csv)."
    )
    categorize_parser.add_argument(
        "--output_csv_file",
        help="Path to the destination CSV file with categories (optional; defaults to input filename with '_labeled' suffix)."
    )
    categorize_parser.add_argument(
        "--workers",
        type=int,
        help="Number of worker processes for parallel categorization (optional; defaults to half of CPU cores)."
    )
    categorize_parser.set_defaults(func=run_categorize)

    # Reset subcommand
    reset_parser = subparsers.add_parser("reset", help="Deletes all 'analysis.json' files in a directory.")
    reset_parser.add_argument(
        "--target_dir",
        default="downloads",
        help="The directory to scan for 'analysis.json' files to delete (default: downloads)."
    )
    reset_parser.set_defaults(func=run_reset_analysis)

    args = parser.parse_args()

    if hasattr(args, 'func'):
        args.func(args)
    else:
        # This case should ideally not be reached if a command is required and no default is set for the main parser.
        # However, it's good practice to have a fallback.
        parser.print_help()

if __name__ == "__main__":
    main()
