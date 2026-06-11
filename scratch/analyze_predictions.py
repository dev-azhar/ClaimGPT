import json
import os

predictions_file = r"c:\Project\ClaimGPT\tmp\parser_debug\model_predictions.json"
regions_file = r"c:\Project\ClaimGPT\tmp\parser_debug\semantic_region_outputs.json"

if os.path.exists(predictions_file):
    with open(predictions_file, "r", encoding="utf-8") as f:
        predictions = json.load(f)
    print(f"Loaded {len(predictions)} predictions:")
    for pred in predictions:
        print(f"Region ID: {pred.get('region_id')}, Page: {pred.get('page')}, Type: {pred.get('region_type')}, Model: {pred.get('model_name')}, Available: {pred.get('available')}")
        if 'prediction' in pred and pred['prediction']:
            tables = pred['prediction'].get('tables', [])
            fields = pred['prediction'].get('fields', [])
            print(f"  -> Prediction has {len(tables)} tables, {len(fields)} fields")
            for t in tables:
                print(f"    - Table kind: {t.get('table_kind')}, rows: {len(t.get('rows', []))}")
        else:
            print(f"  -> Prediction: {pred.get('prediction')} (reason: {pred.get('reason')})")
else:
    print("model_predictions.json does not exist")

print("\n" + "="*50 + "\n")

if os.path.exists(regions_file):
    with open(regions_file, "r", encoding="utf-8") as f:
        regions = json.load(f)
    print(f"Loaded {len(regions)} regions:")
    for r in regions:
        print(f"Region ID: {r.get('region_id')}, Type: {r.get('region_type')}, Semantic Type: {r.get('semantic_type')}, Model: {r.get('model_name')}")
        tables = r.get('tables', [])
        fields = r.get('fields', [])
        print(f"  -> {len(tables)} tables, {len(fields)} fields")
        for t in tables:
            print(f"    - Table kind: {t.get('table_kind')}, rows: {len(t.get('rows', []))}")
else:
    print("semantic_region_outputs.json does not exist")
