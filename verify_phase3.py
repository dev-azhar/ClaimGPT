import os
import json
from PIL import Image
import numpy as np
from services.parser_v2.pipeline import parse_document

def verify_phase3():
    print("--- Phase 3 Verification Start ---")
    
    # 1. Create mock data
    mock_tokens = [
        {"text": "Patient Name: John Doe", "x0": 100, "y0": 100, "x1": 300, "y1": 120, "page": 1},
        {"text": "Admission Date: 2024-01-01", "x0": 100, "y0": 150, "x1": 350, "y1": 170, "page": 1},
        {"text": "Description", "x0": 100, "y0": 300, "x1": 200, "y1": 320, "page": 1},
        {"text": "Amount", "x0": 400, "y0": 300, "x1": 500, "y1": 320, "page": 1},
        {"text": "Consultation", "x0": 100, "y0": 330, "x1": 200, "y1": 350, "page": 1},
        {"text": "500.00", "x0": 400, "y0": 330, "x1": 500, "y1": 350, "page": 1},
    ]
    
    # Create a blank white image
    img = Image.new('RGB', (800, 1000), color=(255, 255, 255))
    page_images = {1: img}
    
    # 2. Run Pipeline
    debug_dir = "tmp/parser_debug/phase3_test"
    doc = parse_document(mock_tokens, page_images=page_images, debug_dir=debug_dir)
    
    # 3. Check Results
    print(f"Detected Regions: {len(doc.regions)}")
    print(f"Detected Tables: {len(doc.tables)}")
    print(f"Normalized Fields: {len(doc.normalized_fields)}")
    print(f"Normalized Expenses: {len(doc.normalized_expenses)}")
    
    # Verify artifact existence
    artifacts = [
        "layout_model_regions.json",
        "ppstructure_tables.json",
        "canonical_claim.json" # Actually canonical_claim.json is in runtime/ usually, but debug_dir has others
    ]
    
    for art in artifacts:
        p = os.path.join(debug_dir, art)
        if os.path.exists(p):
            print(f"Artifact Found: {art}")
        else:
            # layout_model_regions.json is exported in debug_overlay.py
            print(f"Artifact Missing: {art}")

    print("--- Phase 3 Verification End ---")

if __name__ == "__main__":
    verify_phase3()
