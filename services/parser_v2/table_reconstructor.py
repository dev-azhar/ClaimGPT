from typing import List, Dict, Any, Optional
import logging
import re
from statistics import median

from .models import Token, Region, TableRegion, Row, Cell
from .geometry_utils import get_bbox, x_overlap

logger = logging.getLogger("parser-debug")


def _token_stats(tokens: List[Token]) -> Dict[str, float]:
    heights = [max(1.0, t.height) for t in tokens]
    widths = [max(1.0, t.width) for t in tokens]
    y_centers = [t.y_center for t in tokens]
    vertical_gaps: List[float] = []
    sorted_by_top = sorted(tokens, key=lambda t: t.y0)
    prev_bottom: Optional[float] = None
    for tok in sorted_by_top:
        if prev_bottom is not None:
            vertical_gaps.append(max(0.0, tok.y0 - prev_bottom))
        prev_bottom = tok.y1 if prev_bottom is None else max(prev_bottom, tok.y1)
    return {
        "median_height": median(heights) if heights else 12.0,
        "median_width": median(widths) if widths else 40.0,
        "median_y_center": median(y_centers) if y_centers else 0.0,
        "median_vertical_gap": median(vertical_gaps) if vertical_gaps else 0.0,
    }


def _cluster_tokens_into_rows(tokens: List[Token]) -> List[List[Token]]:
    if not tokens:
        return []

    stats = _token_stats(tokens)
    median_h = stats["median_height"]
    # tolerance for vertical grouping
    row_tol = max(4.0, median_h * 0.6)

    # We'll maintain row buckets with running bbox and token list and assign
    # tokens by vertical overlap ratio and baseline proximity.
    sorted_tokens = sorted(tokens, key=lambda t: (t.y0, t.y_center, t.x0))
    rows: List[List[Token]] = []
    row_bboxes: List[List[float]] = []  # [top, bottom]

    for token in sorted_tokens:
        t_top = token.y0
        t_bottom = token.y1
        t_h = max(1.0, token.height)
        placed = False

        # Try to find a matching existing row by vertical overlap / baseline
        for ri, (r_top, r_bottom) in enumerate(row_bboxes):
            overlap = max(0.0, min(r_bottom, t_bottom) - max(r_top, t_top))
            # row height estimate
            r_h = max(1.0, r_bottom - r_top)
            overlap_ratio = overlap / max(1.0, min(r_h, t_h))
            center_delta = abs(token.y_center - ((r_top + r_bottom) / 2.0))

            # Prefer real vertical overlap; only allow center-based grouping when
            # centers are very close relative to median height.
            if overlap_ratio >= 0.45 or (overlap_ratio >= 0.2 and center_delta <= max(3.0, row_tol * 0.5)):
                # assign token to this row and expand bbox
                rows[ri].append(token)
                row_bboxes[ri][0] = min(r_top, t_top)
                row_bboxes[ri][1] = max(r_bottom, t_bottom)
                placed = True
                break

        if not placed:
            # create new row bucket
            rows.append([token])
            row_bboxes.append([t_top, t_bottom])

    # Sort rows top->bottom and tokens within rows left->right
    rows_sorted = [sorted(r, key=lambda t: t.x0) for r in rows]
    rows_sorted = sorted(rows_sorted, key=lambda r: min(t.y0 for t in r))
    return rows_sorted


