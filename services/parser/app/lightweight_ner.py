"""Lightweight Named Entity Recognition for medical claims.

Uses keyword matching and heuristics only (no transformer models).

Recognizes:
- patient_name
- hospital_name  
- doctor_name
- diagnosis
- medicines
"""
from __future__ import annotations

import re
from typing import Any


def extract_patient_name(tokens: list[dict[str, Any]]) -> str | None:
    """Extract patient name from patient info section."""
    text = " ".join(t.get("text", "") for t in tokens[:30])
    
    # Look for "Patient Name:" or "Name:" pattern
    name_pattern = r"(?:patient\s+)?name\s*[:|\-]?\s*([A-Za-z\s\.]{3,50})"
    match = re.search(name_pattern, text, re.I)
    if match:
        name = match.group(1).strip()
        # Remove trailing colons, numbers, or dates
        name = re.sub(r"[:\d\-/\s]*$", "", name).strip()
        if name and len(name) > 2:
            return name
    return None


def extract_hospital_name(tokens: list[dict[str, Any]]) -> str | None:
    """Extract hospital name from hospitalization info section."""
    text = " ".join(t.get("text", "") for t in tokens[:50])
    
    # Look for "Hospital Name:" or "Hospital:" pattern
    hosp_pattern = r"(?:hospital\s+)?name\s*[:|\-]?\s*([A-Za-z\s\.\&,]{3,100})"
    match = re.search(hosp_pattern, text, re.I)
    if match:
        name = match.group(1).strip()
        name = re.sub(r"[:\d\-/\s]*$", "", name).strip()
        if name and len(name) > 2:
            return name
    
    # Fallback: look for "registered under" pattern
    reg_pattern = r"registered\s+under\s*[:|\-]?\s*([A-Za-z\s\.\&,]{3,100})"
    match = re.search(reg_pattern, text, re.I)
    if match:
        name = match.group(1).strip()
        name = re.sub(r"[:\d\-/\s]*$", "", name).strip()
        if name and len(name) > 2:
            return name
    
    return None


def extract_doctor_name(tokens: list[dict[str, Any]]) -> str | None:
    """Extract doctor/treating physician name."""
    text = " ".join(t.get("text", "") for t in tokens[:80])
    
    # Look for "Treating Doctor:" or "Physician:" pattern
    doc_patterns = [
        r"treating\s+doctor\s*[:|\-]?\s*([A-Za-z\s\.]{3,80})",
        r"physician\s*[:|\-]?\s*([A-Za-z\s\.]{3,80})",
        r"dr\.?\s+([A-Za-z\s\.]{3,80})",
    ]
    
    for pattern in doc_patterns:
        match = re.search(pattern, text, re.I)
        if match:
            name = match.group(1).strip()
            name = re.sub(r"[:\d\-/\s]*$", "", name).strip()
            if name and len(name) > 2:
                return name
    
    return None


def extract_diagnosis(tokens: list[dict[str, Any]]) -> str | None:
    """Extract primary diagnosis."""
    text = " ".join(t.get("text", "") for t in tokens)
    
    # Look for "Diagnosis:" or "Primary Diagnosis:" pattern
    diag_patterns = [
        r"(?:primary\s+)?diagnosis\s*[:|\-]?\s*([A-Za-z0-9\s\.,\-\(\)]{3,200}?)(?:\n|$|diagnosis|secondary)",
        r"icd-?10\s*[:|\-]?\s*([A-Z0-9\.\-]{3,100})?.*?([A-Za-z\s]{3,150})",
    ]
    
    for pattern in diag_patterns:
        match = re.search(pattern, text, re.I)
        if match:
            # Use last non-None group
            for i in range(match.lastindex or 0, 0, -1):
                diagnosis = (match.group(i) or "").strip()
                if diagnosis and len(diagnosis) > 2:
                    # Clean up
                    diagnosis = re.sub(r"[:\-/\s]*$", "", diagnosis).strip()
                    if diagnosis:
                        return diagnosis
    
    return None


def extract_medicines(tokens: list[dict[str, Any]]) -> list[str]:
    """Extract list of medicines from prescription/hospitalization section."""
    text = " ".join(t.get("text", "") for t in tokens)
    medicines: list[str] = []
    
    # Common medicine indicators and patterns
    common_medicines = {
        "paracetamol": r"\bparacetamol\b|\bacetaminophen\b|\btylenol\b|\bcalpol\b",
        "ibuprofen": r"\bibuprofen\b|\bbrufen\b",
        "aspirin": r"\baspirin\b|\baspirin\b",
        "amoxicillin": r"\bamoxicillin\b|\bamoxycillin\b",
        "ciprofloxacin": r"\bciprofloxacin\b|\bcipro\b",
        "cefixime": r"\bcefixime\b",
        "metformin": r"\bmetformin\b|\bglucophage\b",
        "lisinopril": r"\blisinopril\b|\bprinivil\b",
        "atorvastatin": r"\batorvastatin\b|\blipitor\b",
        "omeprazole": r"\bomeprazole\b|\bprilosec\b",
        "salbutamol": r"\bsalbutamol\b|\balbuterol\b",
        "doxycycline": r"\bdoxycycline\b",
        "metoprolol": r"\bmetoprolol\b|\blokren\b",
        "amlodipine": r"\bamlodipine\b|\bnorvasc\b",
        "insulin": r"\binsulin\b",
    }
    
    for medicine_name, pattern in common_medicines.items():
        if re.search(pattern, text, re.I):
            medicines.append(medicine_name.title())
    
    # Also look for generic medicine patterns: "Rx: Medicine Name"
    rx_pattern = r"(?:rx|medicine|drug|medication|tab|capsule|injection)\s*[:|\-]?\s*([A-Za-z\s\-\d\.]{3,80})"
    for match in re.finditer(rx_pattern, text, re.I):
        med = match.group(1).strip()
        if med and len(med) > 2 and med not in medicines:
            medicines.append(med.title())
    
    return list(set(medicines))  # Remove duplicates


def extract_ner_entities(
    patient_tokens: list[dict[str, Any]] | None = None,
    hospital_tokens: list[dict[str, Any]] | None = None,
    diagnosis_tokens: list[dict[str, Any]] | None = None,
    all_tokens: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Extract all NER entities from section tokens.
    
    Parameters
    ----------
    patient_tokens : list[dict], optional
        Tokens from patient info section
    hospital_tokens : list[dict], optional
        Tokens from hospitalization section
    diagnosis_tokens : list[dict], optional
        Tokens from diagnosis section
    all_tokens : list[dict], optional
        All page tokens (fallback for entity extraction)
    
    Returns
    -------
    dict with keys: patient_name, hospital_name, doctor_name, diagnosis, medicines
    """
    entities = {
        "patient_name": None,
        "hospital_name": None,
        "doctor_name": None,
        "diagnosis": None,
        "medicines": [],
    }
    
    if patient_tokens:
        entities["patient_name"] = extract_patient_name(patient_tokens)
    
    if hospital_tokens:
        entities["hospital_name"] = extract_hospital_name(hospital_tokens)
        entities["doctor_name"] = extract_doctor_name(hospital_tokens)
    
    if diagnosis_tokens:
        entities["diagnosis"] = extract_diagnosis(diagnosis_tokens)
    
    if all_tokens:
        entities["medicines"] = extract_medicines(all_tokens)
    
    return entities
