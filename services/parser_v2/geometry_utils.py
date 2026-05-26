from typing import Any, List, Tuple
from .models import Token

def get_bbox(tokens: List[Token]) -> List[float]:
    if not tokens:
        return [0, 0, 0, 0]
    return [
        min(_coord(t, "x0") for t in tokens),
        min(_coord(t, "y0") for t in tokens),
        max(_coord(t, "x1") for t in tokens),
        max(_coord(t, "y1") for t in tokens)
    ]


def _coord(token: Any, name: str) -> float:
    if isinstance(token, dict):
        return float(token.get(name, 0.0))
    return float(getattr(token, name, 0.0))

def group_tokens_into_lines(tokens: List[Token], y_tolerance: float = 12.0) -> List[List[Token]]:
    """Groups tokens into horizontal lines based on Y center overlap."""
    if not tokens:
        return []
    sorted_tokens = sorted(tokens, key=lambda t: _coord(t, "y_center"))
    lines = []
    current_line = []
    for token in sorted_tokens:
        if not current_line:
            current_line.append(token)
            continue
        avg_y = sum(_coord(t, "y_center") for t in current_line) / len(current_line)
        if abs(_coord(token, "y_center") - avg_y) <= y_tolerance:
            current_line.append(token)
        else:
            lines.append(sorted(current_line, key=lambda t: _coord(t, "x0")))
            current_line = [token]
    if current_line:
        lines.append(sorted(current_line, key=lambda t: _coord(t, "x0")))
    return lines

def group_lines_into_blocks(lines: List[List[Token]], gap_threshold: float = 25.0) -> List[List[List[Token]]]:
    """Groups lines into blocks based on vertical gaps."""
    if not lines:
        return []
    # Sort lines by their top bounding box edge
    sorted_lines = sorted(lines, key=lambda line: min(_coord(t, "y0") for t in line))
    blocks = []
    current_block = []
    for line in sorted_lines:
        if not current_block:
            current_block.append(line)
            continue
        
        last_line = current_block[-1]
        last_line_bottom = max(_coord(t, "y1") for t in last_line)
        current_line_top = min(_coord(t, "y0") for t in line)
        
        # Use the provided gap_threshold for better section isolation
        if (current_line_top - last_line_bottom) <= gap_threshold:
            current_block.append(line)
        else:
            blocks.append(current_block)
            current_block = [line]
    if current_block:
        blocks.append(current_block)
    return blocks


def bbox_intersection(box1: List[float], box2: List[float]) -> float:
    x_left = max(box1[0], box2[0])
    y_top = max(box1[1], box2[1])
    x_right = min(box1[2], box2[2])
    y_bottom = min(box1[3], box2[3])

    if x_right < x_left or y_bottom < y_top:
        return 0.0

    return (x_right - x_left) * (y_bottom - y_top)

def bbox_area(box: List[float]) -> float:
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])

def y_overlap(box1: List[float], box2: List[float]) -> float:
    y_top = max(box1[1], box2[1])
    y_bottom = min(box1[3], box2[3])
    if y_bottom <= y_top:
        return 0.0
    return y_bottom - y_top

def x_overlap(box1: List[float], box2: List[float]) -> float:
    x_left = max(box1[0], box2[0])
    x_right = min(box1[2], box2[2])
    if x_right <= x_left:
        return 0.0
    return x_right - x_left

def are_same_row(y1_center: float, y2_center: float, threshold: float = 10.0) -> bool:
    return abs(y1_center - y2_center) < threshold

def merge_bboxes(box1: List[float], box2: List[float]) -> List[float]:
    return [
        min(box1[0], box2[0]),
        min(box1[1], box2[1]),
        max(box1[2], box2[2]),
        max(box1[3], box2[3])
    ]

def get_center(box: List[float]) -> Tuple[float, float]:
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
