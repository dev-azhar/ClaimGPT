import json
from pathlib import Path

json_path = Path("c:/Project/ClaimGPT/tmp/parser_debug/29f56772-ce4c-47e8-911d-d9b23ada6c25_34525d9f-ba63-475f-9745-7fa8b1ac01ee.json")

def main():
    if not json_path.exists():
        print("JSON file not found!")
        return
        
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    print(f"Keys in JSON: {list(data.keys())}")
    
    # Check regions
    if "regions" in data:
        regions = data["regions"]
        print(f"\nFound {len(regions)} regions:")
        for idx, reg in enumerate(regions):
            print(f"  [{idx+1}] ID: {reg.get('id')}, Type: {reg.get('type')}, Semantic Type: {reg.get('semantic_type')}")
            # print first 200 chars of text
            text = reg.get('text', '')
            print(f"      Text preview: {repr(text[:200])}")
            
    # Check semantic outputs
    if "semantic_outputs" in data:
        sem_outs = data["semantic_outputs"]
        print(f"\nFound {len(sem_outs)} semantic_outputs:")
        for idx, out in enumerate(sem_outs):
            print(f"  [{idx+1}] Region ID: {out.get('region_id')}, Region Type: {out.get('region_type')}, Model: {out.get('model_name')}")
            # Let's print tables in the semantic output
            tables = out.get('tables', [])
            if tables:
                print(f"      Tables: {len(tables)}")
                for t_idx, tbl in enumerate(tables):
                    print(f"        Table {t_idx+1}: kind={tbl.get('table_kind')}, rows={len(tbl.get('rows', []))}")
                    for r_idx, row in enumerate(tbl.get('rows', [])):
                        print(f"          Row {r_idx+1}: {row.get('cells')}")

if __name__ == "__main__":
    main()
