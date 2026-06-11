import json

path = r"c:\Project\ClaimGPT\tmp\parser_debug\runtime\01_parser_v2_output.json"

with open(path, "r", encoding="utf-8") as f:
    doc = json.load(f)

regions_to_check = ["5fb6bd61-c5d4-45cb-8c92-86ceeced7713", "4a30f3bf-3556-4f21-9ef9-6eb8f2db6b09", "151b671e-5361-4179-b2e5-d1ebe5c337a4"]

print("Doc structure regions count:", len(doc.get("regions", [])))
print("Doc structure tables count:", len(doc.get("tables", [])))

for table in doc.get("tables", []):
    rid = table.get("region_id")
    if rid in regions_to_check:
        print(f"\n================ Table Region: {rid} ================")
        print(f"Page: {table.get('page')}")
        print(f"Table Kind: {table.get('table_kind')}")
        print("Rows:")
        for idx, row in enumerate(table.get("rows", [])):
            cells_text = [cell.get("text", "") for cell in row.get("cells", [])]
            print(f"  Row {idx}: {cells_text}")
