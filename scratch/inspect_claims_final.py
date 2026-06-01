import sys
from sqlalchemy import create_engine, text
import json

engine = create_engine('postgresql://claimgpt:claimgpt@localhost:5432/claimgpt')

def inspect_claim(claim_id, name):
    print(f"\n=========================================")
    print(f"RESULTS FOR CLAIM: {name} ({claim_id})")
    print(f"=========================================")
    
    with engine.connect() as conn:
        # Check claim status
        status = conn.execute(text("SELECT status FROM claims WHERE id = :cid"), {"cid": claim_id}).scalar()
        print(f"Status: {status}")
        
        # Check expense rows
        result = conn.execute(text(
            "SELECT field_name, field_value FROM parsed_fields "
            "WHERE claim_id = :cid AND field_name LIKE 'expense_table_row_%' "
            "ORDER BY field_name"
        ), {"cid": claim_id})
        rows = result.fetchall()
        print(f"Expense rows count: {len(rows)}")
        for r in rows:
            print(f"  {r[0]} -> {r[1]}")
            
        # Check other key fields like diagnosis, hospital_name
        print("\nKey Fields:")
        result2 = conn.execute(text(
            "SELECT field_name, field_value FROM parsed_fields "
            "WHERE claim_id = :cid AND field_name NOT LIKE 'expense_table_row_%' "
            "ORDER BY field_name"
        ), {"cid": claim_id})
        rows2 = result2.fetchall()
        for r in rows2:
            print(f"  {r[0]} = {r[1]}")
            
        # Check Canonical JSON
        print("\nCanonical JSON Expenses:")
        result3 = conn.execute(text(
            "SELECT canonical_json FROM claims WHERE id = :cid"
        ), {"cid": claim_id})
        canonical_json = result3.scalar()
        if canonical_json:
            expenses = canonical_json.get("expenses", [])
            print(f"Canonical expenses count: {len(expenses)}")
            for idx, exp in enumerate(expenses):
                if isinstance(exp, dict):
                    print(f"  [{idx+1}] Category: {exp.get('category')} | Desc: {exp.get('description')} | Amount: {exp.get('amount')}")
                else:
                    print(f"  [{idx+1}] {exp}")
        else:
            print("No canonical_json found yet.")

def main():
    inspect_claim("1f99f0f4-1d67-4e6f-8d80-f1c8515b89d9", "Claim 1 (Double Expenses)")
    inspect_claim("199c3791-4cbd-4851-bea8-94a298cfb47c", "Claim 2 (Missing/Unnecessary Expenses)")
    inspect_claim("2b9b842a-3c09-4281-adfc-7889f19c3bad", "Claim 2 Alt ID")
    inspect_claim("3993dd6b-9d15-47eb-b924-6008d2687f99", "Claim 2 E2E Fresh Uploaded")

if __name__ == "__main__":
    main()
