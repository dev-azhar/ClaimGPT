import sys
import json
sys.path.insert(0, 'c:/Project/ClaimGPT')

from services.parser.app.engine import parse_document
from services.parser.app.main import _build_canonical_claim

# Simulated OCR input
ocr_pages = [
    {
        "page_number": 1,
        "document_id": "doc_1",
        "tokens": [
            {"text": "patient name", "x0": 10, "y0": 10, "x1": 50, "y1": 20, "page": 1},
            {"text": ":", "x0": 55, "y0": 10, "x1": 60, "y1": 20, "page": 1},
            {"text": "AMREEN", "x0": 65, "y0": 10, "x1": 100, "y1": 20, "page": 1},
            {"text": "AZHAR", "x0": 105, "y0": 10, "x1": 140, "y1": 20, "page": 1},
            {"text": "SHAIKH", "x0": 145, "y0": 10, "x1": 190, "y1": 20, "page": 1},
            {"text": "age", "x0": 10, "y0": 30, "x1": 30, "y1": 40, "page": 1},
            {"text": "-", "x0": 35, "y0": 30, "x1": 40, "y1": 40, "page": 1},
            {"text": "29", "x0": 45, "y0": 30, "x1": 60, "y1": 40, "page": 1},
            {"text": "Years", "x0": 65, "y0": 30, "x1": 90, "y1": 40, "page": 1},
            {"text": "sex", "x0": 100, "y0": 30, "x1": 120, "y1": 40, "page": 1},
            {"text": "-", "x0": 125, "y0": 30, "x1": 130, "y1": 40, "page": 1},
            {"text": "FEMALE", "x0": 135, "y0": 30, "x1": 180, "y1": 40, "page": 1},
            {"text": "Sr.", "x0": 10, "y0": 100, "x1": 30, "y1": 110, "page": 1},
            {"text": "Description", "x0": 40, "y0": 100, "x1": 100, "y1": 110, "page": 1},
            {"text": "Amount", "x0": 150, "y0": 100, "x1": 190, "y1": 110, "page": 1},
            {"text": "1", "x0": 10, "y0": 120, "x1": 20, "y1": 130, "page": 1},
            {"text": "DELIVERY", "x0": 40, "y0": 120, "x1": 90, "y1": 130, "page": 1},
            {"text": "CHARGES", "x0": 95, "y0": 120, "x1": 140, "y1": 130, "page": 1},
            {"text": "16500", "x0": 150, "y0": 120, "x1": 190, "y1": 130, "page": 1},
        ]
    }
]

output = parse_document(ocr_pages)
print("FIELDS:")
for f in output.fields:
    print(f"{f.field_name}: {f.field_value}")

print("\nCANONICAL:")
canonical = _build_canonical_claim(output)
print(json.dumps(canonical, indent=2))
