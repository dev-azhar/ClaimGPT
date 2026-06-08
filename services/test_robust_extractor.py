#!/usr/bin/env python3
"""
Test the robust field extractor on various document formats.
Validates that patient/claim details are extracted consistently WITHOUT using LLM.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from services.parser.app.robust_field_extractor import RobustFieldExtractor


def create_test_tokens(text: str):
    """Convert text into token list for testing."""
    words = text.split()
    tokens = []
    x_pos = 0
    for word in words:
        tokens.append({
            "text": word,
            "x0": x_pos,
            "y0": 0,
            "x1": x_pos + len(word) * 5,
            "y1": 10,
            "page": 1,
        })
        x_pos += len(word) * 6
    return tokens


# Test documents in various formats
TEST_DOCUMENTS = {
    "Format 1 - Key:Value": """
        Patient Name: John Smith
        Age: 45 years
        Gender: Male
        Admission Date: 15-05-2025
        Discharge Date: 20-05-2025
        Doctor: Dr. Ramesh Kumar
        Hospital Name: XYZ Medical Center
        Diagnosis: Acute Myocardial Infarction
    """,
    
    "Format 2 - Label with Dash": """
        Patient - Mr. Rajesh Patel
        Age - 52 years
        Sex - Female
        Date of Admission - 10-03-2025
        Date of Discharge - 15-03-2025
        Treating Doctor - Dr. Priya Sharma
        Hospital - Apollo Healthcare
        Primary Diagnosis - Hypertension
    """,
    
    "Format 3 - Mixed Case": """
        PATIENT NAME: Amelia Johnson
        AGE: 38
        GENDER: Female
        ADMITTED ON: 05-02-2025
        DISCHARGED ON: 10-02-2025
        CONSULTANT: Dr. Michael Brown
        NAME OF HOSPITAL: Fortis Hospitals
        FINAL DIAGNOSIS: Type 2 Diabetes
    """,
    
    "Format 4 - Abbreviated": """
        Name: Vikram Singh
        Age/Sex: 55/M
        DOA: 25-04-2025
        DOD: 30-04-2025
        Dr.: Dr. Arun Verma
        Hospital: Max Healthcare
        Diagnosis: Kidney Stone
    """,
    
    "Format 5 - Narrative Style": """
        Mr. Robert Wilson, a 60-year-old male, was admitted on 12-01-2025
        and discharged on 18-01-2025. Treating Physician: Dr. Edward Smith.
        The patient was treated at Johns Hopkins Hospital.
        Clinical Diagnosis: Cardiac Arrhythmia.
    """,
    
    "Format 6 - Paragraph": """
        This is the medical report for patient Jennifer Davis aged 48 years.
        She is female. The admission date was 08-06-2025 and discharge was 12-06-2025.
        The treating consultant was Dr. Sarah Williams.
        The hospital of treatment was Cleveland Medical Center.
        Her diagnosis upon discharge was Pneumonia.
    """,
}


def test_extractor():
    """Test the robust extractor on all formats."""
    print("=" * 80)
    print("ROBUST FIELD EXTRACTOR TEST - Multiple Document Formats")
    print("=" * 80)
    
    all_passed = True
    
    for format_name, document_text in TEST_DOCUMENTS.items():
        print(f"\n{'='*80}")
        print(f"Testing: {format_name}")
        print(f"{'='*80}")
        
        # Extract fields
        fields = {
            "patient_name": RobustFieldExtractor.extract_field("patient_name", document_text),
            "age": RobustFieldExtractor.extract_field("age", document_text),
            "gender": RobustFieldExtractor.extract_field("gender", document_text),
            "admission_date": RobustFieldExtractor.extract_field("admission_date", document_text),
            "discharge_date": RobustFieldExtractor.extract_field("discharge_date", document_text),
            "doctor_name": RobustFieldExtractor.extract_field("doctor_name", document_text),
            "hospital_name": RobustFieldExtractor.extract_field("hospital_name", document_text),
            "diagnosis": RobustFieldExtractor.extract_field("diagnosis", document_text),
        }
        
        # Display results
        all_found = True
        for field_name, value in fields.items():
            status = "✓" if value else "✗"
            print(f"{status} {field_name:20s}: {value or 'NOT FOUND'}")
            if not value:
                all_found = False
        
        if all_found:
            print(f"\n✓ PASS: All fields extracted successfully")
        else:
            print(f"\n✗ FAIL: Some fields missing")
            all_passed = False
    
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    if all_passed:
        print("✓ All tests PASSED - Robust extractor works across formats")
        return 0
    else:
        print("✗ Some tests FAILED - Check extraction patterns")
        return 1


if __name__ == "__main__":
    sys.exit(test_extractor())
