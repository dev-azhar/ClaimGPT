from typing import List, Dict
import logging
from .models import Token, Region, TableRegion, Row, Cell
from .geometry_utils import get_bbox

logger = logging.getLogger("parser-debug")

def group_tokens_into_raw_rows(tokens: List[Token], y_tolerance: float = 12.0) -> List[List[Token]]:
    """Groups tokens into horizontal rows based on Y center."""
    if not tokens:
        return []
    sorted_tokens = sorted(tokens, key=lambda t: t.y_center)
    rows = []
    current_row = []
    for token in sorted_tokens:
        if not current_row:
            current_row.append(token)
            continue
        avg_y = sum(t.y_center for t in current_row) / len(current_row)
        if abs(token.y_center - avg_y) <= y_tolerance:
            current_row.append(token)
        else:
            rows.append(current_row)
            current_row = [token]
    if current_row:
        rows.append(current_row)
    return rows

def reconstruct_table(region: Region) -> TableRegion:
    """Converts table-region tokens into reconstructed rows/cells using geometry."""
    logger.info("[PARSER_V2 TABLE RECONSTRUCTOR ACTIVE]")
    tokens = region.tokens
    
    # 1. Detect rows
    raw_rows = group_tokens_into_raw_rows(tokens)
    
    # 2. Merge multiline descriptions into logical rows
    # A raw row is a continuation of the previous row if the vertical gap is small
    # and its tokens overlap horizontally with the previous row's tokens.
    logical_rows = []
    current_logical_row = []
    
    for raw_row in raw_rows:
        if not current_logical_row:
            current_logical_row = list(raw_row)
            continue
            
        y_gap = min(t.y0 for t in raw_row) - max(t.y1 for t in current_logical_row)
        
        # Tighten continuation rules: rows are only merged if the gap is very small
        # AND they are not likely distinct line items (e.g. starting with a number/bullet)
        continuation = False
        if y_gap < 8.0: # Reduced from 15.0 to prevent greedy merging
            for token in raw_row:
                for existing in current_logical_row:
                    x_overlap = max(0, min(token.x1, existing.x1) - max(token.x0, existing.x0))
                    # Only merge if significant horizontal overlap exists (description wrapping)
                    if x_overlap > 5.0:
                        continuation = True
                        break
                if continuation:
                    break
                    
        if continuation:
            current_logical_row.extend(raw_row)
        else:
            logical_rows.append(current_logical_row)
            current_logical_row = list(raw_row)

            
    if current_logical_row:
        logical_rows.append(current_logical_row)
        
    # 3. Infer columns by X clustering
    x_positions = []
    for row in logical_rows:
        for token in row:
            x_positions.append(token.x0)
            
    clusters = []
    for x in x_positions:
        matched = False
        for cluster in clusters:
            if abs(cluster['mean'] - x) < 30.0:
                cluster['points'].append(x)
                cluster['mean'] = sum(cluster['points']) / len(cluster['points'])
                matched = True
                break
        if not matched:
            clusters.append({'mean': x, 'points': [x]})
            
    # Define column boundaries based on cluster means
    strong_columns = sorted([c['mean'] for c in clusters if len(c['points']) >= 2])
    
    # 4. Group logical rows into cells
    final_rows = []
    for r_idx, logical_row in enumerate(logical_rows):
        cells = []
        
        # Sort tokens by x0 for left-to-right processing
        sorted_tokens = sorted(logical_row, key=lambda t: t.x0)
        
        current_cell_tokens = []
        
        for token in sorted_tokens:
            if not current_cell_tokens:
                current_cell_tokens.append(token)
                continue
                
            last_token = current_cell_tokens[-1]
            x_gap = token.x0 - last_token.x1
            
            # If the tokens are close to each other, they belong to the same cell
            # OR if they don't cross a strong column boundary
            crosses_column = False
            for col_x in strong_columns:
                if last_token.x1 < col_x and token.x0 >= col_x - 10.0:
                    crosses_column = True
                    break
            
            if x_gap < 25.0 and not crosses_column:
                current_cell_tokens.append(token)
            else:
                # Flush current cell
                sorted_cell_tokens = sorted(current_cell_tokens, key=lambda x: (x.y0, x.x0))
                cells.append(Cell(
                    text=" ".join(t.text for t in sorted_cell_tokens),
                    bbox=get_bbox(current_cell_tokens),
                    tokens=current_cell_tokens
                ))
                current_cell_tokens = [token]
                
        if current_cell_tokens:
            sorted_cell_tokens = sorted(current_cell_tokens, key=lambda x: (x.y0, x.x0))
            cells.append(Cell(
                text=" ".join(t.text for t in sorted_cell_tokens),
                bbox=get_bbox(current_cell_tokens),
                tokens=current_cell_tokens
            ))
            
        final_rows.append(Row(
            row_index=r_idx,
            cells=cells,
            bbox=get_bbox(logical_row)
        ))

    return TableRegion(
        region_id=region.region_id,
        bbox=region.bbox,
        rows=final_rows
    )
