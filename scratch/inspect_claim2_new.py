import json
from pathlib import Path
import sys

# Set standard output encoding to utf-8
sys.stdout.reconfigure(encoding='utf-8')

json_path = Path("c:/Project/ClaimGPT/tmp/parser_debug/199c3791-4cbd-4851-bea8-94a298cfb47c_dbf8d9fd-4617-4c16-9341-0c5a97387d1e.json")

def main():
    if not json_path.exists():
        print("JSON file not found!")
        return
        
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    if "ocr_pages" in data and len(data["ocr_pages"]) >= 1:
        print("\nOCR Page 1 Full Text:")
        page1 = data["ocr_pages"][0]
        tokens = page1.get("tokens", [])
        txt = " ".join([t.get("text", "") for t in tokens])
        print(txt)

if __name__ == "__main__":
    main()
