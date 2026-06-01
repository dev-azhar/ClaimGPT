import json
from pathlib import Path

json_path = Path("c:/Project/ClaimGPT/tmp/parser_debug/199c3791-4cbd-4851-bea8-94a298cfb47c_d077d93c-1ed2-4651-b751-8e41549cae7c.json")

def main():
    if not json_path.exists():
        print("JSON file not found!")
        return
        
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    print(f"Loaded debug file: {json_path.name}")
    
    # Check model_predictions
    predictions = data.get("model_predictions", [])
    print(f"\nModel Predictions ({len(predictions)}):")
    for i, pred in enumerate(predictions):
        print(f"  [{i+1}] Region ID: {pred.get('region_id')}, Region Type: {pred.get('region_type')}, Model: {pred.get('model_name')}, Available: {pred.get('available')}")
        print(f"      Prediction keys: {list(pred.get('prediction', {}).keys()) if pred.get('prediction') else 'None'}")
        
    # Check semantic_regions
    sem_regs = data.get("semantic_regions", [])
    print(f"\nSemantic Regions ({len(sem_regs)}):")
    for i, reg in enumerate(sem_regs):
        print(f"  [{i+1}] Region ID: {reg.get('region_id')}, Type: {reg.get('region_type')}, Model: {reg.get('model_name')}")
        tables = reg.get("tables", [])
        if tables:
            for t_idx, tbl in enumerate(tables):
                print(f"      Table {t_idx+1}: kind={tbl.get('table_kind')}, rows={len(tbl.get('rows', []))}")
                for r_idx, r in enumerate(tbl.get('rows', [])):
                    print(f"        Row {r_idx+1}: {r.get('cells')}")
                    
if __name__ == "__main__":
    main()
