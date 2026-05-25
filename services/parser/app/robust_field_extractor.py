"""
Robust local field extraction using comprehensive regex patterns.
Scans ENTIRE document for patient/claim details WITHOUT sending data to LLM.
Handles multiple formats and variations consistently.
"""
from typing import Any, Dict, Optional, List
import re
from datetime import datetime

logger_name = "parser-debug"


class RobustFieldExtractor:
    """Extract patient and claim details using regex patterns only - NO LLM."""

    # Comprehensive regex patterns for each field
    PATTERNS = {
        "patient_name": [
            # Format: "Patient Name: John Doe"
            r"(?im)^\s*(?:patient\s+name|name\s+of\s+patient|name\s+of\s+the\s+patient)\s*[:\-=|]?\s*([^\n|]+)\s*(?:\||$)",
            # Format: "Patient Rajesh Patel" or "Mr. Robert Wilson"
            r"(?im)\b(?:mr\.?|mrs\.?|ms\.?|miss)[ \t]+([A-Z][A-Za-z.'’\-]+(?:[ \t]+[A-Z][A-Za-z.'’\-]+){1,4})\b",
            # Format: "patient Jennifer Davis aged 48 years"
            r"(?im)\bpatient[ \t]+([A-Z][A-Za-z.'’\-]+(?:[ \t]+[A-Z][A-Za-z.'’\-]+){1,4})\b",
            # Format: "Name of the patient: John Doe"
            r"(?im)^\s*name\s*[:\-=|]?\s*(?!of\s+hospital)(?:Mr\.?\s*|Mrs\.?\s*|Ms\.?\s*)?([^\n|]+)\s*(?:\||$)",
            # Format: "Name: John Doe" or "Name - John Doe" (line-based)
            r"(?im)^\s*patient\s*[:\-=|]\s*(?!name\b)(?:Mr\.?\s+|Mrs\.?\s+|Ms\.?\s+)?([^\n|]+)\s*(?:\||$)",
            # Format: "Patient - Mr. John Doe" or "Patient: John Doe"
            r"(?im)^\s*member\s+name\s*[:\-=|]?\s*(?:Mr\.?\s*|Mrs\.?\s*|Ms\.?\s*)?([^\n|]+)\s*(?:\||$)",
        ],
        
        "age": [
            # Age/Gender combination (common in headers)
            r"(?im)\bage\s*/\s*(?:gender|sex)\s*[:\-=|]?\s*(\d{1,3})",
            # Format: "Age: 45" or "Age: 45 years" or "Age: 45 yrs"
            r"(?im)^\s*age\s*[:\-=|]?\s*(\d{1,3})(?:\s*(?:years?|yrs?))?\b",
            # OCR variants like "Agez 21 Years" or "Age- 29 Years"
            r"(?im)\bagez?\s*[:\-=|]?\s*(\d{1,3})\s*(?:years?|yrs?)\b",
            # Format: "Age/Sex: 45/M"
            r"(?im)^\s*age\s*/\s*sex\s*[:\-=|]?\s*(\d{1,3})/",
            # "29 Years Bill No. Sex- FEMALE" style lines
            r"(?im)^.*?\b(\d{1,3})\s*(?:years?|yrs?)\b.*?\bsex\b.*$",
            # Format in paragraph: "aged 45" or "aged 45 years"
            r"aged\s+(\d{1,3})(?:\s*(?:years?|yrs?))?",
            # Format: "45-year-old" or "45 year old"
            r"(\d{1,3})\s*-?\s*year\s*-?old",
        ],
        
        "gender": [
            # Format: "Gender: Male" or "Sex: Female" or "M/F"
            r"(?im)^\s*(?:gender|sex)\s*[:\-=|]?\s*([MFmf]|male|female|Male|Female)\b",
            # OCR variants like "Sex- FEMALE" anywhere on the line
            r"(?im)\bsex\s*[:\-=|]?\s*([MFmf]|male|female|Male|Female)\b",
            # Format: "Age/Sex: 55/M"
            r"(?im)^\s*age\s*/\s*sex\s*[:\-=|]?\s*\d{1,3}\s*/\s*([MFmf])\b",
            # Format: "45/M" (Age/Sex)
            r"(?im)^\s*\d{1,3}\s*/\s*([MFmf])\b",
            # Format: "She is female" or "is male"
            r"(?:she\s+|he\s+)?is\s+(?:a\s+)?([Mm]ale|[Ff]emale|[MF])\b",
            # Format: standalone "male" or "female" or "Male" or "Female" at word boundary
            r"\b([Mm]ale|[Ff]emale)\b",
        ],
        
        "admission_date": [
            # Wrapped date format: "Date of \n Admission"
            r"(?im)date\s+of\s*[:\-=\/|]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})[^\n]*\n\s*admission",
            # Format: "Admission Date: 15-05-2025" or "Admitted on: 15-05-2025"
            r"(?im)^\s*(?:admission\s+date|admitted\s+on|date\s+of\s+admission|doa)\s*[:\-=|]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
            # Narrative format: "was admitted on 12-01-2025"
            r"(?im)\badmitted\s+on\s+(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
            # Format: "admission date was 15-05-2025"
            r"admission\s+date\s+was\s+(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
            # Format: "Adm Date: 15-May-2025"
            r"adm\s+date\s*[:\-=]?\s*(\d{1,2}[-/](?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[-/]\d{2,4})",
            # Format: "Admitted: 15-05-2025"
            r"admitted\s*[:\-=]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
        ],
        
        "discharge_date": [
            # Wrapped date format: "Date of \n Discharge"
            r"(?im)date\s+of\s*[:\-=\/|]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})[^\n]*\n\s*discharge",
            # Format: "Discharge Date: 20-05-2025"
            r"(?im)^\s*(?:discharge\s+date|discharged\s+on|date\s+of\s+discharge|dod)\s*[:\-=|]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
            # Narrative format: "and discharged on 18-01-2025"
            r"(?im)\bdischarged\s+on\s+(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
            # Format: "discharge was 20-05-2025" 
            r"discharge\s+was\s+(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
            # Format: "Disch Date: 20-May-2025"
            r"disch\s+date\s*[:\-=]?\s*(\d{1,2}[-/](?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[-/]\d{2,4})",
            # Format: "Discharged: 20-05-2025"
            r"discharged\s*[:\-=]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
        ],
        
        "doctor_name": [
            # Format: "Consultant: Dr. Karthik Dey" or "Doctor: Dr. John Smith"
            r"(?im)^\s*(?:doctor|physician|treating\s+doctor|treating\s+consultant|consultant|treating\s+by|treated\s+by|attended\s+by)\s*[:\-=|]?\s*(?:dr\.?\s+)?([A-Z][A-Za-z\.'-]+(?:\s+[A-Z][A-Za-z\.'-]+){0,3})\b",
            # Format: "Dr. John Smith" standalone (must have Dr. prefix)
            r"(?im)\bdr\.?\s+([A-Z][A-Za-z\.'-]+(?:\s+[A-Z][A-Za-z\.'-]+)*)\b",
            # Format: "Signature of Dr. John Smith" or "As per Dr. Name"
            r"(?im)(?:signature\s+of|as\s+per|as\s+authenticated\s+by|as\s+certified\s+by)\s+(?:dr\.?\s+)?([A-Z][A-Za-z\.'-]+(?:\s+[A-Z][A-Za-z\.'-]+){0,2})\b",
        ],
        
        "hospital_name": [
            # Standalone hospital name in header without prefix
            r"(?im)^\s*([A-Za-z0-9][A-Za-z0-9\s.,&'\-]{3,80}\b(?:Hospital|Hospitals|Medical\s+Center|Medical\s+Centre|Healthcare|Clinic|Sanatorium|Nursing\s+Home|Maternity\s+Home|Netaralay))\s*$",
            # Format: "Hospital Name: XYZ Medical Center" (line-based)
            r"(?im)^\s*(?:hospital\s+name|name\s+of\s+hospital)\s*[:\-=|]?\s*([^\n|]{5,150})\s*(?:\||$)",
            # Format: "Hospital - Apollo Healthcare" (strict: require Hospital keyword)
            r"(?im)^\s*hospital\s*[:\-=|]?\s*([^\n|]{5,150})\s*(?:\||$)",
            # Format: "DISCHARGE SUMMARY XYZ Hospital, Tel: ..." - capture before comma (same line)
            r"(?im)^\s*(?:discharge\s+summary|facility|from)[ \t]+([A-Z][^\n,|]{8,150}?)(?:,\s*tel\b|\s*tel\b|,|\||$)",
            # Format: first header line with claim ref, e.g. "Baystate Wing Hospital Corporation | Claim Ref: ..."
            r"(?im)^\s*([A-Z][^\n|]{8,120}?\b(?:Hospital|Hospitals|Medical Center|Medical Centre|Healthcare|Clinic|Corporation))\s*\|\s*(?:Claim Ref|Member|Policy)",
            # Format: "treating hospital: Cleveland Medical Center" or "Hospitalized at: ..."
            r"(?im)(?:treating\s+)?hospital(?:\s+of\s+treatment)?\s*[:\-=]\s*([^\n\.]{8,120}(?:Hospital|Hospitals|Medical Center|Medical Centre|Healthcare|Clinic|Corporation))",
            # Format: "Patient treated at XYZ Hospital" (require Hospital keyword at end)
            r"(?im)\b(?:treated|admitted|hospitalized)\s+(?:at|in)\s+([A-Z][^\n\.]{8,120}(?:Hospital|Hospitals|Medical Center|Medical Centre|Clinic|Corporation))\b",
        ],
        
        "diagnosis": [
            # Format: "Diagnosis: Acute Myocardial Infarction"
            r"(?im)^\s*(?:primary\s+)?diagnosis\s*[:\-=|]?\s*([^\n|]{3,200})\s*(?:\||$)",
            # OCR variants where diagnosis appears mid-line (strict: require 3+ chars)
            r"(?im)\bdiagnosis\s*[:\-=|]?\s*([^\n|]{3,200})\s*(?:\||$)",
            # Format: "Final Diagnosis: ..."
            r"(?im)^\s*final\s+diagnosis\s*[:\-=|]?\s*([^\n|]{3,200})\s*(?:\||$)",
            # Format: "Clinical Diagnosis: ..." or "Primary Diagnosis: ..."
            r"(?im)^\s*(?:clinical|primary|chief)\s+diagnosis\s*[:\-=|]?\s*([^\n|]{3,200})\s*(?:\||$)",
            # Format: "Patient discharged with diagnosis of Pneumonia"
            r"(?im)\b(?:discharged\s+with\s+)?diagnosis\s+(?:of\s+)?([^\n\.]{3,200})(?:\s+(?:icd-?\d+|code:|managed|treated)\b|\.|\n|$)",
            # Format: within "CLINICAL SUMMARY" section
            r"(?im)^\s*clinical\s+summary\s*[:\-=|]?\s*(?:[^\n]*\n)?\s*([A-Z][^\n|]{3,200})\s*(?:\||$)",
        ],

        "claimed_total": [
            # Multi-line: total keyword then optional whitespace/newline then amount
            r"(?im)(?:gross\s+hospital\s+bill|total\s+billed\s+amount|total\s+claimed\s+amount|claimed\s+total|total\s+claimed|bill\s+amount|total\s+amount|total\s+bill|net\s+bill|billed\s+amount|gross\s+total)\s*\n?\s*(?:rs\.?|inr|₹)?\s*[:\-=\/|]?\s*([0-9]+(?:\s*,\s*[0-9]+)*(?:\s*\.\s*[0-9]+)?)",
            # Simple line-start total
            r"(?im)^\s*total\s*\n?\s*(?:rs\.?|inr|₹)?\s*([0-9]+(?:\s*,\s*[0-9]+)*(?:\s*\.\s*[0-9]+)?)",
            # Total: Rs. XXXX on same line
            r"(?im)(?:total|grand\s+total|net\s+amount)\s*[:\-]?\s*(?:rs\.?|inr|₹)?\s*([0-9]+(?:\s*,\s*[0-9]+)*(?:\s*\.\s*[0-9]+)?)",
        ],
    }

    HOSPITAL_REJECT_TERMS = {
        "expense",
        "breakdown",
        "claim",
        "risk",
        "classification",
        "signature",
        "seal",
        "form",
        "summary",
        "original copy",
        "copy",
        "duplicate",
        "certified true",
        "office copy",
        "patient copy",
    }

    PATIENT_REJECT_TERMS = {
        "information",
        "date",
        "age",
        "gender",
        "sex",
        "diagnosis",
        "hospital",
        "doctor",
        "claim",
        "summary",
        "discharge",
        "admission",
        "ipd",
        "reg",
    }

    DOCTOR_REJECT_TERMS = {
        "doctor",
        "referring",
        "consultant",
        "treating",
        "hereby",
        "declare",
        "information",
        "furnished",
        "above",
        "true",
        "correct",
    }

    DIAGNOSIS_REJECT_TERMS = {
        "count",
        "documented",
        "risk",
        "factor",
        "claim",
        "total",
        "expense",
        "breakdown",
        "sum insured",
    }

    @staticmethod
    def _clean_text(value: str) -> str:
        """Clean extracted value: remove trailing punctuation, dates, numbers."""
        if not value:
            return ""
        
        # Remove trailing punctuation
        value = re.sub(r"[:\-=,\.]*$", "", value).strip()
        # Remove trailing numbers and dates (common OCR artifacts)
        value = re.sub(r"\s+\d{1,2}[-/]\d{1,2}[-/]\d{4}$", "", value).strip()
        value = re.sub(r"\s+\d+$", "", value).strip()
        # Clean up HTML/formatting artifacts
        value = re.sub(r"<[^>]+>", "", value).strip()
        
        return value

    @staticmethod
    def _clean_person_name(value: str) -> str:
        """Strip OCR noise, honorifics, and embedded digits from a person name."""
        if not value:
            return ""

        value = re.sub(r"\b(?:mr|mrs|ms|miss)\.?[:\-]?\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\b(?:dr)\.?[:\-]?\s*", "", value, flags=re.IGNORECASE)

        cutoff_terms = {
            "hereby", "declare", "that", "the", "information", "furnished", "above",
            "is", "true", "and", "correct", "was", "admitted", "to", "on", "at",
            "patient", "name", "ipd", "reg", "no", "bill", "date", "age", "sex",
            "relation", "relative", "relationship",
        }

        parts = []
        for token in value.split():
            if token.strip(" ,;:|.-").lower() in cutoff_terms:
                break
            token = re.sub(r"\d+", "", token)
            token = token.strip(" ,;:|.-")
            if not token:
                continue
            parts.append(token)

        return " ".join(parts).strip()

    @staticmethod
    def _tokens_to_text(tokens: List[Dict[str, Any]]) -> str:
        """Rebuild token stream into line-oriented text when geometry is available."""
        if not tokens:
            return ""

        has_geometry = any(
            isinstance(token, dict) and token.get("page") is not None and token.get("y0") is not None and token.get("x0") is not None
            for token in tokens
        )
        if not has_geometry:
            return " ".join(str(token.get("text", "")) for token in tokens if isinstance(token, dict))

        sorted_tokens = sorted(
            [token for token in tokens if isinstance(token, dict)],
            key=lambda token: (token.get("page", 0), token.get("y0", 0.0), token.get("x0", 0.0)),
        )
        lines: List[str] = []
        current_page = None
        current_line: List[Dict[str, Any]] = []
        current_y = None
        y_tolerance = 6.0

        for token in sorted_tokens:
            text = str(token.get("text", "")).strip()
            if not text:
                continue

            page = token.get("page")
            y0 = float(token.get("y0", 0.0))

            if current_page is None:
                current_page = page
                current_y = y0
            if page != current_page or (current_y is not None and abs(y0 - current_y) > y_tolerance):
                if current_line:
                    sorted_line = sorted(current_line, key=lambda t: float(t.get("x0", 0.0)))
                    lines.append(" ".join(str(t.get("text", "")).strip() for t in sorted_line))
                if page != current_page:
                    lines.append("")
                current_line = [token]
                current_page = page
                current_y = y0
                continue

            current_line.append(token)
            if current_y is None:
                current_y = y0
            else:
                current_y = (current_y + y0) / 2

        if current_line:
            sorted_line = sorted(current_line, key=lambda t: float(t.get("x0", 0.0)))
            lines.append(" ".join(str(t.get("text", "")).strip() for t in sorted_line))

        return "\n".join(lines)

    @staticmethod
    def _normalize_date(date_str: str) -> Optional[str]:
        """Normalize date to DD-MM-YYYY format."""
        if not date_str:
            return None
        
        # Try to parse various date formats
        formats = [
            "%d-%m-%Y",
            "%d/%m/%Y", 
            "%d-%m-%y",
            "%d/%m/%y",
            "%d-%b-%Y",
            "%d/%b/%Y",
            "%Y-%m-%d",
            "%d %B %Y",
            "%d %b %Y",
        ]
        
        date_str = date_str.strip()
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.strftime("%d-%m-%Y")
            except ValueError:
                continue
        
        # If no format matched, return as-is (already in recognizable format)
        return date_str if date_str else None

    @staticmethod
    def _normalize_gender(gender_str: str) -> Optional[str]:
        """Normalize gender to Male/Female."""
        if not gender_str:
            return None
        
        gender_str = gender_str.strip().lower()
        if gender_str in {"m", "male"}:
            return "Male"
        elif gender_str in {"f", "female"}:
            return "Female"
        return None

    @staticmethod
    def extract_field(field_name: str, full_text: str) -> Optional[str]:
        """Extract a single field from full text using all available patterns."""
        if field_name not in RobustFieldExtractor.PATTERNS:
            return None
        
        patterns = RobustFieldExtractor.PATTERNS[field_name]
        
        candidates = []
        # Gather all matches across all patterns
        for pattern in patterns:
            matches = re.finditer(pattern, full_text, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                value = match.group(1).strip() if match.lastindex and match.lastindex >= 1 else ""
                if not value:
                    continue
                candidates.append((match.start(), value))
        
        valid_candidates = []
        for start_pos, value in candidates:
            value = RobustFieldExtractor._clean_text(value)
            
            # Post-processing and validation
            if field_name == "age":
                try:
                    age = int(value)
                    if 0 <= age <= 120:
                        valid_candidates.append((start_pos, f"{age} Years"))
                except ValueError:
                    continue
            
            elif field_name == "gender":
                gender = RobustFieldExtractor._normalize_gender(value)
                if gender:
                    valid_candidates.append((start_pos, gender))
            
            elif field_name in {"admission_date", "discharge_date"}:
                date_norm = RobustFieldExtractor._normalize_date(value)
                if date_norm:
                    valid_candidates.append((start_pos, date_norm))
            
            elif field_name in {"patient_name", "doctor_name"}:
                value = RobustFieldExtractor._clean_person_name(value)
                # Strip trailing department/credential markers for doctor names
                if field_name == "doctor_name":
                    value = re.sub(r"\s+(?:Dept|Dept\.|Department|MD|PhD|Reg\.|Reg\s+No).*$", "", value, flags=re.IGNORECASE).strip()
                value_lower = value.lower()
                reject_terms = RobustFieldExtractor.PATIENT_REJECT_TERMS if field_name == "patient_name" else RobustFieldExtractor.DOCTOR_REJECT_TERMS
                if any(term in value_lower for term in reject_terms):
                    continue

                words = [w for w in value.split() if w]
                if len(words) >= 2:
                    has_valid_word = any(len(w) >= 3 and re.search(r"[A-Za-z]", w) for w in words)
                    if has_valid_word:
                        if field_name == "doctor_name":
                            valid_candidates.append((start_pos, " ".join(words[:3])))
                        else:
                            valid_candidates.append((start_pos, " ".join(words[:4])))
            
            elif field_name == "hospital_name":
                # Hospital names should be meaningful; strip unwanted trailing tokens
                value_lower = value.lower()
                if any(term in value_lower for term in RobustFieldExtractor.HOSPITAL_REJECT_TERMS):
                    continue
                
                # Remove unwanted trailing fragments like "& FINAL BILL", "| Claim Ref", etc.
                value = re.sub(r"\s*[&|].*$", "", value).strip()
                
                if len(value) >= 5:
                    trailing_tokens: list[str] = []
                    for token in reversed(value.split()):
                        clean_token = token.strip(" ,;:|.-")
                        if not clean_token:
                            continue
                        token_lower = clean_token.lower()
                        if clean_token[0].isupper() or token_lower in {"of", "and", "the", "&"}:
                            trailing_tokens.append(clean_token)
                            continue
                        break

                    if trailing_tokens:
                        candidate = " ".join(reversed(trailing_tokens)).strip()
                        candidate_lower = candidate.lower()
                        if any(keyword in candidate_lower for keyword in {"hospital", "hospitals", "medical center", "medical centre", "health center", "health centre", "healthcare", "clinic", "corporation", "health"}):
                            valid_candidates.append((start_pos, candidate))
                            continue
                    if value.replace(" ", "").replace("&", "").replace(".", "").isalpha() or "hospital" in value_lower or "center" in value_lower or "clinic" in value_lower or "health" in value_lower:
                        valid_candidates.append((start_pos, value))
            
            elif field_name == "diagnosis":
                # Clean diagnosis: remove extra punctuation
                value = re.sub(r"\s+", " ", value).strip()
                value_lower = value.lower()
                if any(term in value_lower for term in RobustFieldExtractor.DIAGNOSIS_REJECT_TERMS):
                    continue
                diagnosis_matches = list(re.finditer(r"(?:primary\s+)?diagnosis\s*[:\-=|]?\s*([^\n|]{3,120})", value, re.IGNORECASE))
                if diagnosis_matches:
                    value = diagnosis_matches[-1].group(1).strip()
                    value_lower = value.lower()
                value = re.split(
                    r"\b(?:age|sex|admission|admit|discharge|patient|doctor|hospital|bill|occupation)\b|\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b",
                    value,
                    maxsplit=1,
                    flags=re.IGNORECASE,
                )[0].strip(" ,;:|.-")
                value_lower = value.lower()
                if any(term in value_lower for term in {"patient", "hospital", "doctor", "claim", "information"}):
                    continue
                if re.search(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b", value):
                    continue
                if re.fullmatch(r"[\d\W_]+", value):
                    continue
                if len(value) >= 3:
                    valid_candidates.append((start_pos, value))
            
            elif field_name == "claimed_total":
                # clean total amount (remove rs, spaces, commas, non-numeric except dot)
                cleaned = re.sub(r"[^\d.]", "", value)
                if cleaned:
                    try:
                        float(cleaned)
                        valid_candidates.append((start_pos, value))
                    except ValueError:
                        continue

            else:
                if len(value) >= 3:
                    valid_candidates.append((start_pos, value))
        
        if not valid_candidates:
            return None

        # Return logic:
        if field_name == "diagnosis":
            # For diagnosis, filter out vague generic values (like "management", "medical management")
            # if we have other more specific clinical descriptions.
            generic_terms = {"management", "medical management", "procedure", "care", "admitting", "discharge", "treated", "managed", "history"}
            filtered = [val for _, val in valid_candidates if val.strip().lower() not in generic_terms]
            if filtered:
                # Sort by length descending to get the most specific description
                filtered.sort(key=len, reverse=True)
                return filtered[0]
            # Fallback if only generic terms matched
            valid_candidates.sort(key=lambda x: len(x[1]), reverse=True)
            return valid_candidates[0][1]

        # For all other fields, prefer the earliest match in the text (original behavior)
        valid_candidates.sort(key=lambda x: x[0])
        return valid_candidates[0][1]

    @staticmethod
    def extract_all_fields(tokens: List[Dict[str, Any]]) -> Dict[str, Optional[str]]:
        """Extract all patient/claim fields from token list."""
        # Join all tokens into full text
        full_text = RobustFieldExtractor._tokens_to_text(tokens)
        
        results = {}
        for field_name in RobustFieldExtractor.PATTERNS.keys():
            extracted = RobustFieldExtractor.extract_field(field_name, full_text)
            if extracted:
                results[field_name] = extracted
        
        return results

    @staticmethod
    def extract_from_tokens(tokens: List[Dict[str, Any]]) -> Dict[str, Optional[str]]:
        """
        Extract patient and claim details from token stream.
        Returns dict with keys: patient_name, age, gender, admission_date, 
                               discharge_date, doctor_name, hospital_name, diagnosis
        """
        return RobustFieldExtractor.extract_all_fields(tokens)
