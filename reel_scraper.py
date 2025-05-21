#!/usr/bin/env python3
import json
import subprocess
import os
import re
import sys
import time
import random
import argparse
from urllib.parse import urlparse, parse_qs

def extract_reel_links(json_file):
    """Extract Instagram reel links from a Messenger export JSON file.

    Returns
    -------
    reel_links : list[dict]
        A list of dictionaries with metadata for each reel share **including** the
        index of the originating message. This index is necessary when we later
        want to prune messages from the JSON file.
    url_to_indices : dict[str, list[int]]
        Mapping from the base-URL of a reel (query params stripped) to the list
        of indices in the `messages` array that reference that reel.
    """
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        reel_links = []
        url_to_indices = {}

        instagram_post_count = 0
        reel_count = 0

        for idx, message in enumerate(data.get('messages', [])):
            # Check if message has a share component with a link
            if 'share' in message and 'link' in message['share']:
                link = message['share']['link']

                # Process Instagram links
                if 'instagram.com' in link:
                    instagram_post_count += 1

                    # Specifically identify reels
                    if 'instagram.com/reel' in link:
                        reel_count += 1

                        base_url = link.split('?')[0]

                        # Extract share_text if available, otherwise use empty string
                        share_text = message['share'].get('share_text', '')

                        reel_links.append({
                            'url': link,
                            'timestamp': message.get('timestamp_ms'),
                            'sender': message.get('sender_name'),
                            'original_creator': message['share'].get('original_content_owner', 'unknown'),
                            'share_text': share_text,
                            'message_index': idx,
                        })

                        # Map url -> indices so we can later remove the messages
                        url_to_indices.setdefault(base_url, []).append(idx)

        print(f"Found {instagram_post_count} Instagram posts, of which {reel_count} are reels")
        return reel_links, url_to_indices
    except Exception as e:
        print(f"Error extracting links from {json_file}: {e}")
        return [], {}

def load_downloaded_reels(output_dir='downloads'):
    """Load the database of previously downloaded reels.
    If database doesn't exist, scan the output directory for existing downloads.
    """
    db_path = os.path.join(output_dir, 'downloaded_reels.json')
    reels_db = {}
    
    # Try to load existing database first
    if os.path.exists(db_path):
        try:
            with open(db_path, 'r', encoding='utf-8') as f:
                reels_db = json.load(f)
                print(f"Loaded {len(reels_db)} entries from downloaded reels database")
        except Exception as e:
            print(f"Error loading downloaded reels database: {e}")
    
    # If database is empty or doesn't exist, scan the output directory
    if not reels_db and os.path.exists(output_dir):
        print("No database found or it's empty. Scanning existing downloads folder...")
        scanned_count = 0
        
        # Walk through all directories in the output directory
        for folder_name in os.listdir(output_dir):
            folder_path = os.path.join(output_dir, folder_name)
            
            # Only process directories that start with 'reel_'
            if os.path.isdir(folder_path) and folder_name.startswith('reel_'):
                # Check if this folder contains a metadata.json file
                metadata_path = os.path.join(folder_path, 'metadata.json')
                
                if os.path.exists(metadata_path):
                    try:
                        with open(metadata_path, 'r', encoding='utf-8') as f:
                            metadata = json.load(f)
                        
                        # Extract the clean URL from the metadata
                        if 'url' in metadata:
                            clean_url = metadata['url'].split('?')[0]
                            reel_id = folder_name.replace('reel_', '')
                            
                            # Add to the database
                            reels_db[clean_url] = {
                                'reel_id': reel_id,
                                'download_time': os.path.getmtime(folder_path),
                                'folder': folder_path
                            }
                            scanned_count += 1
                    except Exception as e:
                        print(f"Error scanning metadata in {folder_path}: {e}")
        
        print(f"Scanned existing downloads: found {scanned_count} previously downloaded reels")
        
        # Save the scanned database
        if scanned_count > 0:
            try:
                with open(db_path, 'w', encoding='utf-8') as f:
                    json.dump(reels_db, f, indent=2)
                print(f"Created new database with {scanned_count} entries")
            except Exception as e:
                print(f"Error saving scanned database: {e}")
    
    return reels_db