def _merge_multiline_rows(raw_rows: List[List[Token]], stats: Dict[str, float]) -> tuple[List[List[Token]], List[Dict[str, Any]]]:
    if not raw_rows:
        return [], []

    # Find the horizontal boundaries of the table to define the right-aligned amount zone
    all_x1 = [t.x1 for r in raw_rows for t in r]
    table_right = max(all_x1) if all_x1 else 1.0
    table_left = min(t.x0 for r in raw_rows for t in r) if raw_rows else 0.0
    table_width = table_right - table_left
    right_zone = table_left + table_width * 0.72

    def _has_right_amount(row_tokens: List[Token]) -> bool:
        import re
        for t in row_tokens:
            if t.x_center >= right_zone:
                # Clean amount prefix / suffix
                s = t.text.strip().replace(",", "").replace(" ", "")
                s = re.sub(r"^(?:rs|inr|₹)\.?\s*", "", s, flags=re.IGNORECASE)
                if re.fullmatch(r"\d+(?:\.\d+)?", s):
                    return True
        return False

    logical_rows: List[List[Token]] = [list(raw_rows[0])]
    merges: List[Dict[str, Any]] = []
    continuation_gap = max(5.0, stats["median_height"] * 0.9)

    for row_index, row in enumerate(raw_rows[1:], start=1):
        prev_row = logical_rows[-1]

        # Safeguard 1: If both rows have their own right-aligned numeric amounts,
        # they represent distinct logical line items and must not be merged.
        if _has_right_amount(prev_row) and _has_right_amount(row):
            logical_rows.append(list(row))
            continue

        # Safeguard 2: If the current row starts with a sequence index (e.g. "1.", "2.", "13.")
        # it is a new logical item and must not be merged.
        first_token_text = row[0].text.strip() if row else ""
        starts_with_index = bool(re.match(r"^\d+[\.\)]\s*$", first_token_text)) or bool(re.match(r"^\d+\.$", first_token_text))
        if starts_with_index:
            logical_rows.append(list(row))
            continue
        prev_left = min(t.x0 for t in prev_row)
        prev_right = max(t.x1 for t in prev_row)
        prev_bottom = max(t.y1 for t in prev_row)
        prev_width = max(1.0, prev_right - prev_left)

        cur_left = min(t.x0 for t in row)
        cur_right = max(t.x1 for t in row)
        cur_top = min(t.y0 for t in row)
        cur_width = max(1.0, cur_right - cur_left)
        gap = cur_top - prev_bottom
        horizontal_overlap = x_overlap([prev_left, 0.0, prev_right, 1.0], [cur_left, 0.0, cur_right, 1.0])
        overlap_ratio = horizontal_overlap / max(1.0, min(prev_width, cur_width))
        indent_delta = abs(cur_left - prev_left)

        # More conservative continuation rules: require strong horizontal overlap
        # *and* similar widths/indent to be considered a multiline continuation.
        width_similar = abs(prev_width - cur_width) <= max(1.0, stats["median_width"] * 1.0)
        is_continuation = (
            gap >= 0.0
            and gap <= continuation_gap
            and (
                (overlap_ratio >= 0.75 and indent_delta <= stats["median_width"] * 0.15)
                or (overlap_ratio >= 0.6 and width_similar and indent_delta <= stats["median_width"] * 0.25)
            )
        )
        if is_continuation:
            merges.append({
                "from_row_index": len(logical_rows) - 1,
                "continuation_row_index": row_index,
                "gap": round(gap, 2),
                "overlap_ratio": round(overlap_ratio, 3),
                "indent_delta": round(indent_delta, 2),
            })
            logical_rows[-1] = sorted(prev_row + list(row), key=lambda t: (t.y0, t.x0))
        else:
            logical_rows.append(list(row))

    return logical_rows, merges


