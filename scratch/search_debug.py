import json
import glob
import os

target_id = "5fb6bd61-c5d4-45cb-8c92-86ceeced7713"
debug_dir = r"c:\Project\ClaimGPT\tmp\parser_debug"

# Find all JSON files recursively
json_files = glob.glob(os.path.join(debug_dir, "**", "*.json"), recursive=True)

for path in json_files:
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
            if target_id in content:
                print(f"Found {target_id} in {path}")
                # Parse and find occurrences
                try:
                    data = json.loads(content)
                    # Let's write a simple recursive finder or print some context
                    lines = content.splitlines()
                    for idx, line in enumerate(lines):
                        if target_id in line:
                            start = max(0, idx - 10)
                            end = min(len(lines), idx + 20)
                            print(f"--- Context in {os.path.basename(path)} (lines {start}-{end}) ---")
                            print("\n".join(lines[start:end]))
                            print("-" * 50)
                except Exception as e:
                    print(f"Error parsing json in {path}: {e}")
    except Exception as e:
        print(f"Error reading {path}: {e}")
