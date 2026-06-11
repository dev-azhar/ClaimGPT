import json

path = r"c:\Project\ClaimGPT\tmp\parser_debug\runtime\01_parser_v2_output.json"

with open(path, "r", encoding="utf-8") as f:
    doc = json.load(f)

for table in doc.get("tables", []):
    rid = table.get("region_id")
    page = table.get("page")
    if page in [1, 2]:
        print(f"\n================ Table Region: {rid} ================")
        print(f"Page: {page}")
        print(f"Table Kind: {table.get('table_kind')}")
        print("Rows:")
        for idx, row in enumerate(table.get("rows", [])):
            cells_text = [cell.get("text", "") for cell in row.get("cells", [])]
            print(f"  Row {idx}: {cells_text}")
