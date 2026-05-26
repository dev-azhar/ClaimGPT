#!/usr/bin/env python3
"""
Generate sample debug artifacts to show document isolation output format.
"""

import json
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from services.parser_v2.pipeline import parse_document


def generate_sample_artifacts():
    """Generate debug artifacts showing document isolation."""
    
    # Create realistic test tokens simulating discharge summary + hospital bill
    tokens = []
    
    # Discharge summary page 1
    discharge_tokens = [
        {"text": "DISCHARGE SUMMARY", "x0": 100, "y0": 50, "x1": 400, "y1": 80, "page": 1},
        {"text": "Patient Name:", "x0": 100, "y0": 100, "x1": 250, "y1": 130, "page": 1},
        {"text": "AMREEN AZHAR", "x0": 260, "y0": 100, "x1": 400, "y1": 130, "page": 1},
        {"text": "Age:", "x0": 100, "y0": 140, "x1": 150, "y1": 170, "page": 1},
        {"text": "26 years", "x0": 160, "y0": 140, "x1": 260, "y1": 170, "page": 1},
        {"text": "DOA:", "x0": 300, "y0": 140, "x1": 380, "y1": 170, "page": 1},
        {"text": "09-04-2026", "x0": 390, "y0": 140, "x1": 500, "y1": 170, "page": 1},
    ]
    
    # Hospital bill page 1
    bill_tokens = [
        {"text": "HOSPITAL BILL", "x0": 100, "y0": 50, "x1": 400, "y1": 80, "page": 1},
        {"text": "Sr. No.", "x0": 100, "y0": 150, "x1": 200, "y1": 180, "page": 1},
        {"text": "Description", "x0": 210, "y0": 150, "x1": 500, "y1": 180, "page": 1},
        {"text": "Amount", "x0": 510, "y0": 150, "x1": 600, "y1": 180, "page": 1},
        {"text": "1", "x0": 100, "y0": 190, "x1": 200, "y1": 220, "page": 1},
        {"text": "Room Charges", "x0": 210, "y0": 190, "x1": 500, "y1": 220, "page": 1},
        {"text": "21000", "x0": 510, "y0": 190, "x1": 600, "y1": 220, "page": 1},
        {"text": "2", "x0": 100, "y0": 230, "x1": 200, "y1": 260, "page": 1},
        {"text": "Pharmacy", "x0": 210, "y0": 230, "x1": 500, "y1": 260, "page": 1},
        {"text": "8000", "x0": 510, "y0": 230, "x1": 600, "y1": 260, "page": 1},
        {"text": "Total", "x0": 210, "y0": 300, "x1": 500, "y1": 330, "page": 1},
        {"text": "29000", "x0": 510, "y0": 300, "x1": 600, "y1": 330, "page": 1},
    ]
    
    # Add document_id and claim_id
    discharge_id = "doc-discharge-20260510"
    bill_id = "doc-bill-20260510"
    claim_id = "claim-patient-123"
    
    for token in discharge_tokens:
        token["document_id"] = discharge_id
        token["claim_id"] = claim_id
        tokens.append(token)
    
    for token in bill_tokens:
        token["document_id"] = bill_id
        token["claim_id"] = claim_id
        tokens.append(token)
    
    # Parse with debug output
    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Parsing {len(tokens)} tokens from 2 documents...")
        print(f"  - Discharge summary: {len(discharge_tokens)} tokens")
        print(f"  - Hospital bill: {len(bill_tokens)} tokens")
        print()
        
        doc = parse_document(tokens, debug_dir=tmpdir, claim_id=claim_id)
        
        # Read and display debug artifacts
        import os
        
        isolated_docs_path = os.path.join(tmpdir, "10_isolated_documents.json")
        grouped_pages_path = os.path.join(tmpdir, "11_grouped_pages.json")
        
        if os.path.exists(isolated_docs_path):
            print("=" * 60)
            print("10_isolated_documents.json")
            print("=" * 60)
            with open(isolated_docs_path) as f:
                data = json.load(f)
            print(json.dumps(data, indent=2))
            print()
        
        if os.path.exists(grouped_pages_path):
            print("=" * 60)
            print("11_grouped_pages.json")
            print("=" * 60)
            with open(grouped_pages_path) as f:
                data = json.load(f)
            print(json.dumps(data, indent=2))
            print()
        
        # Verify document separation
        print("=" * 60)
        print("VERIFICATION SUMMARY")
        print("=" * 60)
        print(f"Regions detected: {len(doc.regions)}")
        for i, region in enumerate(doc.regions):
            doc_count = len(set(t.document_id for t in region.tokens))
            print(f"  Region {i}: {region.region_type:20} | doc_count={doc_count} | tokens={len(region.tokens)}")
            if doc_count > 1:
                print(f"    ✗ WARNING: Mixed documents in region!")
                unique_docs = set(t.document_id for t in region.tokens)
                for doc_id in unique_docs:
                    print(f"      - {doc_id}")
            else:
                doc_id = region.tokens[0].document_id if region.tokens else "none"
                print(f"    ✓ OK: All tokens from document {doc_id[:16]}...")


if __name__ == "__main__":
    generate_sample_artifacts()
