import logging
from statistics import median
from typing import Any, Dict, List

from .geometry_utils import get_bbox
from .models import FormField, Region

logger = logging.getLogger("parser-debug")


def extract_fields(region: Region) -> List[FormField]:
    """Extract key-value pairs from a form region using adaptive geometry.

    Values stay on the same row, stop at the next anchor, and stop at major
    horizontal gaps or column transitions.
    
    ADDED: Detect and skip table-like regions to prevent table headers from being extracted as fields.
    """
    fields: List[FormField] = []
    token_records = [_as_record(token) for token in region.tokens]
    lines = _adaptive_line_groups(token_records)
    
    # ADDED: Detect table-like structure and skip if found
    # Tables typically have 3+ rows with 2+ tokens each and consistent structure
    if len(lines) >= 3:
        line_token_counts = [len(line) for line in lines]
        mean_tokens = sum(line_token_counts) / len(line_token_counts) if line_token_counts else 0
        
        # Calculate variance to check consistency
        variance = 0.0
        if len(line_token_counts) >= 2:
            mean = sum(line_token_counts) / len(line_token_counts)
            variance = (sum((c - mean) ** 2 for c in line_token_counts) / len(line_token_counts)) ** 0.5
        
        # If 3+ rows, 2+ tokens per row on average, and consistent structure, it's likely a table
        if mean_tokens >= 2.0 and variance < 2.0:
            logger.debug(f"[TABLE_SKIP] Region has table-like structure (rows={len(lines)}, tokens/row={mean_tokens:.1f}, variance={variance:.1f}). Skipping form extraction.")
            return fields  # Return empty - table will be handled by reconstruct_table
    if not lines:
        return fields

    width_samples = [max(1.0, _token_width(token)) for token in region.tokens]
    median_width = median(width_samples) if width_samples else 40.0
    height_samples = [max(1.0, _token_height(token)) for token in region.tokens]
    med_h = median(height_samples) if height_samples else 12.0
    value_gap_threshold = max(36.0, median_width * 1.8)
    anchor_gap_threshold = max(24.0, median_width * 1.25)

    for line in lines:
        if not line:
            continue
        
        # ADDED: Skip lines that look like table headers/rows
        # Table headers often have multiple short tokens without clear key:value structure
        if len(line) >= 3:
            line_sorted = sorted(line, key=_token_x0)
            # Check if this looks like a table row (many tokens, aligned to multiple columns)
            non_empty_tokens = [t for t in line_sorted if str(t.get("text", "")).strip()]
            if len(non_empty_tokens) >= 3:
                # Heuristic: If many tokens, few are on left edge, they're likely column data not key:value
                left_aligned = sum(1 for t in non_empty_tokens if float(t.get("x0", 0)) < 100)
                if left_aligned < len(non_empty_tokens) * 0.3:  # Most tokens are spread across page
                    logger.debug(f"[TABLE_ROW_SKIP] Line has {len(non_empty_tokens)} spread tokens, looks like table row")
                    continue
                
                # Also skip if line contains table keywords
                line_text = " ".join(str(t.get("text", "")).strip() for t in non_empty_tokens).lower()
                table_keywords = ["result", "unit", "reference", "range", "interpretation", "day", "qty", "amount", "price", "strength", "medicine", "dosage", "frequency"]
                keyword_count = sum(1 for kw in table_keywords if kw in line_text)
                if keyword_count >= 2:
                    logger.debug(f"[TABLE_ROW_SKIP] Line contains table keywords: {line_text[:50]}")
                    continue

        line = sorted(line, key=_token_x0)

        i = 0
        while i < len(line):
            token = line[i]
            text = str(token.get("text", "")).strip()

            is_key = False
            key_text = ""
            key_tokens: List[Dict[str, Any]] = []

            if text.endswith(":") or text.endswith("-"):
                is_key = True
                key_text = text[:-1].strip()
                key_tokens = [token]
            elif text == ":" and i > 0:
                is_key = True
                key_text = str(line[i - 1].get("text", "")).strip()
                key_tokens = [line[i - 1], token]

            if not is_key and i == 0:
                concept_keys = [
                    "name",
                    "age",
                    "sex",
                    "gender",
                    "address",
                    "bill",
                    "date",
                    "reg",
                    "uid",
                    "ipd",
                    "opd",
                    "diagnosis",
                    "occupation",
                ]
                # ADDED: Only use concept_keys if it's truly a standalone key at line start, not part of table
                # If line has many tokens, it's less likely to be a form field
                if text.lower() in concept_keys and len(line) <= 5:
                    is_key = True
                    key_text = text
                    key_tokens = [token]

            if is_key and key_text:
                value_tokens: List[Dict[str, Any]] = []
                # Use per-line median width so long tokens in other lines don't inflate thresholds
                line_widths = [max(1.0, _token_width(t)) for t in line]
                line_median_w = median(line_widths) if line_widths else median_width
                local_value_gap = max(24.0, line_median_w * 1.4)
                local_anchor_gap = max(18.0, line_median_w * 1.1)

                current_x = float(token.get("x1", 0.0))
                j = i + 1
                while j < len(line):
                    next_token = line[j]
                    next_x0 = float(next_token.get("x0", 0.0))
                    if next_x0 <= current_x:
                        j += 1
                        continue
                    # ensure token is on roughly same baseline (don't cross vertical lines)
                    next_center = (float(next_token.get("y0", 0.0)) + float(next_token.get("y1", 0.0))) / 2.0
                    token_center = (float(token.get("y0", 0.0)) + float(token.get("y1", 0.0))) / 2.0
                    if abs(next_center - token_center) > max(6.0, med_h * 0.9):
                        break

                    if _looks_like_anchor(str(next_token.get("text", "")), line, j):
                        break

                    if float(next_token.get("x0", 0.0)) - current_x > local_value_gap:
                        break
                    if value_tokens and float(next_token.get("x0", 0.0)) - float(value_tokens[-1].get("x1", 0.0)) > local_anchor_gap:
                        break

                    value_tokens.append(next_token)
                    current_x = float(next_token.get("x1", 0.0))
                    j += 1

                if value_tokens:
                    value_text = " ".join(str(t.get("text", "")).strip() for t in value_tokens).strip()
                    if value_text:
                        fields.append(
                            FormField(
                                key=key_text,
                                value=value_text,
                                key_bbox=get_bbox(key_tokens),
                                value_bbox=get_bbox(value_tokens),
                                page=region.page,
                            )
                        )
                        i = j - 1
            i += 1

    return fields


