"""
Consolidated field and expense mappings for the ClaimGPT platform.

This module centralizes all field alias mappings, expense field definitions,
and normalization logic to avoid duplication across services.
"""

import re
from typing import Any


# ============================================================================
# FIELD ALIASES — Canonical field → parser field name variations
# ============================================================================
# Each canonical key maps to all known aliases (including spaces, underscores,
# and common abbreviations).

FIELD_ALIASES: dict[str, list[str]] = {
    # Core patient/policy info
    "patient_name": [
        "patient_name", "patient name", "patientname",
        "name", "patient full name", "full name",
    ],
    "policy_number": [
        "policy_number", "policy number", "policynumber",
        "policy_id", "policy id", "policyid",
        "policy", "member_id", "member id", "memberid",
    ],
    "patient_age": [
        "age", "patient_age", "patient age", "patientage",
        "patient_dob", "dob", "date_of_birth", "date of birth",
    ],
    "patient_gender": [
        "gender", "patient_gender", "patient gender", "sex",
        "patient_sex",
    ],
    
    # Dates
    "service_date": [
        "service_date", "service date", "servicedate",
        "dos", "date_of_service", "admission_date", "admission date",
        "date_of_admission", "doa", "discharge_date", "discharge date",
        "date_of_discharge", "dod",
    ],
    "admission_date": [
        "admission_date", "admission date", "admissiondate",
        "date_of_admission", "doa", "admitted_date",
    ],
    "discharge_date": [
        "discharge_date", "discharge date", "dischargedate",
        "date_of_discharge", "dod", "discharged_date",
    ],
    
    # Medical info
    "diagnosis": [
        "diagnosis", "primary_diagnosis", "primary diagnosis",
        "primary_diag", "primary diag", "chief_complaint",
        "chief complaint", "presenting_complaint",
    ],
    "secondary_diagnosis": [
        "secondary_diagnosis", "secondary diagnosis",
        "secondary_diag", "comorbidity", "comorbidities",
        "additional_diagnosis", "other_diagnosis",
    ],
    
    # Provider info
    "provider_name": [
        "provider_name", "provider name", "providername",
        "hospital_name", "hospital name", "hospitalname",
        "hospital", "facility_name", "facility name",
        "doctor_name", "doctor name", "docname", "treating_doctor",
        "treating doctor", "physician", "surgeon", "healthcare_provider",
    ],
    
    # Financial info
    "total_amount": [
        "total_amount", "total amount", "totalamount",
        "claimed_total", "claimed total", "claimed_amount",
        "claim_amount", "claim amount", "calculated_total",
        "net_amount", "net amount", "grand_total", "gross_total",
        "billed_amount", "billing_amount",
    ],
    "sum_insured": [
        "sum_insured", "sum insured", "suminsured",
        "cover_amount", "coverage_amount", "policy_limit",
        "sum_assured", "policy_sum", "sum_assured",
    ],
    
    # Ward/Room info
    "ward_type": [
        "ward_type", "ward type", "wardtype",
        "room_type", "room type", "roomtype",
        "room_category", "ward_category",
    ],
    
    # ========================================================================
    # EXPENSE / CHARGE FIELDS (for feature engineering & financial breakdown)
    # ========================================================================
    "room_charges": [
        "room_charges", "room charge", "room_charge",
        "room charges", "boarding_charges", "boarding charge",
        "room_fee", "room_rent",
    ],
    "consultation_charges": [
        "consultation_charges", "consultation charge", "consultation_charge",
        "consultation charges", "consultation_fee", "consultation_fees",
        "doctor_fee", "doctor_fees", "doctor fees",
    ],
    "surgeon_fees": [
        "surgeon_fees", "surgeon fee", "surgeon_fee",
        "surgeon charges", "surgeon_charges", "surgical_fee",
        "surgical fees", "professional_fees", "professional fees",
    ],
    "nursing_charges": [
        "nursing_charges", "nursing charge", "nursing_charge",
        "nursing charges", "nursing_fee", "nursing_fees",
        "nursing_support", "support_services",
    ],
    "ot_charges": [
        "ot_charges", "ot charge", "ot_charge",
        "ot charges", "operation_theatre", "operation theatre",
        "operation_theater", "theatre_charges",
    ],
    "surgery_charges": [
        "surgery_charges", "surgery charge", "surgery_charge",
        "surgery charges", "surgical_charges", "surgical charges",
        "surgical_charge", "procedure_charges",
    ],
    "anaesthesia_charges": [
        "anaesthesia_charges", "anaesthesia charge", "anaesthesia_charge",
        "anaesthesia charges", "anesthesia_charges", "anesthesia charges",
        "anaesthesia_fee", "anesthesia_fee", "anaesthesia fees",
    ],
    "laboratory_charges": [
        "laboratory_charges", "laboratory charge", "laboratory_charge",
        "laboratory charges", "lab_charges", "lab charges",
        "laboratory_fee", "lab_fee", "pathology_charges",
    ],
    "radiology_charges": [
        "radiology_charges", "radiology charge", "radiology_charge",
        "radiology charges", "imaging_charges", "imaging charges",
        "xray_charges", "ct_charges", "mri_charges",
    ],
    "investigation_charges": [
        "investigation_charges", "investigation charge", "investigation_charge",
        "investigation charges", "diagnostic_charges", "diagnostic charges",
        "diagnostics_charges", "tests_charges",
    ],
    "pharmacy_charges": [
        "pharmacy_charges", "pharmacy charge", "pharmacy_charge",
        "pharmacy charges", "medication_charges", "medication charges",
        "medicine_charges", "medicine charges", "drug_charges",
    ],
    "consumables": [
        "consumables", "consumable_charges", "consumable charges",
        "medical_consumables", "surgical_consumables",
        "supplies_charges", "materials_charges",
    ],
    "icu_charges": [
        "icu_charges", "icu charge", "icu_charge",
        "icu charges", "intensive_care_charges", "icu_fee",
        "critical_care_charges",
    ],
    "isolation_charges": [
        "isolation_charges", "isolation charge", "isolation_charge",
        "isolation charges", "isolation_fee", "quarantine_charges",
    ],
    "blood_charges": [
        "blood_charges", "blood charge", "blood_charge",
        "blood charges", "blood_transfusion_charges",
        "transfusion_charges", "blood_products",
    ],
    "physiotherapy_charges": [
        "physiotherapy_charges", "physiotherapy charge", "physiotherapy_charge",
        "physiotherapy charges", "physio_charges", "physio charges",
        "rehabilitation_charges", "therapy_charges",
    ],
    "chemotherapy_charges": [
        "chemotherapy_charges", "chemotherapy charge", "chemotherapy_charge",
        "chemotherapy charges", "chemo_charges", "chemo charges",
        "oncology_charges",
    ],
    "transplant_charges": [
        "transplant_charges", "transplant charge", "transplant_charge",
        "transplant charges", "stem_cell_charges", "organ_transplant",
    ],
    "ambulance_charges": [
        "ambulance_charges", "ambulance charge", "ambulance_charge",
        "ambulance charges", "ambulance_fee", "transportation_charges",
    ],
    "misc_charges": [
        "misc_charges", "misc charge", "misc_charge",
        "misc charges", "miscellaneous_charges", "miscellaneous charges",
        "miscellaneous_fee", "other_charges", "other charge",
    ],
    "implant_charges": [
        "implant_charges", "implant charge", "implant_charge",
        "implant charges", "prosthesis_charges", "prosthesis charges",
        "prosthetic_charges", "device_charges",
    ],
}


