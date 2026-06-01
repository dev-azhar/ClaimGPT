import json
from pathlib import Path

json_path = Path("c:/Project/ClaimGPT/tmp/parser_debug/29f56772-ce4c-47e8-911d-d9b23ada6c25_34525d9f-ba63-475f-9745-7fa8b1ac01ee.json")

def main():
    if not json_path.exists():
        print("JSON file not found!")
        return
        
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    print(f"Keys: {list(data.keys())}")
    
    if "results" in data:
        res = data["results"]
        print(f"\nType of 'results': {type(res)}")
        if isinstance(res, dict):
            print(f"Keys under 'results': {list(res.keys())}")
            if "semantic_outputs" in res:
                s_outs = res["semantic_outputs"]
                print(f"Found {len(s_outs)} semantic outputs in results")
                for i, out in enumerate(s_outs):
                    print(f"  [{i+1}] Region ID: {out.get('region_id')}, Region Type: {out.get('region_type')}, Model: {out.get('model_name')}")
                    tables = out.get('tables', [])
                    if tables:
                        print(f"      Tables: {len(tables)}")
                        for t_idx, tbl in enumerate(tables):
                            print(f"        Table {t_idx+1}: kind={tbl.get('table_kind')}, rows={len(tbl.get('rows', []))}")
                            for r_idx, row in enumerate(tbl.get('rows', [])):
                                print(f"          Row {r_idx+1}: {row.get('cells')}")
                                
            if "regions" in res:
                regs = res["regions"]
                print(f"Found {len(regs)} regions in results:")
                for idx, reg in enumerate(regs):
                    print(f"  [{idx+1}] ID: {reg.get('id')}, Type: {reg.get('type')}, Semantic Type: {reg.get('semantic_type')}")
                    text = reg.get('text', '')
                    print(f"      Text: {repr(text[:200])}")
                    
    # Also print page_objects summary
    if "page_objects" in data:
        pages = data["page_objects"]
        print(f"\nFound {len(pages)} page_objects:")
        for idx, p in enumerate(pages):
            print(f"  Page {idx+1}: {list(p.keys())}")
            if "regions" in p:
                print(f"    Regions on page: {len(p['regions'])}")

if __name__ == "__main__":
    main()