def _looks_like_anchor(text: str, row: List[Dict[str, Any]], index: int) -> bool:
    token_text = text.strip()
    if token_text.endswith(":") or token_text.endswith("-"):
        return True
    if token_text == ":" and index > 0:
        return True

    phrase = token_text.lower()
    if index + 1 < len(row):
        phrase = f"{phrase} {str(row[index + 1].get('text', '')).strip().lower()}".strip()
    if index + 2 < len(row):
        phrase2 = f"{phrase} {str(row[index + 2].get('text', '')).strip().lower()}".strip()
        if phrase2 in {"patient name", "date of birth", "admission date", "discharge date", "hospital name", "occupation"}:
            return True

    return any(word in phrase for word in ["name", "age", "sex", "gender", "address", "occupation", "diagnosis", "patient", "admission", "discharge", "hospital", "doctor", "bill", "reg", "ipd", "doa"])


def _as_record(token: Any) -> Dict[str, Any]:
    if isinstance(token, dict):
        return token
    if hasattr(token, "model_dump"):
        return token.model_dump()
    if hasattr(token, "dict"):
        return token.dict()
    return {
        "text": getattr(token, "text", ""),
        "x0": getattr(token, "x0", 0.0),
        "y0": getattr(token, "y0", 0.0),
        "x1": getattr(token, "x1", 0.0),
        "y1": getattr(token, "y1", 0.0),
    }


def _token_x0(token: Any) -> float:
    return float(token.get("x0", 0.0) if isinstance(token, dict) else getattr(token, "x0", 0.0))


def _token_y0(token: Any) -> float:
    return float(token.get("y0", 0.0) if isinstance(token, dict) else getattr(token, "y0", 0.0))


def _token_x1(token: Any) -> float:
    return float(token.get("x1", 0.0) if isinstance(token, dict) else getattr(token, "x1", 0.0))


def _token_y1(token: Any) -> float:
    return float(token.get("y1", 0.0) if isinstance(token, dict) else getattr(token, "y1", 0.0))


def _token_width(token: Any) -> float:
    return _token_x1(token) - _token_x0(token)


def _token_height(token: Any) -> float:
    return _token_y1(token) - _token_y0(token)


def _adaptive_line_groups(tokens: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    if not tokens:
        return []

    sorted_tokens = sorted(tokens, key=lambda token: ((_token_y0(token) + _token_y1(token)) / 2.0, _token_x0(token)))
    heights = [max(1.0, _token_height(token)) for token in sorted_tokens]
    med_h = median(heights) if heights else 12.0
    # Stricter row grouping: reduce tolerance to avoid vertical merging
    row_tolerance = max(3.0, med_h * 0.3)
    gap_tolerance = max(3.0, med_h * 0.4)

    rows: List[List[Dict[str, Any]]] = []
    current_row: List[Dict[str, Any]] = []

    for token in sorted_tokens:
        if not current_row:
            current_row.append(token)
            continue

        row_center = sum(((_token_y0(row_token) + _token_y1(row_token)) / 2.0) for row_token in current_row) / len(current_row)
        row_top = min(_token_y0(row_token) for row_token in current_row)
        row_bottom = max(_token_y1(row_token) for row_token in current_row)
        row_height = max(1.0, row_bottom - row_top)
        token_center = (_token_y0(token) + _token_y1(token)) / 2.0
        token_height = max(1.0, _token_height(token))
        overlap = max(0.0, min(row_bottom, _token_y1(token)) - max(row_top, _token_y0(token)))
        overlap_ratio = overlap / max(1.0, min(row_height, token_height))
        center_delta = abs(token_center - row_center)
        gap = _token_y0(token) - row_bottom

        # Require stronger vertical overlap or very small center delta; avoid merging
        # tokens that are clearly on different lines even if whitespace is small.
        same_row = (
            overlap_ratio >= 0.8
            or (center_delta <= (row_tolerance * 0.5) and overlap_ratio >= 0.2)
            or gap <= max(1.0, med_h * 0.3)
        )
        if same_row:
            current_row.append(token)
        else:
            rows.append(sorted(current_row, key=_token_x0))
            current_row = [token]

    if current_row:
        rows.append(sorted(current_row, key=_token_x0))

    return rows