def save_downloaded_reels(reels_db, output_dir='downloads'):
    """Save the database of downloaded reels."""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    db_path = os.path.join(output_dir, 'downloaded_reels.json')
    try:
        with open(db_path, 'w', encoding='utf-8') as f:
            json.dump(reels_db, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving downloaded reels database: {e}")
        return False

def download_reel(reel_info, output_dir='downloads', reels_db=None, retry_count=0, max_retries=8):
    """Download an Instagram reel using yt-dlp."""
    url = reel_info['url']
    
    # Create output directory if it doesn't exist
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Clean up the URL (remove query parameters)
    clean_url = url.split('?')[0]
    
    # Check if this reel has already been downloaded
    if reels_db is not None and clean_url in reels_db:
        print(f"Skipping already downloaded reel: {clean_url}")
        return 'already_downloaded'
    
    # Extract reel ID for folder name
    parsed_url = urlparse(clean_url)
    path_segments = parsed_url.path.strip('/').split('/')
    reel_id = None
    
    # Try to find reel ID from the URL path
    for segment in path_segments:
        if re.match(r'^[A-Za-z0-9_-]+$', segment) and segment != 'reel':
            reel_id = segment
            break
    
    # If we couldn't find a proper ID, use a timestamp
    if not reel_id:
        reel_id = str(int(time.time()))
    
    try:
        print(f"Downloading: {clean_url}")
        # First check if the reel exists by running yt-dlp with --skip-download
        check_process = subprocess.run(
            [
                'yt-dlp',
                clean_url,
                '--skip-download',        # Only check if video exists
                '--no-warnings',
            ],
            capture_output=True,
            text=True
        )
        
        # Check for rate limiting or other errors
        if check_process.returncode != 0:
            stderr = check_process.stderr.lower()

            # Check if it's a rate limit error
            if 'rate-limit' in stderr or 'too many requests' in stderr:
                if retry_count < max_retries:
                    # Exponential backoff with jitter
                    wait_time = (2 ** retry_count) * 10 + random.uniform(1, 5)
                    print(
                        f"Rate limited! Waiting {wait_time:.1f} seconds before retry {retry_count + 1}/{max_retries}..."
                    )
                    time.sleep(wait_time)
                    return download_reel(
                        reel_info, output_dir, reels_db, retry_count + 1, max_retries
                    )
                else:
                    print(f"Maximum retries reached for {clean_url}. Skipping.")
                    return 'rate_limited'

            # Detect removed / inaccessible content (commonly manifests as an empty media response)
            if (
                'empty media response' in stderr
                or '404' in stderr
                or 'not available' in stderr
                or 'restricted video' in stderr
                or 'you must be 18' in stderr
            ):
                print(f"Reel appears to be removed or inaccessible: {clean_url}")
                return 'removed'

            # Other errors like login required
            print(f"Error checking {clean_url}: {check_process.stderr}")
            return False
        
        # Video exists, proceed with download
        # Create folder for this reel now that we know it exists
        reel_folder = os.path.join(output_dir, f'reel_{reel_id}')
        os.makedirs(reel_folder, exist_ok=True)
        
        # Now download the actual video directly to the folder
        download_process = subprocess.run(
            [
                'yt-dlp', 
                clean_url,
                '--restrict-filenames',  # Replace special chars in filenames
                '-o', f'{reel_folder}/Video by %(uploader)s [%(id)s].%(ext)s',  # Output filename 
                '--no-playlist',         # Do not download playlists
                '--no-warnings',         # Suppress warnings
                '--force-overwrites',    # Overwrite files
            ],
            capture_output=True,
            text=True,
            check=True
        )
        
        # Save metadata to a JSON file
        metadata = {
            'url': reel_info['url'],
            'timestamp': reel_info['timestamp'],
            'sender': reel_info['sender'],
            'original_creator': reel_info['original_creator'],
            'share_text': reel_info['share_text']
        }
        
        with open(os.path.join(reel_folder, 'metadata.json'), 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2)
        
        # Update the database of downloaded reels
        if reels_db is not None:
            reels_db[clean_url] = {
                'reel_id': reel_id,
                'download_time': int(time.time()),
                'folder': reel_folder
            }
        
        print(f"Successfully downloaded: {clean_url}")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"Error downloading {clean_url}: {e}")
        if e.stderr:
            stderr = e.stderr.lower()
            # Check if it's a rate limit error
            if 'rate-limit' in stderr or 'too many requests' in stderr:
                if retry_count < max_retries:
                    # Exponential backoff with jitter
                    wait_time = (2 ** retry_count) * 10 + random.uniform(1, 5)
                    print(f"Rate limited during download! Waiting {wait_time:.1f} seconds before retry {retry_count + 1}/{max_retries}...")
                    
                    # Clean up the folder if it was created but download failed
                    reel_folder = os.path.join(output_dir, f'reel_{reel_id}')
                    if os.path.exists(reel_folder):
                        try:
                            import shutil
                            shutil.rmtree(reel_folder)
                        except Exception as cleanup_error:
                            print(f"Warning: Could not clean up folder {reel_folder}: {cleanup_error}")
                    
                    time.sleep(wait_time)
                    return download_reel(reel_info, output_dir, reels_db, retry_count + 1, max_retries)
                else:
                    print(f"Maximum retries reached for {clean_url}. Skipping.")
                    return 'rate_limited'
            elif (
                'empty media response' in stderr
                or '404' in stderr
                or 'not available' in stderr
                or 'restricted video' in stderr
                or 'you must be 18' in stderr
            ):
                print(f"Reel appears to be removed or inaccessible during download: {clean_url}")
                return 'removed'
            else:
                print(f"Error details: {e.stderr}")
        
        # Clean up the folder if it was created but download failed
        reel_folder = os.path.join(output_dir, f'reel_{reel_id}')
        if os.path.exists(reel_folder):
            try:
                # Try to remove the directory and its contents
                import shutil
                shutil.rmtree(reel_folder)
            except Exception as cleanup_error:
                print(f"Warning: Could not clean up folder {reel_folder}: {cleanup_error}")
        
        return False

