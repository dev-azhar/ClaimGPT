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
        elif table_type in {"expenses", "expense", "expense_table", "bill_table", "line_items"}:
            expenses.extend(rows)
        # Generic tables are intentionally not coerced into expenses.
    
    # Parser V2 Fallback: Extract structured rows from form_data if they exist
    import json
    v2_expenses = []
    for key, value in form_data.items():
        if key.startswith("expense_table_row_") and value:
            try:
                row_data = json.loads(value)
                if row_data not in v2_expenses:
                    v2_expenses.append(row_data)
            except:
                pass
    
    if v2_expenses:
        # If we have high-fidelity V2 expenses, they REPLACE the raw legacy table rows
        expenses = v2_expenses


    def get_field(flat_key, dot_key):
        return form_data.get(flat_key) or form_data.get(dot_key)

    # Calculate totals
    expense_total = 0.0
    for item in expenses:
        if isinstance(item, dict):
            amt = item.get("amount", 0.0)
            if isinstance(amt, str):
                try:
                    amt = float(amt.replace(",", "").replace("Rs.", "").replace("$", "").strip())
                except:
                    amt = 0.0
            expense_total += float(amt)

    canonical = {
        "patient": {
            "name": get_field("patient_name", "patient.name"),
            "date_of_birth": get_field("date_of_birth", "patient.date_of_birth"),
            "member_id": get_field("member_id", "patient.member_id"),
            "policy_number": get_field("policy_number", "insurance.policy_number"),
            "age": get_field("age", "patient.age"),
            "sex": get_field("sex", "patient.sex"),
            "address": get_field("address", "patient.address"),

        },
        "insurance": {
            "payer": get_field("payer", "insurance.payer"),
            "policy_number": get_field("policy_number", "insurance.policy_number"),
            "member_id": get_field("member_id", "insurance.member_id"),
        },
        "hospitalization": {
            "hospital_name": get_field("hospital_name", "hospitalization.hospital_name"),
            "admission_date": get_field("admission_date", "hospitalization.admission_date"),
            "discharge_date": get_field("discharge_date", "hospitalization.discharge_date"),
            "doctor_name": get_field("doctor_name", "hospitalization.doctor_name"),
        },
        "diagnosis": {
            "primary": get_field("diagnosis", "diagnosis.primary"),
            "secondary": get_field("secondary_diagnosis", "diagnosis.secondary"),
            "procedure": get_field("procedure", "diagnosis.procedure"),
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
            "claimed_total": get_field("claimed_total", "claims.claimed_total"),
            "calculated_total": expense_total,
            "total_amount": expense_total if expense_total > 0 else get_field("claimed_total", "claims.claimed_total"),
            "confidence": "HIGH",
        },

        "expenses": {
            "line_items": expenses,
            "item_count": len(expenses),
        },
        "sections": []  # Kept empty as layout regions are logical now
    }
    
    return canonical

