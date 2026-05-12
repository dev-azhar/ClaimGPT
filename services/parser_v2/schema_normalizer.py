import logging
from typing import List, Dict, Any
from .models import FormField, TableRegion

logger = logging.getLogger("parser-debug")

CANONICAL_MAPPING = {
    "patient_name": "patient.name",
    "name": "patient.name",
    "patient": "patient.name",
    "date_of_birth": "patient.date_of_birth",
    "birth": "patient.date_of_birth",
    "date": "patient.date_of_birth",
    "sex": "patient.sex",
    "gender": "patient.sex",
    "policy_number": "insurance.policy_number",
    "policy": "insurance.policy_number",
    "number": "insurance.policy_number",
    "insurance_provider": "insurance.payer",
    "provider": "insurance.payer",
    "insurance": "insurance.payer",
    "admission_date": "hospitalization.admission_date",
    "admission": "hospitalization.admission_date",
    "discharge_date": "hospitalization.discharge_date",
    "discharge": "hospitalization.discharge_date",
}

def normalize_fields(fields: List[FormField]) -> List[Dict[str, Any]]:
    """Maps geometric fields to canonical schema names."""
    normalized = []
    for field in fields:
        key_norm = field.key.lower().strip().replace(":", "").replace(" ", "_")
        canonical_key = CANONICAL_MAPPING.get(key_norm)
        
        if canonical_key:
            normalized.append({
                "field": key_norm,
                "canonical_field": canonical_key,
                "value": field.value,
                "confidence": 0.95,
                "bbox": field.value_bbox,
                "page": field.page
            })
    return normalized

def normalize_tables(tables: List[TableRegion]) -> List[Dict[str, Any]]:
    """Identifies and extracts structured expense rows from tables."""
    all_expenses = []
    for table in tables:
        # Tables usually have: Description, Amount
        # Amount is typically the last column or contains numeric/currency markers
        for row in table.rows:
            if not row.cells:
                continue
                
            # Heuristic: Description is usually the first/longest cell
            # Amount is usually the last numeric cell
            cells = row.cells
            description = ""
            amount = ""
            
            # Find best amount candidate (numeric cell on the right)
            for i in range(len(cells)-1, -1, -1):
                cell_text = cells[i].text.strip().replace(",", "")
                # Remove currency symbols for check
                clean_text = cell_text.replace("Rs.", "").replace("$", "").strip()
                if clean_text.replace(".", "").isdigit():
                    amount = cell_text
                    # Description is everything to the left
                    description = " ".join(c.text for c in cells[:i]).strip()
                    break
            
            if description and amount:
                all_expenses.append({
                    "description": description,
                    "amount": amount,
                    "page": table.rows[0].cells[0].tokens[0].page if table.rows[0].cells and table.rows[0].cells[0].tokens else 1
                })
                
    return all_expenses
