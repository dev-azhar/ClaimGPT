import json
from pathlib import Path
import sys

sys.stdout.reconfigure(encoding='utf-8')

json_path = Path("c:/Project/ClaimGPT/tmp/parser_debug/runtime/01_parser_v2_output.json")

def main():
    if not json_path.exists():
        print("JSON file not found!")
        return
        
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    print(f"Tables in 01_parser_v2_output.json ({len(data.get('tables', []))}):")
    for t_idx, tbl in enumerate(data.get('tables', [])):
        print(f"\n=========================================")
        print(f"Table {t_idx+1}: page={tbl.get('page')}, kind={tbl.get('table_kind')}")
        rows = tbl.get("rows", [])
        print(f"  Rows count: {len(rows)}")
        for r_idx, r in enumerate(rows):
            print(f"    Row {r_idx+1}: {r.get('cells')}")

if __name__ == "__main__":
    main()
