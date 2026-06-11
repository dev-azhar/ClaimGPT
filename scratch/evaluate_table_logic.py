import json
import re
# from services.parser_v2.models import TableRegion, Row, Cell

path = r"c:\Project\ClaimGPT\tmp\parser_debug\runtime\01_parser_v2_output.json"

with open(path, "r", encoding="utf-8") as f:
    doc_json = json.load(f)

# Reconstruct TableRegion object from JSON
from pydantic import BaseModel
class TableRegionObj:
    def __init__(self, d):
        self.region_id = d.get("region_id")
        self.page = d.get("page")
        self.bbox = d.get("bbox")
        self.table_kind = d.get("table_kind")
        self.confidence = d.get("confidence", 1.0)
        self.model_name = d.get("model_name", "model")
        
        # Rows
        self.rows = []
        for r in d.get("rows", []):
            cells = []
            for c in r.get("cells", []):
                # Mock cell
                class MockCell:
                    def __init__(self, cell_dict):
                        self.text = cell_dict.get("text")
                        self.bbox = cell_dict.get("bbox")
                        self.tokens = [] # simplified
                        self.column_id = cell_dict.get("column_id")
                        self.row_id = cell_dict.get("row_id")
                        self.cell_id = cell_dict.get("cell_id")
                        self.token_count = cell_dict.get("token_count", 0)
                cells.append(MockCell(c))
            class MockRow:
                def __init__(self, cells):
                    self.cells = cells
            self.rows.append(MockRow(cells))

# Find table for page 4
table_data = None
for t in doc_json.get("tables", []):
    if t.get("region_id") == "5fb6bd61-c5d4-45cb-8c92-86ceeced7713":
        table_data = t
        break

if table_data:
    table = TableRegionObj(table_data)
    
    # Let's test the medications logic on this table
    rows = table.rows
    table_text = " ".join(str(cell.text or "") for row in rows for cell in row.cells).lower()
    
    billing_terms = ["gross", "payable", "rate", "rs.", "inr", "₹", "amount", "price", "bill", "invoice", "receipt", "charge", "charges", "total"]
    found_billing_terms = [term for term in billing_terms if term in table_text]
    print(f"Found billing terms: {found_billing_terms}")
    
    has_billing_terms = len(found_billing_terms) > 0
    print(f"has_billing_terms: {has_billing_terms}")
    
    has_prices = False
    has_currency_symbol = any(sym in table_text for sym in ["rs.", "inr", "₹"])
    print(f"has_currency_symbol: {has_currency_symbol}")
    for row in rows:
        for cell in row.cells:
            text = str(cell.text or "").strip().replace(",", "")
            cleaned = re.sub(r"^(?:rs|inr|₹)\.?\s*", "", text, flags=re.IGNORECASE).strip()
            if re.fullmatch(r"\d+\.\d{2}", cleaned):
                has_prices = True
                print(f"Price matches decimal: {cleaned} from cell: {cell.text}")
                break
            if (has_currency_symbol or any(t in table_text for t in ["amount", "price", "rate", "charges", "fees"])) and re.fullmatch(r"\d+", cleaned) and int(cleaned) > 0:
                has_prices = True
                print(f"Price matches integer under symbol/context: {cleaned} from cell: {cell.text}")
                break
        if has_prices:
            break
            
    print(f"has_prices: {has_prices}")
    
    # Check if the table has common medication/prescription column headers
    med_headers = {"drug name", "drug", "medicine", "dose", "dosage", "frequency", "instruction", "instructions", "duration", "days", "qunt.", "quantity"}
    
    has_med_header = False
    for candidate_row in rows[:2]:
        row_text_cells = [str(cell.text or "").strip().lower() for cell in candidate_row.cells]
        if any(h in row_text_cells for h in ["drug name", "instruction", "dosage", "frequency"]) or (any("dose" in h for h in row_text_cells) and any("days" in h for h in row_text_cells)):
            has_med_header = True
            print(f"Found med header in candidate row: {row_text_cells}")
            break
            
    discharge_med_markers = [
        "treatment on discharge", "treatment on dicharge", "discharge summary", 
        "discharge medications", "medications on discharge", "treatment on discharge:",
        "medications administered", "medication administered", "administered medications",
        "in-hospital medications", "medications administered (in-hospital)", "medication list",
        "medications", "discharge advice & medications"
    ]
    found_discharge_markers = [marker for marker in discharge_med_markers if marker in table_text]
    print(f"Found discharge markers: {found_discharge_markers}")
    has_discharge_marker = len(found_discharge_markers) > 0
    
    med_keyword_count = sum(1 for term in ["inj.", "tab.", "cap.", "inj ", "tab ", "cap "] if term in table_text)
    route_strength_count = sum(1 for term in [" po ", " iv ", " im ", " sc ", " bd", " tds", " od", " mg ", " ml ", " mcg "] if term in table_text)
    print(f"med_keyword_count: {med_keyword_count}, route_strength_count: {route_strength_count}")
    looks_like_clinical_log = med_keyword_count >= 2 and route_strength_count >= 2
    print(f"looks_like_clinical_log: {looks_like_clinical_log}")
    
    is_med_table = has_med_header or has_discharge_marker or looks_like_clinical_log
    print(f"Final is_med_table check: {is_med_table}")
    
    # Wait, if is_med_table is True, why did it still get processed?
    # Ah! In _is_medications_table:
    # if has_billing_terms and has_prices: return False
    # Let's check if (has_billing_terms and has_prices) was True!
    if has_billing_terms and has_prices:
        print("-> Table rejected from medications check because has_billing_terms and has_prices are BOTH true!")
else:
    print("Table not found")
