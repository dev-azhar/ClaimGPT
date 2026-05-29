from typing import Dict, Any, List
import re


_SUMMARY_EXPENSE_KEYWORDS = {
    "total",
    "grand total",
    "bill amount",
    "claim amount",
    "claimed amount",
    "amount claimed",
    "amount payable",
    "net amount",
    "final amount",
    "amount due",
    "sum insured",
}


def _is_summary_expense_row(item: Dict[str, Any]) -> bool:
    description = str(item.get("description") or item.get("desc") or item.get("name") or "").strip().lower()
    category = str(item.get("category") or "").strip().lower()

    if not description and not category:
        return False

    combined = f"{description} {category}".strip()
    return any(keyword in combined for keyword in _SUMMARY_EXPENSE_KEYWORDS)


_EXPENSE_TABLE_KEYWORDS = {"room", "nursing", "patient", "care", "charges", "ward", "bed", "room charges"}


def _looks_like_expense_table(table: Dict[str, Any]) -> bool:
    """Heuristic: detect generic tables that are actually expense/charge tables.

    Checks headers and row content for amount-like values or expense keywords.
    """
    headers = table.get("headers") or []
    headers_lc = [h.strip().lower() for h in headers if isinstance(h, str)]

    # header-based signals
    for h in headers_lc:
        if any(k in h for k in ("amount", "payable", "charges", "rate", "payable (rs", "amount (rs")):
            return True

    # row-based signals
    rows = table.get("structured_rows") or table.get("rows") or []
    amount_re = re.compile(r"\d{1,3}(?:[,\d]{0,2})*(?:\.\d{1,2})?")
    for r in rows:
        if isinstance(r, dict):
            # check description-like fields
            desc = str(r.get("description") or r.get("desc") or r.get("name") or "").lower()
            if any(k in desc for k in _EXPENSE_TABLE_KEYWORDS):
                return True

            # check numeric-like amount fields inside the row
            for v in r.values():
                try:
                    if isinstance(v, (int, float)):
                        return True
                    if isinstance(v, str) and amount_re.search(v.replace(" ", "")):
                        return True
                except Exception:
                    continue
        else:
            # row may be a list of cell texts
            for cell in r:
                if isinstance(cell, str) and amount_re.search(cell.replace(" ", "")):
                    return True

    return False


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
        # Some generic tables are actually expense/charge tables split across
        # pages (room/ward/nursing charges). Use a heuristic to include those.
        elif table_type in {"generic_table", "other"}:
            if _looks_like_expense_table(table):
                expenses.extend(rows)
    
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

    # Summary rows like "Bill Amount" / "Total" should not render as itemized
    # expenses in the report. Keep only genuine line items here; the total is
    # derived separately below.
    expenses = [item for item in expenses if not (isinstance(item, dict) and _is_summary_expense_row(item))]


    def get_field(flat_key, dot_key):
        return form_data.get(flat_key) or form_data.get(dot_key)

    # Calculate totals
    expense_total = 0.0
    for item in expenses:
        if isinstance(item, dict):
            amt = item.get("amount", 0.0)
            if isinstance(amt, str):
                try:
                    amt = float(amt.replace(",", "").replace("Rs.", "").replace("$", "").replace(" ", "").strip())
                except:
                    amt = 0.0
            expense_total += float(amt)


    patient_name = get_field("patient_name", "patient.name")
    if patient_name and isinstance(patient_name, str):
        import re
        patient_name = re.sub(r"\s+Relation\b.*$", "", patient_name, flags=re.I).strip()

    canonical = {
        "patient": {
            "name": patient_name,
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
            "patient_name": (re.sub(r"\s+Relation\b.*$", "", entities.get("patient_name"), flags=re.I).strip() if entities.get("patient_name") else None) if entities else None,
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

