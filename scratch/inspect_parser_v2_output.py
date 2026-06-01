import json
from pathlib import Path

json_path = Path("c:/Project/ClaimGPT/tmp/parser_debug/runtime/01_parser_v2_output.json")

def main():
    if not json_path.exists():
        print("JSON file not found!")
        return
        
    with open(json_path, "r", encoding="utf-8") as f:
        # Since it's 5.4MB, let's load it safely
        data = json.load(f)
        
    print(f"Type of data: {type(data)}")
    if isinstance(data, dict):
        print(f"Keys: {list(data.keys())}")
        if "regions" in data:
            print(f"Found {len(data['regions'])} regions at root level.")
        for k in list(data.keys()):
            if isinstance(data[k], dict):
                print(f"  {k} (dict) keys: {list(data[k].keys())}")
            elif isinstance(data[k], list):
                print(f"  {k} (list) len: {len(data[k])}")
                if data[k]:
                    print(f"    first item type: {type(data[k][0])}")
                    if isinstance(data[k][0], dict):
                        print(f"    first item keys: {list(data[k][0].keys())}")

if __name__ == "__main__":
    main()
