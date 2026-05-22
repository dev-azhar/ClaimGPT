import uuid
import logging
from typing import List, Dict
from .models import Token, Region
from .geometry_utils import get_bbox, group_tokens_into_lines, group_lines_into_blocks
from .region_classifier import classify_region

logger = logging.getLogger("parser-debug")

# Grouping functions moved to geometry_utils.py

# is_table_block removed in favor of region_classifier.classify_region

def detect_regions(tokens: List[Token], gap_threshold: float = 12.0) -> List[Region]:
    """Splits page into structural regions using pure geometry.
    
    CRITICAL: Groups tokens by (claim_id, document_id, page_number) to prevent
    cross-document collisions when multiple images are uploaded.
    """
    logger.info("[PARSER_V2 REGION DETECTOR ACTIVE]")
    if not tokens:
        return []
    
    # DOCUMENT ISOLATION FIX: Group by (claim_id, document_id, page_number) tuple
    # instead of just page_number. This prevents multiple images from merging.
    pages: Dict[tuple, List[Token]] = {}
    for token in tokens:
        # Use composite key: (claim_id, document_id, page_number)
        doc_key = (token.claim_id or "unknown", token.document_id or "unknown", token.page)
        pages.setdefault(doc_key, []).append(token)
    
    logger.info(f"[DOCUMENT_ISOLATION] Grouped {len(tokens)} tokens into {len(pages)} document-pages")
    for doc_key in sorted(pages.keys()):
        claim_id, doc_id, page_num = doc_key
        token_count = len(pages[doc_key])
        logger.info(f"  → claim={claim_id[:8]}... doc={doc_id[:8]}... page={page_num} ({token_count} tokens)")
        
    regions = []
    
    for (claim_id, document_id, page), page_tokens in pages.items():
        lines = group_tokens_into_lines(page_tokens)
        # Determine page height for relative position checks
        page_height = max(t.y1 for t in page_tokens) if page_tokens else 1000.0
        blocks = group_lines_into_blocks(lines, gap_threshold=gap_threshold)
        
        # Phase 2.5: Deep Splitting for dense documents
        refined_blocks = []
        for block in blocks:
            # Get block position
            block_top = min(t.y0 for l in block for t in l)
            block_h = max(t.y1 for l in block for t in l) - block_top
            
            # Protect structural tables from being deep-split into individual row blocks
            r_type_pre = classify_region(block, page_height=page_height)
            is_table = r_type_pre == "table"
            
            # PROTECT DEMOGRAPHICS: Don't deep-split the top 25% of the page
            # where Name/Age/Reg are usually located in a dense form.
            if (len(block) > 8 or block_h > page_height * 0.25) and block_top > page_height * 0.25 and not is_table:
                sub_blocks = group_lines_into_blocks(block, gap_threshold=6.0) # Tight split for tables
                refined_blocks.extend(sub_blocks)
            else:
                refined_blocks.append(block)

        for block in refined_blocks:
            flat_tokens = [token for line in block for token in line]
            bbox = get_bbox(flat_tokens)
            region_id = str(uuid.uuid4())
            
            # Use Geometry-First Classifier
            region_type = classify_region(block, page_height=page_height)
                
            regions.append(Region(
                region_id=region_id,
                region_type=region_type,
                bbox=bbox,
                tokens=flat_tokens,
                page=page,
                claim_id=claim_id,
                document_id=document_id,
                confidence=1.0
            ))
    
    logger.info(f"[DOCUMENT_ISOLATION] Detected {len(regions)} regions across isolated documents")
    for region in regions:
        logger.debug(f"  → region_type={region.region_type} claim={region.claim_id[:8] if region.claim_id else 'N/A'}... doc={region.document_id[:8] if region.document_id else 'N/A'}... page={region.page}")
            
    return regions
