import json
from pathlib import Path

json_path = Path("c:/Project/ClaimGPT/tmp/parser_debug/runtime/01_parser_v2_output.json")

def main():
    if not json_path.exists():
        print("JSON file not found!")
        return
        
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    # Search for DELIVERY CHARGES in all tables
    for t_idx, tbl in enumerate(data.get('tables', [])):
        rows = tbl.get("rows", [])
        for r_idx, r in enumerate(rows):
            cells = r.get("cells", [])
            cells_text = [str(c.get("text") or "").strip() for c in cells]
            joined = " | ".join(cells_text)
            if "DELIVERY" in joined or "SPECIAL" in joined:
                print(f"Table {t_idx+1} (page {tbl.get('page')}) Row {r_idx+1}: {joined}")
                print(f"Raw row details: {cells_text}")
                
if __name__ == "__main__":
    main()