def _cluster_columns(rows: List[List[Token]], stats: Dict[str, float]) -> List[Dict[str, Any]]:
    if not rows:
        return []

    x_tol = max(10.0, min(18.0, stats["median_width"] * 0.5))
    all_centers: List[float] = []
    per_row_centers: List[List[float]] = []
    for row in rows:
        centers = sorted([t.x_center for t in row])
        per_row_centers.append(centers)
        all_centers.extend(centers)

    # Augment centers by estimating word/numeric centers inside very wide tokens
    augmented_centers = list(all_centers)
    for row in rows:
        for t in row:
            if t.width > stats["median_width"] * 2.0 and any(ch.isdigit() for ch in t.text):
                parts = t.text.split()
                if len(parts) <= 1:
                    continue
                total_len = len(t.text)
                # approximate character offsets to estimate per-word center
                offset = 0
                for p in parts:
                    start = t.text.find(p, offset)
                    if start < 0:
                        offset += len(p) + 1
                        continue
                    center_char = start + max(0, len(p) // 2)
                    frac = center_char / max(1, total_len)
                    est = t.x0 + frac * t.width
                    augmented_centers.append(est)
                    offset = start + len(p)

    if not augmented_centers:
        return []
    all_centers = sorted(augmented_centers)

    # Greedy 1D clustering of x centers
    clusters: List[Dict[str, Any]] = []
    for c in all_centers:
        if not clusters:
            clusters.append({"x_center": c, "points": [c], "rows": set()})
            continue
        last = clusters[-1]
        if abs(last["x_center"] - c) <= x_tol:
            last["points"].append(c)
            last["x_center"] = sum(last["points"]) / len(last["points"])
        else:
            clusters.append({"x_center": c, "points": [c], "rows": set()})

    # assign rows_seen by checking per-row membership
    for ri, centers in enumerate(per_row_centers):
        for cluster in clusters:
            # a row supports a cluster if any center in that row falls within x_tol
            for c in centers:
                if abs(cluster["x_center"] - c) <= x_tol:
                    cluster["rows"].add(ri)
                    break

    # Filter clusters by support across rows
    min_support = max(1, int(len(rows) * 0.35))
    strong = [c for c in clusters if len(c["rows"]) >= min_support]
    strong = sorted(strong, key=lambda c: c["x_center"])

    # If we couldn't find multiple supported clusters, attempt to split by large gaps
    if not strong or len(strong) == 1:
        # Consider large gaps in all_centers to create additional column splits
        gaps = [(all_centers[i + 1] - all_centers[i], i) for i in range(len(all_centers) - 1)]
        gaps.sort(reverse=True)
        # allow up to 6 columns, choose up to N-1 largest gaps as split points where gap is significant
        split_indices = []
        avg_gap = sum(g for g, _ in gaps) / max(1, len(gaps)) if gaps else 0.0
        for gap_val, idx in gaps[:5]:
            if gap_val >= max(60.0, avg_gap * 2.0):
                split_indices.append(idx)

        if split_indices:
            split_indices = sorted(split_indices)
            parts = []
            start = 0
            for si in split_indices:
                parts.append(all_centers[start: si + 1])
                start = si + 1
            parts.append(all_centers[start:])
            strong = [{"x_center": sum(p) / len(p), "points": p, "rows": set()} for p in parts if p]

        # Heuristic: if we still have a single cluster, try to detect a
        # right-aligned numeric column by looking for narrow tokens on the
        # right side of the table (typical amounts). Split into left/right
        # if sufficient evidence exists.
        if (not strong or len(strong) == 1):
            all_x0 = [t.x0 for row in rows for t in row]
            all_x1 = [t.x1 for row in rows for t in row]
            table_left = min(all_x0) if all_x0 else 0.0
            table_right = max(all_x1) if all_x1 else 0.0
            table_w = max(1.0, table_right - table_left)
            # narrow tokens likely to be numeric values
            narrow_thresh = stats["median_width"] * 1.8
            right_zone = table_left + table_w * 0.6
            right_narrow = [t.x_center for row in rows for t in row if t.width <= narrow_thresh and t.x_center >= right_zone]
            if len(right_narrow) >= max(2, int(len(rows) * 0.5)):
                left_centers = [c for c in all_centers if c < min(right_narrow)]
                left_center = sum(left_centers) / len(left_centers) if left_centers else (table_left + (table_w * 0.3))
                right_center = sum(right_narrow) / len(right_narrow)
                strong = [
                    {"x_center": left_center, "points": left_centers or all_centers, "rows": set()},
                    {"x_center": right_center, "points": right_narrow, "rows": set()},
                ]

    if not strong:
        # fallback single column spanning whole table
        all_x0 = [t.x0 for row in rows for t in row]
        all_x1 = [t.x1 for row in rows for t in row]
        return [{
            "column_id": "col_0",
            "column_index": 0,
            "x_center": sum(all_x0 + all_x1) / max(1, len(all_x0) + len(all_x1)),
            "x0": min(all_x0) if all_x0 else 0.0,
            "x1": max(all_x1) if all_x1 else 0.0,
            "rows_seen": len(rows),
            "token_count": len(all_x0),
            "alignment_score": 0.0,
        }]

    # Build final columns using midpoints between centers
    centers = [c["x_center"] for c in strong]
    columns: List[Dict[str, Any]] = []
    for idx, cluster in enumerate(strong):
        left = (centers[idx - 1] + cluster["x_center"]) / 2.0 if idx > 0 else cluster["x_center"] - stats["median_width"] * 0.9
        right = (cluster["x_center"] + centers[idx + 1]) / 2.0 if idx + 1 < len(centers) else cluster["x_center"] + stats["median_width"] * 0.9
        columns.append({
            "column_id": f"col_{idx}",
            "column_index": idx,
            "x_center": cluster["x_center"],
            "x0": left,
            "x1": right,
            "rows_seen": len(cluster.get("rows", [])),
            "token_count": len(cluster.get("points", [])),
            "alignment_score": round(len(cluster.get("rows", [])) / max(1, len(rows)), 3),
        })

    return columns


def _assign_rows_and_cells(rows: List[List[Token]], columns: List[Dict[str, Any]]) -> tuple[List[Row], List[Dict[str, Any]]]:
    row_models: List[Row] = []
    assignments: List[Dict[str, Any]] = []
    column_ids = [c["column_id"] for c in columns] or ["col_0"]

    for row_index, row_tokens in enumerate(rows):
        row_id = f"row_{row_index}"
        row_top = min(t.y0 for t in row_tokens)
        row_bottom = max(t.y1 for t in row_tokens)
        row_left = min(t.x0 for t in row_tokens)
        row_right = max(t.x1 for t in row_tokens)
        by_column: Dict[str, List[Token]] = {cid: [] for cid in column_ids}

        for token in sorted(row_tokens, key=lambda t: t.x0):
            column_id = "col_0"
            assign_conf = 0.0
            if columns:
                # Prefer columns that have strong horizontal overlap with token bbox
                overlaps = []
                for col in columns:
                    col_x0 = col.get("x0", col.get("x_center"))
                    col_x1 = col.get("x1", col.get("x_center"))
                    # horizontal overlap between token and column box
                    ov = max(0.0, min(col_x1, token.x1) - max(col_x0, token.x0))
                    ov_ratio = ov / max(1.0, token.width)
                    overlaps.append((col, ov_ratio))

                # pick column with max overlap_ratio, else nearest center
                best_col, best_ov = max(overlaps, key=lambda it: it[1])
                if best_ov >= 0.35:
                    column_id = best_col["column_id"]
                    assign_conf = round(best_ov, 3)
                else:
                    # fallback to nearest center
                    best_col = min(columns, key=lambda col: abs(token.x_center - col["x_center"]))
                    column_id = best_col["column_id"]
                    # distance-based confidence normalized by column width
                    dist = abs(token.x_center - best_col["x_center"])
                    col_w = max(1.0, best_col.get("x1", best_col.get("x_center", 0.0)) - best_col.get("x0", best_col.get("x_center", 0.0)))
                    assign_conf = round(max(0.0, 1.0 - (dist / (col_w * 1.5))), 3)
            by_column.setdefault(column_id, []).append(token)
            assignments.append({
                "token_text": token.text,
                "bbox": [token.x0, token.y0, token.x1, token.y1],
                "page": token.page,
                "claim_id": getattr(token, "claim_id", None),
                "document_id": getattr(token, "document_id", None),
                "row_id": row_id,
                "column_id": column_id,
                "cell_id": f"{row_id}__{column_id}",
                "assign_confidence": assign_conf,
            })

        cells: List[Cell] = []
        for column in columns or [{"column_id": "col_0", "column_index": 0}]:
            cell_tokens = by_column.get(column["column_id"], [])
            if not cell_tokens:
                continue
            sorted_tokens = sorted(cell_tokens, key=lambda t: (t.y0, t.x0))
            cells.append(Cell(
                cell_id=f"{row_id}__{column['column_id']}",
                row_id=row_id,
                column_id=column["column_id"],
                text=" ".join(t.text for t in sorted_tokens).strip(),
                bbox=get_bbox(sorted_tokens),
                tokens=sorted_tokens,
                token_count=len(sorted_tokens),
            ))

        row_models.append(Row(
            row_id=row_id,
            row_index=row_index,
            cells=sorted(cells, key=lambda c: c.column_id or ""),
            bbox=[row_left, row_top, row_right, row_bottom],
            token_count=len(row_tokens),
            source_row_ids=[row_id],
        ))

    return row_models, assignments


def _infer_table_kind(table_rows: List[Row], columns: List[Dict[str, Any]]) -> tuple[str, float]:
    if not table_rows:
        return "generic_table", 0.0

    def _looks_numeric(text: str) -> bool:
        s = str(text or "").strip().lower()
        if not s:
            return False
        s = s.replace("₹", "").replace("rs.", "").replace("rs", "").replace("inr", "")
        s = s.replace(",", "").replace(" ", "")
        if s.startswith("(") and s.endswith(")"):
            s = "-" + s[1:-1]
        return bool(re.fullmatch(r"-?\d+(?:\.\d+)?", s))

    def _contains_header_keywords(text: str) -> bool:
        lower = text.lower()
        return any(
            kw in lower
            for kw in {
                "description",
                "particular",
                "service",
                "item",
                "qty",
                "quantity",
                "rate",
                "gross",
                "np",
                "payable",
                "amount",
                "charges",
                "total",
            }
        )

    column_count = len(columns) or max((len(r.cells) for r in table_rows), default=1)
    numeric_ratios: List[float] = []
    text_lengths: List[int] = []

    for idx in range(column_count):
        cells = [row.cells[idx] for row in table_rows if idx < len(row.cells)]
        if not cells:
            continue
        numeric_hits = 0
        for cell in cells:
            if _looks_numeric(cell.text):
                numeric_hits += 1
            text_lengths.append(len(cell.text.split()))
        numeric_ratios.append(numeric_hits / len(cells))

    header_like = False
    if table_rows and table_rows[0].cells:
        first_row = table_rows[0].cells
        first_text_ratio = sum(1 for c in first_row if not any(ch.isdigit() for ch in c.text)) / max(1, len(first_row))
        header_like = first_text_ratio >= 0.7 and len(first_row) >= 2

    max_numeric_ratio = max(numeric_ratios) if numeric_ratios else 0.0
    last_numeric_ratio = numeric_ratios[-1] if numeric_ratios else 0.0
    avg_text_len = sum(text_lengths) / max(1, len(text_lengths))

    # Robust expense detection: require a right-side numeric column with
    # high numeric presence and reasonably consistent numeric cells across rows.
    numeric_columns = [idx for idx, r in enumerate(numeric_ratios) if r >= 0.5]
    rightmost_numeric = numeric_columns[-1] if numeric_columns else None

    # header keyword detection (common billing headers)
    header_keywords = {"description", "charges", "total", "qty", "days", "amount", "charges_", "total charges", "medicine", "drug", "medication", "procedure", "service", "fee", "cost", "price", "bill", "invoice"}
    header_found = False
    header_rows_text = []
    for row in table_rows[:3]:
        if row.cells:
            header_rows_text.append(" ".join(c.text.lower() for c in row.cells))
    if header_rows_text:
        header_found = any(any(k in row_text for k in header_keywords) for row_text in header_rows_text)

    # Fallback detection for OCR-noisy but valid expense tables:
    # strong rightmost numeric column + at least one header-like row token.
    header_like_hint = any(_contains_header_keywords(row_text) for row_text in header_rows_text)
    data_rows = table_rows[1:] if len(table_rows) > 1 else table_rows
    if data_rows and column_count >= 4:
        rows_with_amount_like_tail = 0
        for row in data_rows:
            row_cells = sorted(row.cells, key=lambda c: c.column_id or "")
            tail_cells = row_cells[-3:] if len(row_cells) >= 3 else row_cells
            tail_numeric = sum(1 for c in tail_cells if _looks_numeric(c.text))
            if tail_numeric >= 2:
                rows_with_amount_like_tail += 1
        amount_tail_ratio = rows_with_amount_like_tail / max(1, len(data_rows))
        if rightmost_numeric is not None and amount_tail_ratio >= 0.45 and (header_found or header_like_hint):
            return "expenses", 0.88

    if rightmost_numeric is not None and len(table_rows) >= 2 and header_found:
        return "expenses", 0.92
    if header_like and column_count >= 4 and max_numeric_ratio < 0.45 and avg_text_len >= 1.4:
        return "medications", 0.76
    if header_like and column_count >= 3 and max_numeric_ratio >= 0.45:
        if numeric_ratios.count(max_numeric_ratio) >= 2:
            return "vitals", 0.72
        return "lab_results", 0.68
    return "generic_table", 0.35


def reconstruct_table(region: Region) -> TableRegion:
    """Convert table-region tokens into reconstructed rows/cells using geometry-first reconstruction."""
    logger.info("[PARSER_V2 TABLE RECONSTRUCTOR ACTIVE]")
    tokens = region.tokens
    if not tokens:
        return TableRegion(
            region_id=region.region_id,
            bbox=region.bbox,
            rows=[],
            page=region.page,
            claim_id=region.claim_id,
            document_id=region.document_id,
            confidence=1.0,
            model_name="geometry-grid-v1",
            columns=[],
            multiline_merges=[],
            table_kind="generic_table",
            table_kind_confidence=0.0,
        )

    stats = _token_stats(tokens)
    raw_rows = _cluster_tokens_into_rows(tokens)
    logical_rows, multiline_merges = _merge_multiline_rows(raw_rows, stats)
    columns = _cluster_columns(logical_rows, stats)
    row_models, cell_assignments = _assign_rows_and_cells(logical_rows, columns)
    table_kind, table_kind_confidence = _infer_table_kind(row_models, columns)

    table_region = TableRegion(
        region_id=region.region_id,
        bbox=region.bbox,
        rows=row_models,
        page=region.page,
        claim_id=region.claim_id,
        document_id=region.document_id,
        confidence=1.0,
        model_name="geometry-grid-v1",
        columns=columns,
        multiline_merges=multiline_merges,
        table_kind=table_kind,
        table_kind_confidence=table_kind_confidence,
    )
    table_region.__dict__["cell_assignments"] = cell_assignments
    table_region.__dict__["raw_row_count"] = len(raw_rows)
    table_region.__dict__["logical_row_count"] = len(logical_rows)

    logger.info(
        "[PARSER_V2 TABLE RECONSTRUCTOR] raw_rows=%d logical_rows=%d columns=%d kind=%s",
        len(raw_rows),
        len(logical_rows),
        len(columns),
        table_kind,
    )
    return table_region
