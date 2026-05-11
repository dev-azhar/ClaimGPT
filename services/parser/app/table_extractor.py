from typing import List, Dict, Any
import re
from collections import defaultdict

MEDICAL_KEYWORDS = ["room", "pharmacy", "consultation", "nursing", "laboratory", "consumables", "procedure", "charges", "delivery", "labour", "oxygen", "special"]

def extract_table(table_region: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not table_region or "rows" not in table_region:
        return []
        
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