# ============================================================================
# EXPENSE FIELDS — All recognized expense categories with display labels
# ============================================================================

EXPENSE_FIELDS: dict[str, str] = {
    # Core charges
    "room_charges": "Room / Boarding Charges",
    "room_charge": "Room / Boarding Charges",
    
    # Medical professionals
    "consultation_charges": "Consultation Charges",
    "consultation_fee": "Consultation Charges",
    "surgeon_fees": "Surgeon & Professional Fees",
    "nursing_charges": "Nursing & Support Services",
    
    # Procedures & operations
    "ot_charges": "Operation Theatre Charges",
    "surgery_charges": "Surgery Charges",
    "surgery_charge": "Surgery Charges",
    "anaesthesia_charges": "Anaesthesia Charges",
    "anaesthesia_fee": "Anaesthesia Charges",
    
    # Diagnostics & treatment
    "laboratory_charges": "Laboratory Charges",
    "laboratory_charge": "Laboratory Charges",
    "radiology_charges": "Radiology & Imaging",
    "radiology_charge": "Radiology & Imaging",
    "investigation_charges": "Diagnostics & Investigations",
    "investigation_charge": "Diagnostics & Investigations",
    
    # Medications & consumables
    "pharmacy_charges": "Pharmacy & Medicines",
    "pharmacy_charge": "Pharmacy & Medicines",
    "medication_charges": "Pharmacy & Medicines",
    "consumables": "Medical & Surgical Consumables",
    
    # Specialized care
    "icu_charges": "ICU Charges",
    "isolation_charges": "Isolation Ward Charges",
    "blood_charges": "Blood Products & Bank",
    "physiotherapy_charges": "Physiotherapy Charges",
    "chemotherapy_charges": "Chemotherapy & Conditioning",
    "transplant_charges": "Stem Cell / Transplant Charges",
    
    # Transport & miscellaneous
    "ambulance_charges": "Ambulance Charges",
    "misc_charges": "Miscellaneous Charges",
    "implant_charges": "Implants / Prosthesis",
    "other_charges": "Other Charges",
}


