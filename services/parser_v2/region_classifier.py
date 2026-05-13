import logging
from typing import List
from .models import Token

logger = logging.getLogger("parser-debug")

def classify_region(block: List[List[Token]], page_height: float = 1000.0) -> str:
    """
    Classifies a block of lines into: 
    'header', 'footer', 'table', 'patient_form', 'hospitalization_form', 'paragraph'
    using geometry-first logic with purity scoring.
    """
    if not block:
        return "paragraph"

    # 1. Page Position (Header/Footer/Isolation)
    block_tokens = [t for line in block for t in line]
    block_top = min(t.y0 for t in block_tokens)
    block_bottom = max(t.y1 for t in block_tokens)
    block_height = block_bottom - block_top
    
    if block_bottom < page_height * 0.08: # Top 8% of page
        return "header"
    if block_top > page_height * 0.85: # Bottom 15%
        return "footer"

    # 2. Table Structural Detection (pure geometry, no keyword dependence)
    x_centers = [t.x_center for line in block for t in line]
    row_token_counts = [len(line) for line in block]
    numeric_tokens = sum(1 for t in block_tokens if any(c.isdigit() for c in t.text))

    clusters = []
    x_tol = max(18.0, page_height * 0.012)
    for x in sorted(x_centers):
        matched = False
        for cluster in clusters:
            if abs(cluster["mean"] - x) <= x_tol:
                cluster["points"].append(x)
                cluster["mean"] = sum(cluster["points"]) / len(cluster["points"])
                matched = True
                break
        if not matched:
            clusters.append({"mean": x, "points": [x], "rows": set()})

    for row_idx, line in enumerate(block):
        line_centers = [token.x_center for token in line]
        for cluster in clusters:
            if any(abs(center - cluster["mean"]) <= x_tol for center in line_centers):
                cluster["rows"].add(row_idx)

    aligned_clusters = [c for c in clusters if len(c["rows"]) >= max(2, int(len(block) * 0.35))]
    text_content = " ".join(t.text for t in block_tokens)
    numeric_density = numeric_tokens / max(1, len(block_tokens))
    mean_tokens_per_line = sum(row_token_counts) / max(1, len(row_token_counts))

    if len(aligned_clusters) >= 2 and (numeric_density >= 0.15 or mean_tokens_per_line >= 3.0 or len(block) >= 3):
        return "table"

    # 3. Form Detection (Key:Value patterns)
    key_value_rows = 0
    for line in block:
        has_colon = any(":" in t.text or "-" in t.text for t in line)
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
        if any(kw in block_text for kw in ["patient", "name", "sex", "gender", "age"]):
            return "patient_form"
        if any(kw in block_text for kw in ["hospital", "admission", "details"]):
            return "hospitalization_form"
        return "patient_form"

    return "paragraph"
