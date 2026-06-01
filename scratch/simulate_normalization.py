import json
import sys
from pathlib import Path

sys.path.insert(0, r"c:\Project\ClaimGPT")

from services.parser_v2.models import TableRegion, Row, Cell
from services.parser_v2.schema_normalizer import normalize_tables
from services.parser_v2.pipeline import _is_probable_expense_row, _parse_amount

json_path = Path("c:/Project/ClaimGPT/tmp/parser_debug/runtime/01_parser_v2_output.json")

def main():
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    tables = []
    for t_data in data.get('tables', []):
        rows = []
        for r_idx, r_data in enumerate(t_data.get('rows', [])):
            cells = []
            for c_data in r_data.get('cells', []):
                cells.append(Cell(
                    cell_id=c_data.get('cell_id'),
                    row_id=c_data.get('row_id'),
                    column_id=c_data.get('column_id'),
                    text=c_data.get('text'),
                    bbox=c_data.get('bbox'),
                    tokens=[],
                    token_count=0
                ))
            rows.append(Row(
                row_id=r_data.get('row_id'),
                row_index=r_idx,
                cells=cells,
                bbox=r_data.get('bbox', [0, 0, 0, 0]),
                token_count=0,
                source_row_ids=[]
            ))
        tables.append(TableRegion(
            region_id=t_data.get('region_id'),
            bbox=t_data.get('bbox'),
            rows=rows,
            page=t_data.get('page'),
            confidence=t_data.get('confidence'),
            model_name=t_data.get('model_name'),
            columns=t_data.get('columns', []),
            table_kind=t_data.get('table_kind')
        ))
        
    # Run normalize_tables
    norm_expenses = normalize_tables(tables)
    print(f"\nRe-run normalize_tables returned {len(norm_expenses)} expenses:")
    for idx, exp in enumerate(norm_expenses):
        print(f"  [{idx+1}] Category: {exp.get('category')} | Desc: {exp.get('description')} | Amount: {exp.get('amount')} | Page: {exp.get('page')}")

    # Now let's trace Table 3 (page 2) specifically
    t3 = tables[2] # Table 3
    print("\nTracing Table 3 rows:")
    for r_idx, row in enumerate(t3.rows):
        cells = sorted(row.cells, key=lambda c: float(c.bbox[0]) if c.bbox else 0.0)
        row_text_chunks = [str(c.text or "").strip() for c in cells if str(c.text or "").strip()]
        joined = " | ".join(row_text_chunks)
        print(f"  Row {r_idx+1}: {joined}")
        
        # Simulate extraction for this row using the exact pipeline logic
        # 1. Find amount
        amount_idx = None
        for i in range(len(cells) - 1, -1, -1):
            cleaned = str(cells[i].text or "").replace("Rs.", "").replace("INR", "").replace("₹", "").replace(",", "").strip()
            # looks numeric check
            if bool(cleaned) and cleaned.replace(".", "", 1).isdigit():
                amount_idx = i
                break
                
        if amount_idx is not None:
            amount = cells[amount_idx].text
            # build description
            desc_parts = []
            for idx, cell in enumerate(cells):
                if idx == amount_idx:
                    continue
                # Skip serial numbers or quantity columns
                txt = str(cell.text or "").strip()
                if txt:
                    desc_parts.append(txt)
            desc = " ".join(desc_parts)
            
            # Run _is_probable_expense_row
            row_dict = {"description": desc, "amount": amount, "page": t3.page}
            prob = _is_probable_expense_row(row_dict)
            print(f"    -> Extracted: desc={repr(desc)}, amount={repr(amount)}")
            print(f"    -> _is_probable_expense_row: {prob}")
            if not prob:
                desc_lower = desc.lower()
                blacklist = ["doctor name", "admission date", "discharge date", "total", "grand total", "net total", "net payable"]
                for term in blacklist:
                    if term in desc_lower:
                        print(f"      -> FAILED because blacklist term {repr(term)} is in desc")

if __name__ == "__main__":
    main()
