import logging
from typing import List
from .models import Token

logger = logging.getLogger("parser-debug")

def classify_region(block: List[List[Token]], page_height: float = 1000.0) -> str:
    """
    Classifies a block of lines into: 
    'header', 'footer', 'expense_table', 'patient_form', 'hospitalization_form', 'paragraph'
    using geometry-first logic with purity scoring.
    """
    if not block:
        return "paragraph"

    # 1. Page Position (Header/Footer/Isolation)
    block_tokens = [t for line in block for t in line]
    block_top = min(t.y0 for t in block_tokens)
    block_bottom = max(t.y1 for t in block_tokens)
    block_height = block_bottom - block_top
    
    if block_bottom < 80: # Top 8% of page
        return "header"
    if block_top > page_height - 150: # Bottom 15%
        # Signature/Footer often have low alignment
        return "footer"

    # Prevent full-page region creation unless extremely consistent
    if block_height > page_height * 0.7:
        # If it's too big, it's likely a merged block that needs further splitting
        # But for classification, we treat it as paragraph to avoid swallowing everything into a table
        pass 

    # 2. Table Structural Detection (Multi-column alignment)
    x0_positions = []
    for line in block:
        for token in line:
            x0_positions.append(token.x0)
            
    # Cluster X coordinates to find columns
    clusters = []
    for x in x0_positions:
        matched = False
        for cluster in clusters:
            if abs(cluster['mean'] - x) < 15.0:
                cluster['points'].append(x)
                cluster['mean'] = sum(cluster['points']) / len(cluster['points'])
                matched = True
                break
        if not matched:
            clusters.append({'mean': x, 'points': [x]})
            
    # A table column must appear in multiple rows
    aligned_columns = 0
    numeric_columns = 0
    for cluster in clusters:
        lines_hit = set()
        numeric_hits = 0
        for i, line in enumerate(block):
            for token in line:
                if abs(token.x0 - cluster['mean']) < 15.0:
                    lines_hit.add(i)
                    # Check if token is likely a currency/numeric amount
                    if any(c.isdigit() for c in token.text):
                        numeric_hits += 1
        
        # A column must hit at least 40% of the rows in a block
        if len(lines_hit) >= max(3, len(block) * 0.4): 
            aligned_columns += 1
            if numeric_hits >= len(lines_hit) * 0.5:
                numeric_columns += 1

    # Numeric density check
    text_content = " ".join(t.text for t in block_tokens)
    digit_count = sum(c.isdigit() for c in text_content)
    numeric_density = digit_count / len(text_content) if text_content else 0

    # PURITY RULE: Table must have >= 3 aligned numeric rows AND >= 2 numeric columns
    # AND cannot exceed 45% of page height unless numeric density is very high
    is_pure_table = (aligned_columns >= 4 and numeric_columns >= 1) or (aligned_columns >= 3 and numeric_density > 0.2)
    
    if is_pure_table:
        if block_height < page_height * 0.45 or numeric_density > 0.3:
            return "expense_table"

    # 3. Form Detection (Key:Value patterns)
    key_value_rows = 0
    for line in block:
        has_colon = any(t.text.strip().endswith(":") for t in line)
        has_large_gap = False
        if len(line) >= 2:
            line_tokens = sorted(line, key=lambda t: t.x0)
            for i in range(len(line_tokens) - 1):
                if line_tokens[i+1].x0 - line_tokens[i].x1 > 40.0:
                    has_large_gap = True
                    break
        if has_colon or has_large_gap:
            key_value_rows += 1

    if key_value_rows >= 2 or (len(block) <= 5 and key_value_rows >= 1):
        block_text = text_content.lower()
        if "patient" in block_text or "name" in block_text or "sex" in block_text:
            return "patient_form"
        if "hospital" in block_text or "admission" in block_text or "details" in block_text:
            return "hospitalization_form"
        return "patient_form"

    return "paragraph"
