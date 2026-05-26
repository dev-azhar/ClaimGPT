#!/usr/bin/env python3
"""
Test script to validate document isolation fix for parser_v2.
Verifies that tokens are properly grouped by (claim_id, document_id, page_number).
"""

import json
import sys
import os
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

def test_import():
    """Verify all modules import correctly."""
    try:
        from services.parser_v2.models import Token, Region, DocumentStructure
        from services.parser_v2.layout_detector import detect_regions
        from services.parser_v2.pipeline import parse_document
        print("✓ All modules imported successfully")
        return True
    except Exception as e:
        print(f"✗ Import failed: {e}")
        return False


def test_token_model():
    """Verify Token model has claim_id field."""
    try:
        from services.parser_v2.models import Token
        
        # Create token with claim_id
        token = Token(
            text="Test",
            x0=0.0, y0=0.0, x1=100.0, y1=50.0,
            page=1,
            document_id="doc-001",
            claim_id="claim-001"
        )
        
        assert token.claim_id == "claim-001", "claim_id not stored"
        assert token.document_id == "doc-001", "document_id not stored"
        print("✓ Token model stores claim_id and document_id")
        return True
    except Exception as e:
        print(f"✗ Token model test failed: {e}")
        return False


def test_document_isolation_grouping():
    """Verify layout_detector uses (claim_id, document_id, page) grouping."""
    try:
        from services.parser_v2.models import Token
        from services.parser_v2.layout_detector import detect_regions
        
        # Create tokens simulating two documents (discharge summary + hospital bill)
        # Both would be page 1 in their respective documents
        tokens_discharge = [
            Token(text=f"Discharge text {i}", x0=float(i*10), y0=float(i*10), 
                  x1=float(i*10+100), y1=float(i*10+30),
                  page=1, document_id="discharge-doc-id", claim_id="claim-123")
            for i in range(5)
        ]
        
        tokens_bill = [
            Token(text=f"Bill text {i}", x0=float(i*10+500), y0=float(i*10), 
                  x1=float(i*10+600), y1=float(i*10+30),
                  page=1, document_id="bill-doc-id", claim_id="claim-123")
            for i in range(5)
        ]
        
        all_tokens = tokens_discharge + tokens_bill
        
        # Detect regions
        regions = detect_regions(all_tokens)
        
        # Verify regions are isolated by document
        discharge_regions = [r for r in regions if r.document_id == "discharge-doc-id"]
        bill_regions = [r for r in regions if r.document_id == "bill-doc-id"]
        
        if len(discharge_regions) == 0 or len(bill_regions) == 0:
            print(f"✗ Document isolation failed: discharge={len(discharge_regions)}, bill={len(bill_regions)}")
            return False
        
        # Verify regions don't mix documents
        for region in regions:
            for token in region.tokens:
                if token.document_id != region.document_id:
                    print(f"✗ Region {region.region_id} has mixed document tokens")
                    return False
                if token.claim_id != region.claim_id:
                    print(f"✗ Region {region.region_id} has mixed claim tokens")
                    return False
        
        print(f"✓ Document isolation working: {len(discharge_regions)} discharge regions, {len(bill_regions)} bill regions")
        return True
        
    except Exception as e:
        print(f"✗ Document isolation test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_debug_artifacts():
    """Verify debug artifacts are generated."""
    try:
        import tempfile
        from services.parser_v2.models import Token
        from services.parser_v2.pipeline import parse_document
        
        # Create test tokens for two documents
        tokens = []
        for i in range(3):
            tokens.append({
                "text": f"Discharge {i}", "x0": float(i*10), "y0": float(i*10), 
                "x1": float(i*10+100), "y1": float(i*10+30),
                "page": 1, "document_id": "discharge-id", "claim_id": "claim-test"
            })
            tokens.append({
                "text": f"Bill {i}", "x0": float(i*10+500), "y0": float(i*10), 
                "x1": float(i*10+600), "y1": float(i*10+30),
                "page": 1, "document_id": "bill-id", "claim_id": "claim-test"
            })
        
        # Parse with debug output
        with tempfile.TemporaryDirectory() as tmpdir:
            doc = parse_document(tokens, debug_dir=tmpdir, claim_id="claim-test")
            
            # Check for debug artifacts
            isolated_docs_path = os.path.join(tmpdir, "10_isolated_documents.json")
            grouped_pages_path = os.path.join(tmpdir, "11_grouped_pages.json")
            
            if not os.path.exists(isolated_docs_path):
                print(f"✗ isolated_documents.json not generated")
                return False
            
            if not os.path.exists(grouped_pages_path):
                print(f"✗ grouped_pages.json not generated")
                return False
            
            # Verify artifact contents
            with open(isolated_docs_path) as f:
                isolated_docs = json.load(f)
            
            with open(grouped_pages_path) as f:
                grouped_pages = json.load(f)
            
            if isolated_docs.get("document_count", 0) < 2:
                print(f"✗ isolated_documents.json shows < 2 documents")
                return False
            
            if grouped_pages.get("group_count", 0) < 2:
                print(f"✗ grouped_pages.json shows < 2 groups")
                return False
            
            print(f"✓ Debug artifacts generated: {isolated_docs['document_count']} docs, {grouped_pages['group_count']} groups")
            return True
            
    except Exception as e:
        print(f"✗ Debug artifacts test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("DOCUMENT ISOLATION VALIDATION TEST")
    print("=" * 60)
    print()
    
    tests = [
        ("Module Imports", test_import),
        ("Token Model", test_token_model),
        ("Document Isolation Grouping", test_document_isolation_grouping),
        ("Debug Artifacts", test_debug_artifacts),
    ]
    
    results = []
    for name, test_func in tests:
        print(f"\n{name}:")
        print("-" * 40)
        result = test_func()
        results.append((name, result))
    
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"  {status}: {name}")
    
    print()
    print(f"Total: {passed}/{total} tests passed")
    
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
