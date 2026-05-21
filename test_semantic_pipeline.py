#!/usr/bin/env python
"""
Comprehensive test of semantic extraction and LLM integration.
Tests Ollama connectivity, backend registry, semantic extraction, and full pipeline.
"""
import json
import sys
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

def test_ollama_connectivity():
    """Test direct connection to local Ollama."""
    logger.info("=" * 80)
    logger.info("TEST 1: Ollama Connectivity")
    logger.info("=" * 80)
    
    import httpx
    urls_to_test = [
        'http://localhost:11434/api/tags',
        'http://127.0.0.1:11434/api/tags',
    ]
    
    for url in urls_to_test:
        try:
            logger.info(f"Testing {url}...")
            r = httpx.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                models = data.get('models', [])
                logger.info(f"✓ Ollama is reachable! Found {len(models)} models")
                for model in models:
                    name = model.get('name') or model.get('model')
                    logger.info(f"  - {name}")
                return True
            else:
                logger.warning(f"✗ Status {r.status_code}")
        except Exception as e:
            logger.warning(f"✗ {url}: {e}")
    
    logger.error("✗ Ollama not reachable on any endpoint")
    return False


def test_backend_registry():
    """Test semantic backend registry and model selection."""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 2: Backend Registry and Model Selection")
    logger.info("=" * 80)
    
    from services.parser_v2.semantic_backends import SemanticBackendRegistry
    
    try:
        registry = SemanticBackendRegistry()
        logger.info(f"✓ Registry initialized with {len(registry.backends)} backends")
        
        for i, backend in enumerate(registry.backends):
            logger.info(f"  [{i}] {backend.name}")
            try:
                avail = backend.available()
                logger.info(f"      available: {avail}")
            except Exception as e:
                logger.warning(f"      available check failed: {e}")
        
        chosen = registry.choose()
        if chosen:
            logger.info(f"✓ Selected backend: {chosen.name}")
            return True
        else:
            logger.error("✗ No backend available")
            return False
    except Exception as e:
        logger.error(f"✗ Registry initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_semantic_extraction():
    """Test semantic extraction on real debug payload."""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 3: Semantic Extraction on Real Data")
    logger.info("=" * 80)
    
    try:
        from services.parser_v2.models import DocumentStructure, Region, TableRegion
        from services.parser_v2.semantic_extractor import extract_semantics
        
        # Load real debug payload
        payload_path = Path('tmp/parser_debug/runtime/01_parser_v2_output.json')
        if not payload_path.exists():
            logger.error(f"✗ Debug payload not found: {payload_path}")
            return False
        
        logger.info(f"Loading debug payload from {payload_path}...")
        obj = json.loads(payload_path.read_text(encoding='utf-8'))
        
        logger.info(f"  - regions: {len(obj.get('regions', []))}")
        logger.info(f"  - tables: {len(obj.get('tables', []))}")
        logger.info(f"  - fields: {len(obj.get('fields', []))}")
        
        # Build DocumentStructure
        doc = DocumentStructure(
            regions=[Region.model_validate(r) for r in obj['regions']],
            tables=[TableRegion.model_validate(t) for t in obj['tables']],
            claim_id=obj.get('claim_id'),
            document_id=obj.get('document_id'),
        )
        logger.info(f"✓ DocumentStructure created")
        
        # Run semantic extraction
        logger.info("Running semantic extraction...")
        out = extract_semantics(
            doc, 
            page_images=None, 
            debug_dir=None, 
            claim_id=obj.get('claim_id')
        )
        
        logger.info(f"✓ Semantic extraction completed")
        logger.info(f"  - backend: {out.model_name}")
        logger.info(f"  - errors: {out.errors if out.errors else 'none'}")
        logger.info(f"  - semantic_regions: {len(out.semantic_regions)}")
        logger.info(f"  - semantic_fields: {len(out.semantic_fields)}")
        logger.info(f"  - classified_tables: {len(out.classified_tables)}")
        logger.info(f"  - model_predictions: {len(out.model_predictions)}")
        
        # Detailed field output
        if out.semantic_field_mapping:
            logger.info(f"✓ Semantic fields extracted:")
            for field_name, field_data in list(out.semantic_field_mapping.items())[:10]:
                value = field_data.get('value', '')[:50]
                confidence = field_data.get('confidence', 0)
                logger.info(f"    - {field_name}: '{value}' (conf: {confidence:.2f})")
        
        # Table mapping
        if out.semantic_table_mapping:
            logger.info(f"✓ Table kinds found:")
            for table_kind, tables in out.semantic_table_mapping.items():
                count = len(tables) if isinstance(tables, list) else 1
                logger.info(f"    - {table_kind}: {count} entries")
        
        # Expense extraction
        expenses = out.semantic_table_mapping.get('expense_line_items', [])
        if expenses:
            logger.info(f"✓ Extracted {len(expenses)} expense line items:")
            for exp in expenses[:5]:
                desc = exp.get('description', '')[:40]
                amount = exp.get('amount', '')
                logger.info(f"    - {desc}: {amount}")
        else:
            logger.warning("⚠ No expenses extracted")
        
        return len(out.semantic_fields) > 0 or len(expenses) > 0
        
    except Exception as e:
        logger.error(f"✗ Semantic extraction failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_full_pipeline():
    """Test full parser_v2 pipeline."""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 4: Full Parser Pipeline")
    logger.info("=" * 80)
    
    try:
        from services.parser_v2.pipeline import parse_document
        
        # Load real debug payload
        payload_path = Path('tmp/parser_debug/runtime/01_parser_v2_output.json')
        if not payload_path.exists():
            logger.error(f"✗ Debug payload not found: {payload_path}")
            return False
        
        obj = json.loads(payload_path.read_text(encoding='utf-8'))
        ocr_tokens = obj.get('regions', [])[0].get('tokens', []) if obj.get('regions') else []
        
        if not ocr_tokens:
            logger.error("✗ No OCR tokens in debug payload")
            return False
        
        logger.info(f"Running full pipeline with {len(ocr_tokens)} OCR tokens...")
        
        # Convert regions/tables to token stream
        all_tokens = []
        for region in obj.get('regions', []):
            all_tokens.extend(region.get('tokens', []))
        
        logger.info(f"Total tokens to process: {len(all_tokens)}")
        
        doc = parse_document(
            all_tokens,
            page_images=None,
            debug_dir='tmp/parser_debug/pipeline_test',
            claim_id=obj.get('claim_id')
        )
        
        logger.info(f"✓ Pipeline completed")
        logger.info(f"  - normalized_fields: {len(doc.normalized_fields)}")
        logger.info(f"  - normalized_expenses: {len(doc.normalized_expenses)}")
        logger.info(f"  - semantic_regions: {len(doc.semantic_regions)}")
        logger.info(f"  - classified_tables: {len(doc.classified_tables)}")
        
        # Show extracted fields
        if doc.normalized_fields:
            logger.info(f"✓ Normalized fields:")
            for field in doc.normalized_fields[:5]:
                field_name = field.get('canonical_field', 'unknown')
                value = str(field.get('value', ''))[:40]
                logger.info(f"    - {field_name}: {value}")
        
        # Show extracted expenses
        if doc.normalized_expenses:
            logger.info(f"✓ Normalized expenses ({len(doc.normalized_expenses)}):")
            for exp in doc.normalized_expenses[:5]:
                desc = exp.get('description', '')[:40]
                amount = exp.get('amount', '')
                logger.info(f"    - {desc}: {amount}")
        else:
            logger.warning("⚠ No normalized expenses")
        
        return len(doc.normalized_fields) > 0 or len(doc.normalized_expenses) > 0
        
    except Exception as e:
        logger.error(f"✗ Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    logger.info("\n")
    logger.info("╔" + "=" * 78 + "╗")
    logger.info("║" + " " * 78 + "║")
    logger.info("║" + "  SEMANTIC EXTRACTION & LLM INTEGRATION TEST SUITE".center(78) + "║")
    logger.info("║" + " " * 78 + "║")
    logger.info("╚" + "=" * 78 + "╝")
    logger.info("\n")
    
    results = {
        "Ollama Connectivity": test_ollama_connectivity(),
        "Backend Registry": test_backend_registry(),
        "Semantic Extraction": test_semantic_extraction(),
        "Full Pipeline": test_full_pipeline(),
    }
    
    logger.info("\n" + "=" * 80)
    logger.info("TEST SUMMARY")
    logger.info("=" * 80)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        logger.info(f"{status}: {name}")
    
    logger.info("=" * 80)
    logger.info(f"RESULT: {passed}/{total} tests passed")
    logger.info("=" * 80 + "\n")
    
    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
