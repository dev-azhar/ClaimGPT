"""
Document Relevance Validator — verifies uploaded documents are:
1. Medical/health-related (not random files)
2. Related to the same patient across all claim documents
3. Support the claim being processed

Runs after OCR extraction, before downstream pipeline (parse, code, predict).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ocr.doc_validator")


# ═══════════════════════════════════════════════════════════════════════
# Document classification — what type of medical document is this?
# ═══════════════════════════════════════════════════════════════════════

_DOC_TYPE_PATTERNS: List[Tuple[str, str, re.Pattern]] = [
    # Hospital / clinical documents
    ("DISCHARGE_SUMMARY", "Discharge Summary", re.compile(
        r"\b(?:discharge\s+summary|discharge\s+report|final\s+summary|case\s+summary)\b", re.I)),
    ("ADMISSION_RECORD", "Admission Record", re.compile(
        r"\b(?:admission\s+(?:record|form|note|sheet)|indoor\s+case|case\s+paper|IP\s+record)\b", re.I)),
    ("PRESCRIPTION", "Prescription / Medication", re.compile(
        r"\b(?:prescription|Rx|medication\s+(?:list|order|chart)|drug\s+chart|treatment\s+sheet)\b", re.I)),
    ("LAB_REPORT", "Laboratory Report", re.compile(
        r"\b(?:lab(?:oratory)?\s+(?:report|test|result)|blood\s+(?:test|report)|CBC|LFT|KFT|RFT|"
        r"urine\s+(?:test|analysis|report)|pathology|hematology|biochemistry|culture\s+(?:report|sensitivity)|"
        r"serology|biopsy|histopath)\b", re.I)),
    ("RADIOLOGY_REPORT", "Radiology / Imaging Report", re.compile(
        r"\b(?:radiology|imaging\s+report|MRI\s+report|CT\s+report|X[\-\s]?Ray\s+report|"
        r"ultrasound\s+report|sonography|nuclear\s+medicine|PET|mammogra)\b", re.I)),
    ("SURGICAL_NOTE", "Operative / Surgical Note", re.compile(
        r"\b(?:operative?\s+(?:note|report|record|summary)|surgery\s+(?:note|report)|"
        r"pre[\-\s]?op|post[\-\s]?op|anesthesia\s+(?:note|record)|anaesthe)\b", re.I)),
    ("CONSULTATION", "Consultation Note", re.compile(
        r"\b(?:consultation|consult\s+note|specialist\s+(?:opinion|report)|referral\s+letter)\b", re.I)),
    ("BILL_INVOICE", "Hospital Bill / Invoice", re.compile(
        r"\b(?:hospital\s+bill|bill\s+(?:summary|detail)|invoice|receipt|payment|"
        r"charges|itemized\s+bill|final\s+bill|interim\s+bill|estimated\s+cost)\b", re.I)),
    ("INSURANCE_FORM", "Insurance / Claim Form", re.compile(
        r"\b(?:claim\s+form|insurance\s+(?:form|card|policy)|pre[\-\s]?auth|cashless|"
        r"TPA|third\s+party|reimbursement\s+form|policy\s+(?:number|document))\b", re.I)),
    ("ID_DOCUMENT", "Identity Document", re.compile(
        r"\b(?:aadhaar|aadhar|PAN\s+card|voter\s+ID|passport|driving\s+licen[sc]e|"
        r"photo\s+ID|identity\s+(?:card|proof|document))\b", re.I)),
    ("CONSENT_FORM", "Consent Form", re.compile(
        r"\b(?:consent\s+(?:form|document)|informed\s+consent|authorization\s+for\s+treatment)\b", re.I)),
    ("INVESTIGATION", "Investigation / Diagnostic Report", re.compile(
        r"\b(?:ECG|EEG|EMG|echocardiograph|spirometry|pulmonary\s+function|"
        r"endoscopy|colonoscopy|bronchoscopy|angiography)\b", re.I)),
]

# Medical / health document indicators (broad)
_MEDICAL_INDICATORS = re.compile(
    r"\b(?:patient|diagnosis|treatment|hospital|doctor|physician|dr\.|"
    r"medical|clinical|health|healthcare|disease|condition|symptom|"
    r"prescription|medication|admission|discharge|surgery|procedure|"
    r"insurance|claim|policy|TPA|reimbursement|cashless|"
    r"laboratory|lab\s+report|blood|urine|biopsy|pathology|"
    r"radiology|imaging|scan|MRI|CT|X[\-\s]?Ray|ultrasound|"
    r"ICD[\-\s]?10|CPT|diagnosis\s+code|procedure\s+code|"
    r"nursing|ward|ICU|OT|operation|anesthesia|"
    r"OPD|IPD|emergency|ER|casualty|ambulance|"
    r"pharmacy|drug|tablet|capsule|injection|IV|"
    r"vital|temperature|blood\s+pressure|BP|pulse|SPO2|"
    r"allergy|allergi|immuniz|vaccin|"
    r"bill|invoice|charges|amount|receipt|payment|"
    r"DOB|date\s+of\s+birth|age|gender|sex|male|female|"
    r"registration|MRN|UHID|patient\s+ID|IP\s+no)\b",
    re.I,
)

# Non-medical document indicators
_NON_MEDICAL_INDICATORS = re.compile(
    r"\b(?:curriculum\s+vitae|resume|job\s+application|employment|"
    r"real\s+estate|property|deed|mortgage|rent|lease|tenancy|"
    r"invoice\s+for\s+(?:electronics|software|hardware|furniture)|"
    r"restaurant|food\s+order|delivery|shopping|"
    r"travel\s+itinerary|flight\s+booking|hotel\s+reservation|"
    r"academic|transcript|degree|university\s+(?!hospital)|semester|"
    r"tax\s+return|GST\s+return|ITR|income\s+tax|"
    r"legal\s+notice|court\s+order|FIR|police)\b",
    re.I,
)


# ═══════════════════════════════════════════════════════════════════════
# Patient identity extraction — pull patient identifiers from text
# ═══════════════════════════════════════════════════════════════════════

_PATIENT_NAME_PATTERNS = [
    re.compile(r"(?:patient\s*(?:name)?)\s*[:\-]?\s*([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){1,3})", re.I),
    re.compile(r"(?:patient|pt)\s*[:\-]\s*([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){1,3})", re.I),
    re.compile(r"(?:Mr\.|Mrs\.|Ms\.|Shri|Smt\.?|Master)\s+([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){1,3})", re.I),
]

_PATIENT_ID_PATTERNS = [
    re.compile(r"(?:patient\s*ID|PID|MRN|UHID|IP\s*(?:No|Number)|registration\s*(?:no|number))\s*[:\-]?\s*([A-Z0-9\-/]{3,20})", re.I),
    re.compile(r"(?:case\s*no|admission\s*no|bed\s*no)\s*[:\-]?\s*([A-Z0-9\-/]{3,20})", re.I),
]

_DOB_PATTERNS = [
    re.compile(r"(?:DOB|date\s*of\s*birth|birth\s*date)\s*[:\-]?\s*(\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4})", re.I),
    re.compile(r"(?:DOB|date\s*of\s*birth)\s*[:\-]?\s*(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{2,4})", re.I),
]

_AGE_PATTERN = re.compile(
    r"(?:age(?:\s*[/&]\s*gender)?)\s*[:\-]?\s*(\d{1,3})\s*(?:[/\s]*(?:male|female|m|f)|yrs?|years?|y/?o)?", re.I,
)

_GENDER_PATTERN = re.compile(
    r"(?:sex|gender|age\s*[/&]\s*gender)\s*[:\-]?\s*(?:\d{1,3}\s*[/\s]\s*)?(male|female|m|f|other)\b", re.I,
)

_POLICY_PATTERN = re.compile(
    r"(?:policy\s*(?:no|number|id)|insurance\s*(?:no|number|id)|member\s*(?:no|id))\s*[:\-]?\s*([A-Z0-9\-/]{4,25})", re.I,
)


@dataclass
class PatientIdentity:
    """Extracted patient identifiers from a single document."""
    name: Optional[str] = None
    patient_id: Optional[str] = None
    dob: Optional[str] = None
    age: Optional[str] = None
    gender: Optional[str] = None
    policy_number: Optional[str] = None

    @property
    def has_identifiers(self) -> bool:
        return any([self.name, self.patient_id, self.dob, self.policy_number])


@dataclass
class DocumentValidation:
    """Validation result for a single document."""
    document_id: str
    file_name: str
    doc_type: str
    doc_type_label: str
    is_medical: bool
    is_relevant: bool
    patient_match: str  # MATCH | MISMATCH | UNCERTAIN | NO_DATA
    confidence: float
    issues: List[str] = field(default_factory=list)
    patient_identity: Optional[PatientIdentity] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> str:
        if not self.is_medical:
            return "INVALID"
        if self.patient_match == "MISMATCH":
            return "INVALID"
        if not self.is_relevant:
            return "WARNING"
        return "VALID"


@dataclass
class ClaimValidationResult:
    """Aggregated validation across all documents in a claim."""
    claim_id: str
    total_documents: int
    valid_count: int
    invalid_count: int
    warning_count: int
    primary_patient: Optional[PatientIdentity] = None
    documents: List[DocumentValidation] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.invalid_count == 0

    @property
    def status(self) -> str:
        if self.invalid_count > 0:
            return "INVALID"
        if self.warning_count > 0:
            return "WARNING"
        return "VALID"


# ═══════════════════════════════════════════════════════════════════════
# Core functions
# ═══════════════════════════════════════════════════════════════════════

def classify_document(text: str, file_name: str) -> Tuple[str, str]:
    """Classify document type based on OCR text and filename.
    Returns (doc_type_code, doc_type_label)."""
    # Check filename hints first
    name_lower = file_name.lower()
    for code, label, pattern in _DOC_TYPE_PATTERNS:
        if pattern.search(name_lower):
            return code, label

    # Check text content
    for code, label, pattern in _DOC_TYPE_PATTERNS:
        if pattern.search(text):
            return code, label

    return "UNKNOWN", "Unclassified Document"


def is_medical_document(text: str, file_name: str) -> Tuple[bool, float, List[str]]:
    """Check if the document is medical/health related.
    Returns (is_medical, confidence, issues)."""
    issues: List[str] = []

    if not text or len(text.strip()) < 20:
        return False, 0.0, ["Document has insufficient text content"]

    text_sample = text[:5000]  # Limit analysis to first 5000 chars

    medical_hits = len(_MEDICAL_INDICATORS.findall(text_sample))
    non_medical_hits = len(_NON_MEDICAL_INDICATORS.findall(text_sample))

    # Normalize by text length (per 1000 chars)
    text_len = max(len(text_sample), 1)
    medical_density = (medical_hits / text_len) * 1000
    non_medical_density = (non_medical_hits / text_len) * 1000

    # Decision logic
    if non_medical_hits > 0 and non_medical_density > medical_density:
        issues.append(f"Document appears non-medical: {non_medical_hits} non-medical indicators found")
        return False, min(non_medical_density / 5, 0.95), issues

    if medical_hits == 0:
        issues.append("No medical/health indicators found in document text")
        return False, 0.1, issues

    if medical_density < 2.0:
        # Very low medical content density
        issues.append("Very low medical content density — document may not be health-related")
        return False, 0.3, issues

    if medical_density < 5.0:
        issues.append("Low medical content density — verify document relevance")
        return True, 0.6, issues

    return True, min(0.5 + medical_density / 20, 0.98), []


def extract_patient_identity(text: str) -> PatientIdentity:
    """Extract patient identifiers from OCR text."""
    identity = PatientIdentity()

    text_sample = text[:8000]  # First 8000 chars typically have demographics

    # Patient name
    for pattern in _PATIENT_NAME_PATTERNS:
        m = pattern.search(text_sample)
        if m:
            name = m.group(1).strip()
            # Basic validation: should be 2-60 chars, not all caps gibberish
            if 2 <= len(name) <= 60 and not re.match(r"^[A-Z]{10,}$", name):
                identity.name = name
                break

    # Patient ID / MRN
    for pattern in _PATIENT_ID_PATTERNS:
        m = pattern.search(text_sample)
        if m:
            identity.patient_id = m.group(1).strip()
            break

    # DOB
    for pattern in _DOB_PATTERNS:
        m = pattern.search(text_sample)
        if m:
            identity.dob = m.group(1).strip()
            break

    # Age
    m = _AGE_PATTERN.search(text_sample)
    if m:
        age_val = m.group(1)
        if 0 < int(age_val) < 150:
            identity.age = age_val

    # Gender
    m = _GENDER_PATTERN.search(text_sample)
    if m:
        g = m.group(1).upper()
        identity.gender = "Male" if g in ("M", "MALE") else "Female" if g in ("F", "FEMALE") else g

    # Policy number
    m = _POLICY_PATTERN.search(text_sample)
    if m:
        identity.policy_number = m.group(1).strip()

    return identity


def _normalize_name(name: Optional[str]) -> str:
    """Normalize a name for comparison."""
    if not name:
        return ""
    # Remove titles, extra spaces, lowercase
    cleaned = re.sub(r"\b(?:Mr|Mrs|Ms|Dr|Shri|Smt|Master|Baby|Miss)\b\.?", "", name, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    return cleaned


def _names_match(name1: Optional[str], name2: Optional[str]) -> Tuple[bool, float]:
    """Check if two patient names match with fuzzy tolerance.
    Returns (is_match, confidence)."""
    n1 = _normalize_name(name1)
    n2 = _normalize_name(name2)

    if not n1 or not n2:
        return False, 0.0

    # Exact match
    if n1 == n2:
        return True, 1.0

    # One name is a subset of the other (handles partial names)
    if n1 in n2 or n2 in n1:
        return True, 0.85

    # Split into tokens and check overlap
    tokens1 = set(n1.split())
    tokens2 = set(n2.split())
    if not tokens1 or not tokens2:
        return False, 0.0

    overlap = tokens1 & tokens2
    union = tokens1 | tokens2
    jaccard = len(overlap) / len(union)

    # At least half the name tokens must match
    if jaccard >= 0.5:
        return True, jaccard

    # First + last name match (common in Indian names with middle name differences)
    t1 = sorted(tokens1)
    t2 = sorted(tokens2)
    if len(t1) >= 2 and len(t2) >= 2:
        if t1[0] == t2[0] and t1[-1] == t2[-1]:
            return True, 0.80

    return False, jaccard


def match_patient_across_documents(
    identities: List[Tuple[str, PatientIdentity]]
) -> Tuple[Optional[PatientIdentity], List[Tuple[str, str, float]]]:
    """Match patient identity across all documents.

    Args:
        identities: List of (document_id, PatientIdentity) pairs

    Returns:
        (primary_identity, list of (doc_id, status, confidence))
        where status is MATCH | MISMATCH | UNCERTAIN | NO_DATA
    """
    # Find the "primary" identity — the one with the most complete info
    scored: List[Tuple[int, PatientIdentity, str]] = []
    for doc_id, ident in identities:
        score = 0
        if ident.name:
            score += 3
        if ident.patient_id:
            score += 3
        if ident.dob:
            score += 2
        if ident.policy_number:
            score += 2
        if ident.age:
            score += 1
        if ident.gender:
            score += 1
        scored.append((score, ident, doc_id))

    if not scored:
        return None, []

    scored.sort(key=lambda x: x[0], reverse=True)
    primary = scored[0][1]

    # If primary has no identifiers at all, return uncertain
    if not primary.has_identifiers:
        return None, [(doc_id, "NO_DATA", 0.0) for _, _, doc_id in scored]

    results: List[Tuple[str, str, float]] = []
    for _, ident, doc_id in scored:
        if not ident.has_identifiers:
            results.append((doc_id, "NO_DATA", 0.0))
            continue

        match_score = 0.0
        checks = 0

        # Name match (strongest signal)
        if primary.name and ident.name:
            is_match, conf = _names_match(primary.name, ident.name)
            match_score += conf * 3
            checks += 3
            if not is_match and conf < 0.3:
                results.append((doc_id, "MISMATCH", conf))
                continue

        # Patient ID match
        if primary.patient_id and ident.patient_id:
            if primary.patient_id.upper() == ident.patient_id.upper():
                match_score += 3
            else:
                # Different patient ID is a strong mismatch signal
                results.append((doc_id, "MISMATCH", 0.1))
                continue
            checks += 3

        # DOB match
        if primary.dob and ident.dob:
            if primary.dob == ident.dob:
                match_score += 2
            checks += 2

        # Policy match
        if primary.policy_number and ident.policy_number:
            if primary.policy_number.upper() == ident.policy_number.upper():
                match_score += 2
            checks += 2

        # Gender match
        if primary.gender and ident.gender:
            if primary.gender == ident.gender:
                match_score += 1
            checks += 1

        if checks == 0:
            results.append((doc_id, "UNCERTAIN", 0.5))
        else:
            confidence = match_score / checks
            if confidence >= 0.7:
                results.append((doc_id, "MATCH", confidence))
            elif confidence >= 0.4:
                results.append((doc_id, "UNCERTAIN", confidence))
            else:
                results.append((doc_id, "MISMATCH", confidence))

    return primary, results


def validate_claim_documents(
    documents: List[Dict[str, Any]],
    claim_id: str,
) -> ClaimValidationResult:
    """Validate all documents in a claim for medical relevance and patient consistency.

    Args:
        documents: List of dicts with keys: document_id, file_name, text (OCR text)
        claim_id: The claim UUID

    Returns:
        ClaimValidationResult with per-document and aggregate validation
    """
    validations: List[DocumentValidation] = []
    identities: List[Tuple[str, PatientIdentity]] = []

    # Phase 1: Classify and check each document individually
    for doc in documents:
        doc_id = doc["document_id"]
        file_name = doc.get("file_name", "")
        text = doc.get("text", "")

        # Classify document type
        doc_type, doc_type_label = classify_document(text, file_name)

        # Check if medical
        is_medical, med_confidence, med_issues = is_medical_document(text, file_name)

        # Extract patient identity
        identity = extract_patient_identity(text)
        identities.append((doc_id, identity))

        validations.append(DocumentValidation(
            document_id=doc_id,
            file_name=file_name,
            doc_type=doc_type,
            doc_type_label=doc_type_label,
            is_medical=is_medical,
            is_relevant=True,  # Will update in Phase 2
            patient_match="PENDING",
            confidence=med_confidence,
            issues=med_issues,
            patient_identity=identity,
            metadata={
                "text_length": len(text),
                "doc_type": doc_type,
            },
        ))

    # Phase 2: Cross-document patient matching
    primary_identity, match_results = match_patient_across_documents(identities)

    # Build lookup
    match_lookup: Dict[str, Tuple[str, float]] = {}
    for doc_id, status, conf in match_results:
        match_lookup[doc_id] = (status, conf)

    claim_issues: List[str] = []
    valid_count = 0
    invalid_count = 0
    warning_count = 0

    for v in validations:
        # Update patient match from Phase 2
        pmatch, pconf = match_lookup.get(v.document_id, ("UNCERTAIN", 0.5))
        v.patient_match = pmatch

        if pmatch == "MISMATCH":
            v.is_relevant = False
            v.issues.append(
                f"Patient identity mismatch — this document may belong to a different patient"
            )
            if primary_identity and primary_identity.name and v.patient_identity and v.patient_identity.name:
                v.issues.append(
                    f"Expected patient: '{primary_identity.name}', found: '{v.patient_identity.name}'"
                )

        # Compute final confidence as average
        v.confidence = (v.confidence + pconf) / 2 if pconf > 0 else v.confidence

        # Count by status
        status = v.status
        if status == "VALID":
            valid_count += 1
        elif status == "INVALID":
            invalid_count += 1
            claim_issues.append(f"'{v.file_name}' — {'; '.join(v.issues)}")
        else:
            warning_count += 1

    if invalid_count > 0:
        claim_issues.insert(0, f"{invalid_count} document(s) failed validation")

    return ClaimValidationResult(
        claim_id=claim_id,
        total_documents=len(validations),
        valid_count=valid_count,
        invalid_count=invalid_count,
        warning_count=warning_count,
        primary_patient=primary_identity,
        documents=validations,
        issues=claim_issues,
    )
