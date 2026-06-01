import json
from pathlib import Path

json_path = Path("c:/Project/ClaimGPT/tmp/parser_debug/runtime/01_parser_v2_output.json")

def main():
    if not json_path.exists():
        print("JSON file not found!")
        return
        
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    sem_regs = data.get("semantic_regions", [])
    print(f"Found {len(sem_regs)} semantic_regions:")
    for idx, reg in enumerate(sem_regs):
        print(f"\n=========================================")
        print(f"Semantic Region [{idx+1}]:")
        print(f"  Region ID: {reg.get('region_id')}")
        print(f"  Region Type: {reg.get('region_type')}")
        print(f"  Semantic Type: {reg.get('semantic_type')}")
        print(f"  Model Name: {reg.get('model_name')}")
        print(f"  Notes: {reg.get('notes')}")
        
        # Let's print fields extracted in this semantic region
        fields = reg.get("fields", [])
        if fields:
            print(f"  Fields extracted ({len(fields)}):")
            for f in fields:
                print(f"    - Canonical: {f.get('canonical_field')}, Value: {f.get('value')}")
                
        # Let's print tables extracted in this semantic region
        tables = reg.get("tables", [])
        if tables:
            print(f"  Tables extracted ({len(tables)}):")
            for t_idx, tbl in enumerate(tables):
                print(f"    Table {t_idx+1}: kind={tbl.get('table_kind')}, headers={tbl.get('headers')}")
                rows = tbl.get("rows", [])
                for r_idx, r in enumerate(rows):
                    print(f"      Row {r_idx+1}: {r.get('cells')}")
                    
        # Let's find the original region in regions list to print the source text/tokens
        orig_region = None
        for orig in data.get("regions", []):
            if orig.get("region_id") == reg.get("region_id"):
                orig_region = orig
                break
                
        if orig_region:
            print(f"  Original Region Info:")
            print(f"    Region Type: {orig_region.get('region_type')}")
            # print some of the tokens
            tokens = orig_region.get("tokens", [])
            print(f"    Tokens Count: {len(tokens)}")
            token_texts = [t.get("text", "") for t in tokens]
            print(f"    Token text preview: {' '.join(token_texts[:100])}")

if __name__ == "__main__":
    main()
