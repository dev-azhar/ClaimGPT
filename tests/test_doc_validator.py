"""Quick validation test for the document validator module."""

from services.ocr.app.doc_validator import (
    classify_document,
    is_medical_document,
    extract_patient_identity,
    validate_claim_documents,
)


def test_classify_document():
    code, label = classify_document(
        "Patient: John Doe. Discharge Summary. Diagnosis: Acute appendicitis.",
        "discharge.pdf",
    )
    assert code == "DISCHARGE_SUMMARY", f"Expected DISCHARGE_SUMMARY, got {code}"
    print(f"  classify: {code} ({label})")


def test_medical_document():
    text = (
        "Patient Name: John Doe. Doctor: Dr Smith. Diagnosis: Fracture. "
        "Treatment: Surgery. Admission: 2024-01-01. Hospital: City Hospital. "
        "Medication: Paracetamol. Lab Report: CBC normal."
    )
    is_med, conf, issues = is_medical_document(text, "report.pdf")
    assert is_med is True, f"Expected medical=True, got {is_med}"
    print(f"  medical: {is_med}, confidence: {conf:.2f}")


def test_non_medical_document():
    text = "This is a real estate property deed for 123 Main St. Mortgage details. Rent agreement."
    is_med, conf, issues = is_medical_document(text, "property.pdf")
    assert is_med is False, f"Expected medical=False, got {is_med}"
    print(f"  non-medical: {is_med}, issues: {issues}")


def test_patient_extraction():
    text = (
        "Patient Name: John Doe. DOB: 15/03/1990. Age: 34 years. "
        "Sex: Male. MRN: MRN-12345. Policy Number: POL-9876543"
    )
    ident = extract_patient_identity(text)
    assert ident.name == "John Doe", f"Expected 'John Doe', got '{ident.name}'"
    assert ident.patient_id == "MRN-12345", f"Expected 'MRN-12345', got '{ident.patient_id}'"
    assert ident.dob == "15/03/1990", f"Expected '15/03/1990', got '{ident.dob}'"
    assert ident.age == "34", f"Expected '34', got '{ident.age}'"
    assert ident.gender == "Male", f"Expected 'Male', got '{ident.gender}'"
    assert ident.policy_number == "POL-9876543", f"Expected 'POL-9876543', got '{ident.policy_number}'"
    print(f"  patient: name={ident.name}, dob={ident.dob}, id={ident.patient_id}")


def test_cross_document_validation():
    result = validate_claim_documents(
        [
            {
                "document_id": "00000000-0000-0000-0000-000000000001",
                "file_name": "discharge.pdf",
                "text": (
                    "Patient Name: John Doe. DOB: 15/03/1990. MRN: MRN-12345. "
                    "Discharge Summary. Diagnosis: Fracture. Treatment: Surgery. "
                    "Hospital: City Hospital. Doctor: Dr Smith."
                ),
            },
            {
                "document_id": "00000000-0000-0000-0000-000000000002",
                "file_name": "lab_report.pdf",
                "text": (
                    "Patient: John Doe. MRN: MRN-12345. Lab Report. "
                    "CBC: Normal. Blood Sugar: 110. Hemoglobin: 14.2."
                ),
            },
            {
                "document_id": "00000000-0000-0000-0000-000000000003",
                "file_name": "wrong_patient.pdf",
                "text": (
                    "Patient Name: Jane Smith. DOB: 22/07/1985. MRN: MRN-99999. "
                    "Prescription. Drug: Amoxicillin. Doctor: Dr Brown."
                ),
            },
        ],
        "test-claim-001",
    )

    assert result.valid_count >= 1, f"Expected at least 1 valid, got {result.valid_count}"
    assert result.invalid_count >= 1, f"Expected at least 1 invalid, got {result.invalid_count}"
    print(f"  claim: status={result.status}, valid={result.valid_count}, invalid={result.invalid_count}")
    for d in result.documents:
        issues_str = "; ".join(d.issues) if d.issues else "none"
        print(f"    {d.file_name}: {d.status} (match={d.patient_match}, medical={d.is_medical}) issues=[{issues_str}]")


if __name__ == "__main__":
    tests = [
        ("Classify document", test_classify_document),
        ("Medical document detection", test_medical_document),
        ("Non-medical document detection", test_non_medical_document),
        ("Patient identity extraction", test_patient_extraction),
        ("Cross-document patient matching", test_cross_document_validation),
    ]
    passed = 0
    for name, fn in tests:
        try:
            print(f"\n[TEST] {name}")
            fn()
            print(f"  PASSED")
            passed += 1
        except AssertionError as e:
            print(f"  FAILED: {e}")
        except Exception as e:
            print(f"  ERROR: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
