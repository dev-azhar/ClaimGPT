from typing import List, Dict, Any
import re
from collections import defaultdict

MEDICAL_KEYWORDS = ["room", "pharmacy", "consultation", "nursing", "laboratory", "consumables", "procedure", "charges", "delivery", "labour", "oxygen", "special"]

def extract_table(table_region: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not table_region:
        return []

    # PP-Structure-style tables may arrive as a cell grid instead of token rows.
    if table_region.get("cells") and not table_region.get("rows"):
        return _extract_from_cells(table_region)
        
    line_items = []
    
    for row_data in table_region["rows"]:
        tokens = row_data.get("tokens", [])
        if not tokens:
            continue
            
        # Sort left-to-right
        tokens = sorted(tokens, key=lambda t: t["x0"])
        row_text = " ".join(t.get("text", "") for t in tokens).lower()
        
        # Must contain medical keywords
        if not any(k in row_text for k in MEDICAL_KEYWORDS):
            continue
            
        # Ignore total/summary rows
        if re.search(r"\b(?:total|sum insured|claim amount|amount exceeding|grand total)\b", row_text):
            continue
            
        # Find amount (last numeric token)
        amount_idx = -1
        raw_amount = ""
        amount_val = 0.0
        
        for i in range(len(tokens)-1, -1, -1):
            token_clean = tokens[i].get("text", "").replace('Rs.', '').replace('INR', '').replace(',', '').strip()
            if re.match(r'^\d{1,3}(,\d{3})*(\.\d{2})?$', tokens[i].get("text", "").replace('Rs.', '').replace('INR', '').strip()) or token_clean.replace('.', '').isdigit():
                try:
                    amount_val = float(token_clean)
                    if amount_val > 0:
                        amount_idx = i
                        raw_amount = tokens[i].get("text", "")
                        break
                except ValueError:
                    pass
                    
        if amount_idx == -1:
            continue
            
        # Remaining tokens form the description/category
        clean_tokens = [t.get("text", "") for i, t in enumerate(tokens) if i != amount_idx]
        
        if len(clean_tokens) >= 2:
            sr = clean_tokens[0]
            category = clean_tokens[1]
            description = " ".join(clean_tokens[2:])
        elif len(clean_tokens) == 1:
            sr = ""
            category = clean_tokens[0]
            description = ""
        else:
            sr = ""
            category = "Expense"
            description = ""
            
        desc = description or category or "Expense"
        
        line_items.append({
            "description": desc,
            "category": category,
            "quantity": 1.0,
            "unit_price": amount_val,
            "amount": amount_val
        })
        
    return line_items


def _extract_from_cells(table_region: Dict[str, Any]) -> List[Dict[str, Any]]:
    cells_grid = table_region.get("cells") or []
    line_items: List[Dict[str, Any]] = []

    for row in cells_grid:
        if not row:
            continue

        cell_texts = []
        for cell in row:
            if isinstance(cell, dict):
                text = str(cell.get("text", "")).strip()
            else:
                text = str(cell).strip()
            cell_texts.append(text)

        row_text = " ".join(cell_texts).lower()
        if not any(k in row_text for k in MEDICAL_KEYWORDS):
            continue
        if re.search(r"\b(?:total|sum insured|claim amount|amount exceeding|grand total)\b", row_text):
            continue

        amount_value = None
        for text in reversed(cell_texts):
            cleaned = text.replace("Rs.", "").replace("INR", "").replace(",", "").strip()
            if not cleaned:
                continue
            try:
                amount_value = float(cleaned)
                if amount_value > 0:
                    break
            except ValueError:
                continue

        if not amount_value or amount_value <= 0:
            continue

        description = " ".join(text for text in cell_texts[:-1] if text).strip() or "Expense"
        category = cell_texts[1].strip() if len(cell_texts) > 1 and cell_texts[1].strip() else description

        line_items.append({
            "description": description,
            "category": category,
            "quantity": 1.0,
            "unit_price": amount_value,
            "amount": amount_value,
        })

    return line_items
