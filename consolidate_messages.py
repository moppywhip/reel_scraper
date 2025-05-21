#!/usr/bin/env python3
import json
import sys

def consolidate_messages(file_paths, output_path):
    """
    Consolidate multiple message JSON files into a single file.
    
    Args:
        file_paths: List of JSON file paths to consolidate
        output_path: Path to save the consolidated file
    """
    all_messages = []
    participants = set()
    
    # Read and combine all messages
    for file_path in file_paths:
        print(f"Processing {file_path}...")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Store all participants
            for participant in data.get('participants', []):
                participant_name = participant.get('name')
                if participant_name:
                    participants.add(participant_name)
            
            # Add all messages
            all_messages.extend(data.get('messages', []))
            print(f"Added {len(data.get('messages', []))} messages from {file_path}")
        except Exception as e:
            print(f"Error processing {file_path}: {e}")
    
    # Sort messages by timestamp (newest first, which is how they appear in the original files)
    all_messages.sort(key=lambda msg: msg.get('timestamp_ms', 0), reverse=True)
    
    # Create consolidated data
    consolidated_data = {
        'participants': [{'name': name} for name in participants],
        'messages': all_messages
    }
    
    # Save consolidated data
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(consolidated_data, f, ensure_ascii=False, indent=2)
    
    print(f"Consolidated {len(all_messages)} messages from {len(file_paths)} files")
    print(f"Output saved to {output_path}")

def run(output_path: str, input_paths: list[str]) -> None:
    consolidate_messages(input_paths, output_path)


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: consolidate_messages.py <output_file> <input_file1> <input_file2> ...")
        sys.exit(1)

    output_path = sys.argv[1]
    input_paths = sys.argv[2:]

    consolidate_messages(input_paths, output_path)


if __name__ == "__main__":
    main()
