import json
from pathlib import Path

json_path = Path("c:/Project/ClaimGPT/tmp/parser_debug/runtime/03_normalized_expenses.json")

def main():
    if not json_path.exists():
        print("JSON file not found!")
        return
        
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    print(f"Loaded normalized_expenses: {len(data)} items")
    for idx, exp in enumerate(data):
        print(f"  [{idx+1}] Category: {exp.get('category')} | Desc: {exp.get('description')} | Amount: {exp.get('amount')} | Source: {exp.get('source', exp.get('sources'))} | Page: {exp.get('page')}")

if __name__ == "__main__":
    main()
