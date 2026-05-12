from typing import Dict, Any, List

def build_canonical_schema(
    form_data: Dict[str, str],
    table_data: List[Dict[str, Any]],
    entities: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Converts extracted form fields and table rows into the final canonical JSON schema.
    
    Parameters
    ----------
    form_data : dict
        Extracted form fields (patient info, hospital info, etc.)
    table_data : list
        List of table dictionaries with "type" key indicating table category
        Possible types: "medications", "lab_results", "vitals", "diagnoses", "expenses"
    entities : dict, optional
        NER entities extracted from document
    
    Returns
    -------
    dict
        Canonical schema with all medical and claims data
    """
    
    # Separate tables by type
    medications = []
    lab_results = []
    vitals = []
    diagnoses = []
    expenses = []
    
    for table in table_data:
        table_type = table.get("type", "expenses")
        rows = table.get("structured_rows") or table.get("rows", [])
        
        if table_type == "medications":
            medications.extend(rows)
        elif table_type == "lab_results":
            lab_results.extend(rows)
        elif table_type == "vitals":
            vitals.extend(rows)
        elif table_type == "diagnoses":
            diagnoses.extend(rows)
        else:  # expenses, line_items, etc.
            expenses.extend(rows)
    
    # Calculate totals
    expense_total = sum(
        float(item.get("amount", 0.0))
        for item in expenses
        if isinstance(item, dict) and isinstance(item.get("amount"), (int, float))
    )
    
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
        "medical": {
            "diagnosis_tables": diagnoses,
            "medications": medications,
            "lab_results": lab_results,
            "vitals": vitals,
        },
        "medical_entities": {
            "patient_name": entities.get("patient_name") if entities else None,
            "hospital_name": entities.get("hospital_name") if entities else None,
            "doctor_name": entities.get("doctor_name") if entities else None,
            "diagnosis": entities.get("diagnosis") if entities else None,
            "medicines": entities.get("medicines") if entities else [],
        },
        "claims": {
            "claimed_total": None,  # Will rely on bottom-up calculation
            "calculated_total": expense_total,
            "total_amount": expense_total,
            "confidence": "HIGH",
        },
        "expenses": {
            "line_items": expenses,
            "item_count": len(expenses),
        },
        "sections": []  # Kept empty as layout regions are logical now
    }
    
    return canonical

