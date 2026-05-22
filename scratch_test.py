import json
import sys
import re

# Add services folder to path
sys.path.append(r"C:\Project\ClaimGPT")

from services.parser_v2.models import Token
from services.parser_v2.geometry_utils import group_tokens_into_lines, group_lines_into_blocks

with open(r"C:\Project\ClaimGPT\tmp\parser_debug\89177cef-0a9c-4779-8899-693e951776d6_c87d85ae-1b47-40a2-b300-ae5edf48e677_real_tokens.json", "r", encoding="utf-8") as f:
    tokens_raw = json.load(f)

page1_tokens = [Token(**t) for t in tokens_raw if t.get("page") == 1]
print(f"Page 1 tokens count: {len(page1_tokens)}")

lines = group_tokens_into_lines(page1_tokens)
print(f"Grouped into {len(lines)} lines")

# Let's group lines into blocks with gap_threshold = 15.0 (which is the retry threshold)
blocks = group_lines_into_blocks(lines, gap_threshold=15.0)
print(f"Grouped into {len(blocks)} blocks")

page_height = max(t.y1 for t in page1_tokens) if page1_tokens else 1000.0

def original_classify(block):
    block_tokens = [t for line in block for t in line]
    block_top = min(t.y0 for t in block_tokens)
    block_bottom = max(t.y1 for t in block_tokens)
    text_content = " ".join(t.text for t in block_tokens)
    
    if block_bottom < page_height * 0.08:
        return "header"
    if block_top > page_height * 0.85:
        return "footer"
    return "paragraph/form/table (other)"

def new_classify(block):
    block_tokens = [t for line in block for t in line]
    block_top = min(t.y0 for t in block_tokens)
    block_bottom = max(t.y1 for t in block_tokens)
    text_content = " ".join(t.text for t in block_tokens)
    
    # Structural table check
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
    
    row_count_variance = 0.0
    if row_token_counts and len(row_token_counts) >= 3:
        mean_count = sum(row_token_counts) / len(row_token_counts)
        variance = sum((count - mean_count) ** 2 for count in row_token_counts) / len(row_token_counts)
        row_count_variance = variance ** 0.5
    
    consistent_row_structure = row_count_variance < 2.0
    multi_row_block = len(block) >= 3
    meaningful_tokens = mean_tokens_per_line >= 2.0
    
    is_table = False
    if (aligned_clusters and len(aligned_clusters) >= 2 and 
        (numeric_density >= 0.15 or mean_tokens_per_line >= 3.0 or len(block) >= 3)):
        is_table = True
    elif len(block) >= 3 and meaningful_tokens and consistent_row_structure:
        if mean_tokens_per_line >= 2.5:
            is_table = True

    if is_table:
        return "table"
        
    if block_bottom < page_height * 0.08:
        return "header"
    if block_top > page_height * 0.85:
        return "footer"
    return "other"

from services.parser_v2.region_classifier import classify_region

for idx, block in enumerate(blocks):
    block_tokens = [t for line in block for t in line]
    block_top = min(t.y0 for t in block_tokens)
    text_content = " ".join(t.text for t in block_tokens)
    print(f"\nBlock {idx} (top={block_top:.2f}, lines={len(block)}):")
    print(f"  Snippet: {text_content[:100]}...")
    orig = original_classify(block)
    new_c = new_classify(block)
    real_c = classify_region(block, page_height=page_height)
    print(f"  Original Mock: {orig}")
    print(f"  New Mock: {new_c}")
    print(f"  Real codebase classify_region: {real_c}")

