import logging
import re
from typing import List, Dict, Any
from .models import FormField, TableRegion

logger = logging.getLogger("parser-debug")

CANONICAL_MAPPING = {
    "patient_name": "patient_name",
    "name": "patient_name",
    "patient": "patient_name",
    "date_of_birth": "patient_dob",
    "birth_date": "patient_dob",
    "dob": "patient_dob",
    "birth": "patient_dob",
    "age": "patient_age",
    "sex": "patient_gender",
    "gender": "patient_gender",
    "address": "patient_address",
    "policy_number": "insurance_policy_number",
    "policy_no": "insurance_policy_number",
    "policy": "insurance_policy_number",
    "insurance_provider": "insurance_payer",
    "payer": "insurance_payer",
    "provider": "insurance_payer",
    "hospital_name": "hospital_name",
    "hospital": "hospital_name",
    "admission_date": "admission_date",
    "admission": "admission_date",
    "discharge_date": "discharge_date",
    "discharge": "discharge_date",
    "doctor_name": "doctor_name",
    "doctor": "doctor_name",
    "diagnosis": "diagnosis",
    "claimed": "claimed_total",
    "total_claimed": "claimed_total",
    "amount_claimed": "claimed_total",
    "reg": "insurance_policy_number",
    "uid": "patient_id",
}

def normalize_fields(fields: List[FormField]) -> List[Dict[str, Any]]:
    """Maps geometric fields to canonical schema names."""
    normalized = []
    for field in fields:
        # Strip both colons and hyphens for robust mapping
        key_norm = field.key.lower().strip().replace(":", "").replace("-", "").replace(" ", "_")
        canonical_key = CANONICAL_MAPPING.get(key_norm)
        
        # Semantic disambiguation for "Name"
        if canonical_key == "patient_name" and field.value:
            val_lower = field.value.lower()
            hospital_keywords = ["hospital", "commission", "clinic", "center", "health", "medical center", "pharmacy"]
            if any(kw in val_lower for kw in hospital_keywords) and "ms." not in val_lower and "mr." not in val_lower:
                canonical_key = "hospital_name"

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
        for row in table.rows:
            if not row.cells:
                continue
                
            cells = row.cells
            description = ""
            amount = ""
            
            for i in range(len(cells)-1, -1, -1):
                cell_text = cells[i].text.strip().replace(",", "")
                amt_match = re.search(r"(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)", cell_text)
                if amt_match:
                    try:
                        val = float(amt_match.group(1).replace(",", ""))
                        if 0.5 < val < 1000000 and len(amt_match.group(1)) <= 12:
                            amount = cell_text
                            description = " ".join(c.text for c in cells[:i]).strip()
                            break
                    except ValueError:
                        continue

            if description and amount:
                desc_lower = description.lower()
                # Relaxed blacklist to prevent accidental exclusion of billed items
                blacklist = ["total", "sum insured", "requested", "previous claims", "policy status"]
                if any(kw in desc_lower for kw in blacklist):
                    continue
                
                category = "Miscellaneous"
                if any(kw in desc_lower for kw in ["room", "ward", "icu", "bed", "stay", "accommodation"]):
                    category = "Room Rent"
                elif any(kw in desc_lower for kw in ["consultation", "visit", "doctor", "specialist", "cons."]):
                    category = "Consultation"
                elif any(kw in desc_lower for kw in ["pharmacy", "medicine", "drug", "iv fluid", "phar", "med."]):
                    category = "Pharmacy"
                elif any(kw in desc_lower for kw in ["lab", "test", "blood", "panel", "investigation", "pathology"]):
                    category = "Laboratory"
                elif any(kw in desc_lower for kw in ["procedure", "surgery", "operation", "injection", "treatment", "proc."]):
                    category = "Procedure"
                elif any(kw in desc_lower for kw in ["nursing", "care"]):
                    category = "Nursing"
                elif any(kw in desc_lower for kw in ["consumable", "surgical", "glove", "mask", "cons."]):
                    category = "Consumables"
                elif any(kw in desc_lower for kw in ["service", "charge", "tax", "gst", "vat"]):
                    category = "Service Charges"

                all_expenses.append({
                    "description": description,
                    "amount": amount,
                    "category": category,
                    "page": table.rows[0].cells[0].tokens[0].page if table.rows[0].cells and table.rows[0].cells[0].tokens else 1
                })
                
    return all_expenses
