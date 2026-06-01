import json
from pathlib import Path
from sqlalchemy import create_engine, text

engine = create_engine('postgresql://claimgpt:claimgpt@localhost:5432/claimgpt')

def inspect_claim(claim_id, name):
    print(f"\n=========================================")
    print(f"INSPECTING CLAIM: {name} ({claim_id})")
    print(f"=========================================")
    
    # 1. Check database status
    with engine.connect() as conn:
        res = conn.execute(text("SELECT status, canonical_json FROM claims WHERE id = :cid"), {"cid": claim_id}).fetchone()
        if res:
            print(f"Database Status: {res[0]}")
            canon = res[1]
            if canon:
                print(f"Canonical keys: {list(canon.keys())}")
                expenses = canon.get('expenses', {})
                if isinstance(expenses, dict):
                    print(f"Canonical Expenses Keys: {list(expenses.keys())}")
                    print(f"Item Count: {expenses.get('item_count')}")
                    line_items = expenses.get('line_items', [])
                    print(f"Line Items Count: {len(line_items)}")
                    for idx, exp in enumerate(line_items[:30]):
                        print(f"  [{idx+1}] Category: {exp.get('category')} | Desc: {exp.get('description')} | Amount: {exp.get('amount')}")
                else:
                    print(f"Expenses is not a dict: {type(expenses)}")
                    print(repr(expenses))
            else:
                print("Canonical JSON is empty/NULL")
        else:
            print("Claim not found in database!")

    # 2. Check parser debug files
    debug_dir = Path("c:/Project/ClaimGPT/tmp/parser_debug")
    claim_files = list(debug_dir.glob(f"{claim_id}_*.json"))
    if claim_files:
        print(f"\nFound debug JSON file: {claim_files[0].name}")
        with open(claim_files[0], "r", encoding="utf-8") as f:
            data = json.load(f)
            
        canonical_claim = data.get("canonical_claim", {})
        print(f"Debug JSON canonical_claim keys: {list(canonical_claim.keys())}")
        if "expenses" in canonical_claim:
            deb_exp = canonical_claim["expenses"]
            if isinstance(deb_exp, dict):
                print(f"Debug item_count: {deb_exp.get('item_count')}")
                deb_line_items = deb_exp.get('line_items', [])
                print(f"Debug Line Items Count: {len(deb_line_items)}")
                for idx, exp in enumerate(deb_line_items[:30]):
                    print(f"  Debug [{idx+1}] Category: {exp.get('category')} | Desc: {exp.get('description')} | Amount: {exp.get('amount')} | Source: {exp.get('source', exp.get('sources'))}")
            elif isinstance(deb_exp, list):
                print(f"Debug Expenses is a list of len {len(deb_exp)}")
                for idx, exp in enumerate(deb_exp[:30]):
                    print(f"  Debug [{idx+1}] Category: {exp.get('category')} | Desc: {exp.get('description')} | Amount: {exp.get('amount')}")
        
        # Let's inspect raw parser results to see what LLM returned vs what heuristic returned!
        results = data.get("results", {})
        if results and isinstance(results, dict):
            # Print if there is normalized_expenses
            norm_exp = results.get("normalized_expenses", [])
            if norm_exp:
                print(f"\nResults normalized_expenses ({len(norm_exp)} items):")
                for idx, exp in enumerate(norm_exp[:30]):
                    print(f"  Norm [{idx+1}] Category: {exp.get('category')} | Desc: {exp.get('description')} | Amount: {exp.get('amount')} | Source: {exp.get('source', exp.get('sources'))}")
    else:
        print("\nNo direct debug JSON found in tmp/parser_debug for this claim ID.")

def main():
    inspect_claim("1f99f0f4-1d67-4e6f-8d80-f1c8515b89d9", "Claim 1 (Double Expenses)")
    inspect_claim("199c3791-4cbd-4851-bea8-94a298cfb47c", "Claim 2 (Missing/Unnecessary Expenses)")

if __name__ == "__main__":
    main()
