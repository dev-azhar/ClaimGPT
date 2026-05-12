import uuid
import logging
from typing import List, Dict
from .models import Token, Region
from .geometry_utils import get_bbox, group_tokens_into_lines, group_lines_into_blocks
from .region_classifier import classify_region

logger = logging.getLogger("parser-debug")

# Grouping functions moved to geometry_utils.py

# is_table_block removed in favor of region_classifier.classify_region

def detect_regions(tokens: List[Token]) -> List[Region]:
    """Splits page into structural regions using pure geometry."""
    logger.info("[PARSER_V2 REGION DETECTOR ACTIVE]")
    if not tokens:
        return []
        
    pages: Dict[int, List[Token]] = {}
    for token in tokens:
        pages.setdefault(token.page, []).append(token)
        
    regions = []
    
    for page, page_tokens in pages.items():
        lines = group_tokens_into_lines(page_tokens)
        blocks = group_lines_into_blocks(lines, gap_threshold=35.0)
        
        for block in blocks:
            flat_tokens = [token for line in block for token in line]
            bbox = get_bbox(flat_tokens)
            region_id = str(uuid.uuid4())
            
            # Use Geometry-First Classifier (Phase 2)
            region_type = classify_region(block)
                
            regions.append(Region(
                region_id=region_id,
                region_type=region_type,
                bbox=bbox,
                tokens=flat_tokens,
                page=page
            ))
            
    return regions
