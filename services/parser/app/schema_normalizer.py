from typing import Dict, Any, List

def build_canonical_schema(form_data: Dict[str, str], table_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Converts extracted form fields and table rows into the final canonical JSON schema.
    This replaces _build_canonical_claim and all global regex heuristic output mapping.
    """
    total_amount = sum(item.get("amount", 0.0) for item in table_data)
    
    # Optional parsing for age string to int if needed, but keeping as string is safer 
    # based on the user's requirement ("Age: 29 Years").
    
    canonical = {
        "patient": {
            "name": form_data.get("patient_name"),
            "member_id": form_data.get("member_id"),
            "policy_number": form_data.get("policy_number"),
            "age": form_data.get("age"),
            "sex": form_data.get("sex"),
            "address": form_data.get("address"),
        },
        "insurance": {
            "payer": form_data.get("payer"),
            "policy_number": form_data.get("policy_number"),
            "member_id": form_data.get("member_id"),
        },
        "hospitalization": {
            "hospital_name": form_data.get("hospital_name"),
            "admission_date": form_data.get("admission_date"),
            "discharge_date": form_data.get("discharge_date"),
            "doctor_name": form_data.get("doctor_name"),
        },
        "diagnosis": {
            "primary": form_data.get("diagnosis"),
            "secondary": form_data.get("secondary_diagnosis"),
            "procedure": form_data.get("procedure"),
        },
        "claims": {
            "claimed_total": None, # Will rely strictly on bottom-up calculation
            "calculated_total": total_amount,
            "total_amount": total_amount,
            "confidence": "HIGH",
        },
        "expenses": {
            "line_items": table_data,
            "item_count": len(table_data),
        },
        "sections": [] # Kept empty as layout regions are logical now
    }
    
    return canonical
