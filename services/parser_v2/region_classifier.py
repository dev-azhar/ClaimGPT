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

    def _looks_like_expense_table(block_tokens: List[Token], text_content: str) -> bool:
        expense_keywords = (
            "room rent",
            "nursing",
            "consultation",
            "registration",
            "pharmacy",
            "diagnostics",
            "miscellaneous",
            "lab",
            "laboratory",
            "icu",
            "surgery",
            "charges",
            "fees",
            "disposal",
            "supplies",
            "consumables",
        )
        summary_keywords = (
            "grand total",
            "net payable",
            "amount claimed",
            "admissible amount",
            "patient share",
            "co-pay",
            "copay",
            "balance",
            "total amount",
        )

        lower_text = text_content.lower()
        keyword_hits = sum(1 for keyword in expense_keywords if keyword in lower_text)

        # If summary keywords exist, do not reject if there are multiple unique expense keywords present
        if any(keyword in lower_text for keyword in summary_keywords):
            if keyword_hits < 2:
                return False

        has_date = any(
            any(char.isdigit() for char in token.text)
            and ("-" in token.text or "/" in token.text)
            for token in block_tokens
        )
        numeric_tokens = sum(1 for token in block_tokens if any(char.isdigit() for char in token.text))

        # We relax the has_date requirement if we have high keyword hits and numeric density
        if has_date:
            return numeric_tokens >= 2 and keyword_hits >= 1
        else:
            return numeric_tokens >= 5 and keyword_hits >= 2

    # 1. Structural features & geometry (computed early for guarding)
    block_tokens = [t for line in block for t in line]
    block_top = min(t.y0 for t in block_tokens)
    block_bottom = max(t.y1 for t in block_tokens)
    block_height = block_bottom - block_top
    text_content = " ".join(t.text for t in block_tokens)

    # Pre-calculate structural table detection
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
    numeric_density = numeric_tokens / max(1, len(block_tokens))
    mean_tokens_per_line = sum(row_token_counts) / max(1, len(row_token_counts))
    
    # ADDED: More aggressive table detection
    # If block has 3+ rows with consistent token structure, likely a table
    row_count_variance = 0.0
    if row_token_counts and len(row_token_counts) >= 3:
        mean_count = sum(row_token_counts) / len(row_token_counts)
        variance = sum((count - mean_count) ** 2 for count in row_token_counts) / len(row_token_counts)
        row_count_variance = variance ** 0.5
    
    consistent_row_structure = row_count_variance < 3.5  # Relaxed from 2.0 to 3.5 to handle variable columns / multi-line cells
    multi_row_block = len(block) >= 3
    meaningful_tokens = mean_tokens_per_line >= 2.0

    is_structural_table = False
    if (aligned_clusters and len(aligned_clusters) >= 2 and 
        (numeric_density >= 0.15 or mean_tokens_per_line >= 3.0 or len(block) >= 3)):
        is_structural_table = True
    elif len(block) >= 3 and meaningful_tokens and consistent_row_structure:
        if mean_tokens_per_line >= 2.5:
            is_structural_table = True

    # 2. Page Position checks with structural table guards
    if _looks_like_expense_table(block_tokens, text_content):
        return "expense_table"
    
    if block_bottom < page_height * 0.08: # Top 8% of page
        if not is_structural_table:
            return "header"
    if block_top > page_height * 0.85: # Bottom 15%
        if not is_structural_table:
            return "footer"

    # 3. Table structural return
    if is_structural_table:
        if len(block) >= 3 and meaningful_tokens and consistent_row_structure and mean_tokens_per_line >= 2.5:
            logger.debug(f"[TABLE_DETECT] Multi-row block: rows={len(block)}, tokens/row={mean_tokens_per_line:.1f}, variance={row_count_variance:.1f}")
        return "table"


    # 3. Form Detection (Key:Value patterns) - BUT SKIP IF LIKELY TABLE
    # Don't classify as form if it has table-like characteristics
    if len(block) >= 3 and meaningful_tokens and consistent_row_structure:
        # If it has table-like multi-row structure, don't treat as form even if some rows have colons
        logger.debug(f"[FORM_REJECT] Block has table-like structure (rows={len(block)}, consistent={consistent_row_structure}), rejecting form classification")
    else:
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