def run(message_file: str = "consolidated_messages.json", output_dir: str = "downloads") -> None:
    """Download reels referenced in *message_file* into *output_dir*."""

    # Load database of previously downloaded reels
    reels_db = load_downloaded_reels(output_dir)
    print(f"Found {len(reels_db)} previously downloaded reels")

    # Extract links
    print(f"Processing {message_file}...")
    reels, url_to_indices = extract_reel_links(message_file)
    if not reels:
        print("No reels found.")
        return
    
    # Remove duplicates (based on URL) but keep mapping to original message indices
    unique_reels = []
    seen_urls = set()
    for reel in reels:
        url_base = reel['url'].split('?')[0]  # Remove query parameters for comparison
        if url_base not in seen_urls:
            seen_urls.add(url_base)
            unique_reels.append(reel)
    
    print(f"Total unique reels found: {len(unique_reels)}")
    
    # Count reels that have already been downloaded
    already_downloaded = sum(1 for reel in unique_reels if reel['url'].split('?')[0] in reels_db)
    print(f"Of these, {already_downloaded} have already been downloaded")
    print(f"Attempting to download {len(unique_reels) - already_downloaded} new reels")
    
    # Download reels
    success_count = 0
    already_downloaded_count = 0
    rate_limited_count = 0
    removed_count = 0
    error_count = 0
    
    for i, reel in enumerate(unique_reels, 1):
        print(f"[{i}/{len(unique_reels)}] Processing reel from {reel['original_creator']}")
        
        # Check if reel is already downloaded before applying any delay
        clean_url = reel['url'].split('?')[0]
        if reels_db is not None and clean_url in reels_db:
            print(f"Skipping already downloaded reel: {clean_url}")
            result = 'already_downloaded'
        else:
            # Only add a delay between new downloads to avoid rate limiting
            if i > 1 and success_count + error_count + rate_limited_count > 0:  # Don't delay before the first actual download
                delay = random.uniform(1.5, 3.0)
                print(f"Waiting {delay:.1f} seconds to avoid rate limiting...")
                time.sleep(delay)
            
            result = download_reel(reel, output_dir, reels_db)
        
        if result is True:
            success_count += 1
            # Save the database after each successful download
            save_downloaded_reels(reels_db, output_dir)
            # Immediately prune JSON as this reel is now handled
            prune_messages_by_url(message_file, clean_url)
        elif result == 'already_downloaded':
            already_downloaded_count += 1
            prune_messages_by_url(message_file, clean_url)
        elif result == 'removed':
            removed_count += 1
            prune_messages_by_url(message_file, clean_url)
        elif result == 'rate_limited':
            rate_limited_count += 1
            # Add a longer delay after rate limiting
            delay = random.uniform(30, 60)
            print(f"Taking a longer break ({delay:.1f} seconds) due to rate limiting...")
            time.sleep(delay)
        else:
            error_count += 1
            
        print("------------------------")
    
    print(f"Download summary:")
    print(f"- Successfully downloaded: {success_count} new reels")
    print(f"- Already downloaded: {already_downloaded_count} reels")
    print(f"- Removed/unavailable: {removed_count} reels")
    print(f"- Rate limited: {rate_limited_count} reels")
    print(f"- Other errors: {error_count} reels")
    print(f"Total reels in database now: {len(reels_db)}")
    
    # Final save of the database
    save_downloaded_reels(reels_db, output_dir)

# -------------------------------------------------------------------------
# Message-pruning utility
# -------------------------------------------------------------------------

def prune_messages_by_url(src_path: str, base_url: str):
    """Remove every message that shares *base_url* from *src_path* JSON file.

    The function is **idempotent** and performs a one-time backup to
    `<file>.bak` (only created the first time it runs for that source).
    """

    try:
        with open(src_path, "r", encoding="utf-8") as f_in:
            data_in = json.load(f_in)

        messages = data_in.get("messages", [])

        new_messages = [
            m
            for m in messages
            if not (
                "share" in m
                and "link" in m["share"]
                and m["share"]["link"].split("?")[0] == base_url
            )
        ]

        removed_cnt = len(messages) - len(new_messages)

        if removed_cnt == 0:
            return  # nothing to do

        # create backup once
        backup_path = src_path + ".bak"
        if not os.path.exists(backup_path):
            import shutil

            shutil.copy2(src_path, backup_path)

        data_in["messages"] = new_messages

        with open(src_path, "w", encoding="utf-8") as f_out:
            json.dump(data_in, f_out, indent=2)

        print(
            f"Pruned {removed_cnt} messages (url={base_url}) from {src_path}. "
            f"New total: {len(new_messages)}"
        )
    except Exception as err:
        print(f"Error pruning messages for url {base_url}: {err}")

def main() -> None:
    parser = argparse.ArgumentParser(description="Download reels from messages")
    parser.add_argument(
        "message_file",
        nargs="?",
        default="consolidated_messages.json",
        help="Path to the consolidated Messenger JSON file",
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        default="downloads",
        help="Directory where reels will be saved",
    )
    args = parser.parse_args()
    run(args.message_file, args.output_dir)


if __name__ == "__main__":
    main()