# ============================================================================
# NORMALIZATION & HELPER FUNCTIONS
# ============================================================================

def normalize_field_name(raw_name: str) -> str:
    """
    Normalize a field name by:
    - Converting to lowercase
    - Replacing spaces with underscores
    - Removing extra whitespace
    - Removing common suffixes (e.g., _charges → _charge)
    
    Examples:
      "Patient Name" → "patient_name"
      "pharmacy charges" → "pharmacy_charges"
      "room charge" → "room_charges"
    """
    if not raw_name:
        return ""
    
    # Lowercase and strip
    normalized = raw_name.strip().lower()
    
    # Replace spaces and hyphens with underscores
    normalized = re.sub(r'[\s\-]+', '_', normalized)
    
    # Remove any non-alphanumeric characters except underscores
    normalized = re.sub(r'[^a-z0-9_]', '', normalized)
    
    return normalized


def resolve_field(
    field_map: dict[str, Any],
    canonical_key: str,
    normalize_keys: bool = True,
) -> Any | None:
    """
    Resolve a canonical field name to its value by checking all known aliases.
    
    Args:
        field_map: Dict of field names to values (keys should ideally be normalized)
        canonical_key: The canonical field key (e.g., "patient_name")
        normalize_keys: If True, normalize both the map keys and aliases before matching
    
    Returns:
        The first non-empty value found, or None if not present
    
    Example:
        >>> field_map = {"patient name": "John Doe", "age": "45"}
        >>> resolve_field(field_map, "patient_name")
        "John Doe"
    """
    if canonical_key not in FIELD_ALIASES:
        return None
    
    aliases = FIELD_ALIASES[canonical_key]
    
    if not normalize_keys:
        # Direct lookup (assumes keys are already normalized)
        for alias in aliases:
            val = field_map.get(alias)
            if val:
                return val
        return None
    
    # Normalize all keys in field_map for fuzzy matching
    normalized_map = {normalize_field_name(k): v for k, v in field_map.items()}
    
    # Try each alias (normalized)
    for alias in aliases:
        normalized_alias = normalize_field_name(alias)
        val = normalized_map.get(normalized_alias)
        if val:
            return val
    
    return None


def get_canonical_field(raw_field: str) -> str | None:
    """
    Given a raw field name (possibly with spaces or alternate forms),
    return the canonical field name (or None if not recognized).
    
    Examples:
        >>> get_canonical_field("Patient Name")
        "patient_name"
        >>> get_canonical_field("pharmacy_charges")
        None  # This is an expense field, not a canonical field
    """
    normalized = normalize_field_name(raw_field)
    
    for canonical, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if normalize_field_name(alias) == normalized:
                return canonical
    
    return None


def get_expense_label(field_name: str) -> str:
    """
    Get the human-readable display label for an expense field.
    
    Args:
        field_name: The expense field name (e.g., "pharmacy_charges")
    
    Returns:
        The display label, or the field name itself if not recognized
    
    Example:
        >>> get_expense_label("pharmacy_charges")
        "Pharmacy & Medicines"
    """
    normalized = normalize_field_name(field_name)
    
    # Try direct match first
    if field_name in EXPENSE_FIELDS:
        return EXPENSE_FIELDS[field_name]
    
    # Try normalized match
    for key, label in EXPENSE_FIELDS.items():
        if normalize_field_name(key) == normalized:
            return label
    
    # Fallback: return a readable version of the field name
    return field_name.replace("_", " ").title()


def get_all_expense_fields() -> dict[str, str]:
    """Return a copy of all expense fields with their display labels."""
    return EXPENSE_FIELDS.copy()


def get_canonical_expense_fields() -> set[str]:
    """
    Return the set of canonical (normalized) expense field names.
    Useful for validating whether a field is an expense field.
    """
    return {normalize_field_name(k) for k in EXPENSE_FIELDS.keys()}
