"""Verify PII is stripped and only clinical context is sent to OpenRouter."""
import sys
sys.path.insert(0, ".")

from services.coding.app.engine import _build_clinical_context

# Simulate what the engine has available for claim 487e630d
full_text = (
    "NETARALAY AND MATERNITY HOME,NANDED Govardhan Ghat Borban Factory "
    "Tel: (02462-248108). DISCHARGE SUMMARY Original Copy "
    "AMREEN AZHAR SHAIKH IPD REG NO- 1-28/2026 DOA- 09-04-2026 "
    "29 Years Sex- FEMALE Occupation: HOUSE WIFE "
    "Address - BHAIGAON ROAD SHARDA NAGAR "
    "DIAGNOSIS- G3PILIAI 39WKS ZDAYS PREGNANCY IN LABOUR "
    "FTND C EPISIOTOMY ON 09/04/2026 AT 6.24PM MALE BABY OF WT 2.8KG\n"
    "C/O-1 H/O-AMMENORRHOEA MONTH 2 DAYS\n"
    "OBSTETRIC EXAMINATION: PA OBS-Uterus height:-FT WEEKS Lie:-Longitudinal\n"
    "DELIVERY NOTES: Type Of Delivery: FTND C EPISIOTOMY Sex: Male Weight 2800 gms\n"
    "COURSE IN HOSPITAL STAY-UNEVENTFUL CONDITION ON DISCHARGE: STABLE\n"
    "Lab Investigation: BL GRP POSITIVE; HIV, HBSAG-NR\n"
    "ANIKET NETARALAY AND MATERNITY HOME,NANDED IPD BILL "
    "Patient Name AMREEN AZHAR SHAIKH Bill Date 10-04-2026"
)

parsed_fields = [
    {"field_name": "patient_name", "field_value": "AMREEN AZHAR SHAIKH"},
    {"field_name": "hospital_name", "field_value": "NETARALAY AND MATERNITY HOME,NANDED"},
    {"field_name": "doctor_name",   "field_value": "SUNITA AJAY BURANDE"},
    {"field_name": "address",       "field_value": "BHAIGAON ROAD SHARDA NAGAR"},
    {"field_name": "diagnosis",     "field_value": "G3PILIAI 39WKS ZDAYS PREGNANCY IN LABOUR"},
]

result = _build_clinical_context(full_text, parsed_fields)

print("=== CLINICAL CONTEXT SENT TO OPENROUTER ===")
print(result)
print()

# Verify PII is gone
pii_checks = {
    "AMREEN AZHAR SHAIKH":                 "patient name",
    "NETARALAY AND MATERNITY HOME,NANDED": "hospital name",
    "BHAIGAON ROAD SHARDA NAGAR":          "address",
    "02462-248108":                         "phone number",
}

print("=== PII AUDIT ===")
all_clean = True
for pii, label in pii_checks.items():
    if pii in result:
        print(f"  FAIL — {label} still present: {pii!r}")
        all_clean = False
    else:
        print(f"  OK   — {label} redacted")

print()
# Verify clinical content is present
clinical_checks = ["FTND", "EPISIOTOMY", "DELIVERY", "OBSTETRIC", "DIAGNOSIS"]
for term in clinical_checks:
    present = term.upper() in result.upper()
    print(f"  {'OK' if present else 'MISSING'} — clinical term {term!r} {'present' if present else 'MISSING'}")

print()
if all_clean:
    print("PASS: No PII in LLM input. Only clinical context sent.")
else:
    print("FAIL: PII detected in LLM input!")
