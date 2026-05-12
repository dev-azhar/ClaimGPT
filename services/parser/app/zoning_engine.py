"""Document Zoning Engine — Detect logical regions BEFORE extraction.

This module identifies document sections (zones) by analyzing:
- Vertical whitespace gaps → Section boundaries
- Y-coordinate clustering → Horizontal row detection
- Heading anchors → Section start detection
- Font density changes → Region transitions
- Bounding box grouping → Physical grouping

CRITICAL: Zones are detected BEFORE extraction. Classification happens AFTER.

NOT:
- Global page reconstruction
- Keyword-based extraction
- Assumptions about document structure
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple, Optional, Set
from collections import defaultdict
import re

logger = logging.getLogger("parser.zoning_engine")

# =====================================================================
# DATA STRUCTURES
# =====================================================================

@dataclass
class Token:
    """OCR token with spatial information."""
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page: int = 0
    
    @property
    def width(self) -> float:
        return self.x1 - self.x0
    
    @property
    def height(self) -> float:
        return self.y1 - self.y0
    
    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2
    
    @property
    def center_y(self) -> float:
        return (self.y0 + self.y1) / 2
    
    @property
    def bbox(self) -> Tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)


@dataclass
class Row:
    """Horizontal row of tokens (same Y coordinate)."""
    tokens: List[Token]
    y_min: float = field(default_factory=float)
    y_max: float = field(default_factory=float)
    
    def __post_init__(self):
        if self.tokens:
            if not self.y_min:
                self.y_min = min(t.y0 for t in self.tokens)
            if not self.y_max:
                self.y_max = max(t.y1 for t in self.tokens)
    
    @property
    def text(self) -> str:
        """Concatenate token text."""
        return " ".join(t.text for t in self.tokens)
    
    @property
    def bbox(self) -> Tuple[float, float, float, float]:
        if not self.tokens:
            return (0, 0, 0, 0)
        x0 = min(t.x0 for t in self.tokens)
        y0 = min(t.y0 for t in self.tokens)
        x1 = max(t.x1 for t in self.tokens)
        y1 = max(t.y1 for t in self.tokens)
        return (x0, y0, x1, y1)


@dataclass
class Zone:
    """Logical document region."""
    section_type: str  # "form_section", "expense_table", "diagnosis_block", etc.
    bbox: Tuple[float, float, float, float]  # [x0, y0, x1, y1]
    tokens: List[Token] = field(default_factory=list)
    rows: List[Row] = field(default_factory=list)
    confidence: float = 0.5  # 0.0-1.0 based on heuristics
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def text(self) -> str:
        return " ".join(t.text for t in self.tokens)
    
    @property
    def x0(self) -> float:
        return self.bbox[0]
    
    @property
    def y0(self) -> float:
        return self.bbox[1]
    
    @property
    def x1(self) -> float:
        return self.bbox[2]
    
    @property
    def y1(self) -> float:
        return self.bbox[3]
    
    @property
    def width(self) -> float:
        return self.x1 - self.x0
    
    @property
    def height(self) -> float:
        return self.y1 - self.y0
    
    @property
    def aspect_ratio(self) -> float:
        """Width / height ratio."""
        if self.height == 0:
            return 0
        return self.width / self.height


# =====================================================================
# ZONING ENGINE
# =====================================================================

class ZoningEngine:
    """Detect logical document zones before extraction."""
    
    # Heading anchors that mark section starts
    HEADING_ANCHORS = {
        "Patient Name": r"patient\s+name",
        "Age": r"(?:age|dob|date\s+of\s+birth)",
        "Insurance": r"insurance|payer|policy",
        "Hospital": r"hospital|facility|clinic",
        "Admission": r"admission|admit\s+date",
        "Discharge": r"discharge",
        "Diagnosis": r"diagnosis|assessment|icd",
        "Medication": r"medication|medicine|drug|prescription",
        "Lab": r"lab|laboratory|investigation|test\s+result",
        "Expense": r"expense|charge|amount|bill|cost|fee",
        "Vitals": r"vital|bp|blood\s+pressure|pulse|temperature",
    }
    
    def __init__(
        self,
        y_cluster_tolerance: float = 5.0,
        x_cluster_tolerance: float = 10.0,
        min_vertical_gap: float = 50.0,
        min_zone_height: float = 20.0,
    ):
        """
        Initialize zoning engine.
        
        Parameters
        ----------
        y_cluster_tolerance : float
            Tokens within this Y-distance are in same row (pixels)
        x_cluster_tolerance : float
            X-positions within this distance are in same column (pixels)
        min_vertical_gap : float
            Minimum Y-gap to consider section boundary (pixels)
        min_zone_height : float
            Minimum zone height to create zone (pixels)
        """
        self.y_cluster_tolerance = y_cluster_tolerance
        self.x_cluster_tolerance = x_cluster_tolerance
        self.min_vertical_gap = min_vertical_gap
        self.min_zone_height = min_zone_height
    
    def detect_zones(self, tokens: List[Token]) -> List[Zone]:
        """
        Detect logical zones from tokens.
        
        Parameters
        ----------
        tokens : List[Token]
            Flat list of OCR tokens
        
        Returns
        -------
        List[Zone]
            Detected zones with bounding boxes and tokens
        """
        if not tokens:
            logger.warning("No tokens provided to zoning engine")
            return []
        
        logger.info(f"Zoning {len(tokens)} tokens")
        
        # Step 1: Group tokens into rows by Y-coordinate
        rows = self._cluster_by_y(tokens)
        logger.info(f"Clustered into {len(rows)} rows")
        
        # Step 2: Find vertical gaps between rows (section boundaries)
        gaps = self._find_vertical_gaps(rows)
        logger.info(f"Found {len(gaps)} vertical gaps at Y positions: {[round(g, 1) for g in gaps]}")
        
        # Step 3: Group rows into zones based on gaps
        zones = self._merge_rows_into_zones(rows, gaps, tokens)
        logger.info(f"Created {len(zones)} zones")
        
        # Step 4: Assign confidence to zones
        self._compute_zone_confidence(zones)
        
        return zones
    
    def _cluster_by_y(self, tokens: List[Token]) -> List[Row]:
        """
        Group tokens by Y-coordinate into rows.
        
        Parameters
        ----------
        tokens : List[Token]
            Flat list of tokens
        
        Returns
        -------
        List[Row]
            Sorted rows (top to bottom)
        """
        if not tokens:
            return []
        
        # Sort tokens by Y, then X
        sorted_tokens = sorted(tokens, key=lambda t: (t.y0, t.x0))
        
        rows = []
        current_row = [sorted_tokens[0]]
        
        for token in sorted_tokens[1:]:
            # Check if token is in same row as last token
            if abs(token.y0 - current_row[-1].y0) <= self.y_cluster_tolerance:
                current_row.append(token)
            else:
                # Start new row
                rows.append(Row(tokens=current_row))
                current_row = [token]
        
        # Add last row
        if current_row:
            rows.append(Row(tokens=current_row))
        
        return rows
    
    def _find_vertical_gaps(self, rows: List[Row], percentile: float = 75.0) -> List[float]:
        """
        Find large vertical gaps between rows (section boundaries).
        
        Parameters
        ----------
        rows : List[Row]
            Rows sorted top to bottom
        percentile : float
            Gap size percentile to consider as boundary (75th percentile)
        
        Returns
        -------
        List[float]
            Y-coordinates of large gaps
        """
        if len(rows) < 2:
            return []
        
        # Calculate gaps between consecutive rows
        gaps_list = []
        gap_positions = []
        
        for i in range(len(rows) - 1):
            current_row = rows[i]
            next_row = rows[i + 1]
            
            gap_size = next_row.y_min - current_row.y_max
            if gap_size > 0:
                gaps_list.append(gap_size)
                gap_positions.append((gap_size, next_row.y_min))
        
        if not gaps_list:
            return []
        
        # Find gaps above 75th percentile or above min_vertical_gap
        gaps_list.sort()
        threshold_idx = int(len(gaps_list) * percentile / 100.0)
        threshold = max(gaps_list[threshold_idx], self.min_vertical_gap)
        
        significant_gaps = [
            y_pos for gap_size, y_pos in gap_positions if gap_size >= threshold
        ]
        
        return sorted(significant_gaps)
    
    def _merge_rows_into_zones(
        self,
        rows: List[Row],
        gap_positions: List[float],
        all_tokens: List[Token]
    ) -> List[Zone]:
        """
        Group rows into zones based on gap boundaries.
        
        Parameters
        ----------
        rows : List[Row]
            Rows sorted top to bottom
        gap_positions : List[float]
            Y-coordinates where significant gaps occur
        all_tokens : List[Token]
            All tokens for zone assignment
        
        Returns
        -------
        List[Zone]
            Zones with assigned tokens
        """
        if not rows:
            return []
        
        zones = []
        
        # Define zone boundaries based on gaps
        boundaries = [rows[0].y_min] + gap_positions + [rows[-1].y_max + 100]
        
        for i in range(len(boundaries) - 1):
            y_start = boundaries[i]
            y_end = boundaries[i + 1]
            
            # Get rows in this boundary
            zone_rows = [
                row for row in rows
                if row.y_min >= y_start and row.y_max <= y_end
            ]
            
            if not zone_rows:
                continue
            
            # Get tokens in this zone
            zone_tokens = [
                t for t in all_tokens
                if y_start <= t.y0 < y_end
            ]
            
            if not zone_tokens:
                continue
            
            # Calculate zone bbox
            x0 = min(t.x0 for t in zone_tokens)
            y0 = min(t.y0 for t in zone_tokens)
            x1 = max(t.x1 for t in zone_tokens)
            y1 = max(t.y1 for t in zone_tokens)
            
            # Check minimum zone height
            zone_height = y1 - y0
            if zone_height < self.min_zone_height:
                continue
            
            zone = Zone(
                section_type="unclassified",  # Will be classified later
                bbox=(x0, y0, x1, y1),
                tokens=zone_tokens,
                rows=zone_rows,
                confidence=0.5
            )
            zones.append(zone)
        
        return zones
    
    def _compute_zone_confidence(self, zones: List[Zone]):
        """
        Compute confidence score for each zone.
        
        Parameters
        ----------
        zones : List[Zone]
            Zones to score
        """
        for zone in zones:
            confidence = 0.5
            
            # Boost confidence if zone has clear heading anchors
            zone_text_lower = zone.text.lower()
            for anchor_pattern in self.HEADING_ANCHORS.values():
                if re.search(anchor_pattern, zone_text_lower):
                    confidence = min(confidence + 0.15, 0.95)
                    break
            
            # Boost confidence if zone has consistent structure
            if len(zone.rows) >= 2:
                # Check if rows have consistent width
                widths = [row.bbox[2] - row.bbox[0] for row in zone.rows]
                if widths:
                    avg_width = sum(widths) / len(widths)
                    variance = sum((w - avg_width) ** 2 for w in widths) / len(widths)
                    consistency = max(0, 1.0 - (variance / (avg_width ** 2) if avg_width > 0 else 1.0))
                    confidence = (confidence + consistency) / 2
            
            zone.confidence = confidence
    
    def detect_columns(self, zone: Zone, tolerance: Optional[float] = None) -> List[Tuple[float, float]]:
        """
        Detect column boundaries within a zone using X-clustering.
        
        Parameters
        ----------
        zone : Zone
            Zone to analyze
        tolerance : float, optional
            X-clustering tolerance (defaults to self.x_cluster_tolerance)
        
        Returns
        -------
        List[Tuple[float, float]]
            Column boundaries as (x_min, x_max) tuples
        """
        if tolerance is None:
            tolerance = self.x_cluster_tolerance
        
        if not zone.tokens:
            return []
        
        # Collect all X-positions (left edges)
        x_positions = sorted(set(t.x0 for t in zone.tokens))
        
        if not x_positions:
            return []
        
        # Cluster X-positions
        columns = []
        current_cluster = [x_positions[0]]
        
        for x in x_positions[1:]:
            if x - current_cluster[-1] <= tolerance:
                current_cluster.append(x)
            else:
                # Save current cluster as column
                columns.append((min(current_cluster), max(current_cluster)))
                current_cluster = [x]
        
        # Add last cluster
        if current_cluster:
            columns.append((min(current_cluster), max(current_cluster)))
        
        return columns
    
    def has_aligned_columns(self, zone: Zone, min_columns: int = 2, min_rows: int = 2) -> bool:
        """
        Check if zone has aligned columns (indicator of table).
        
        Parameters
        ----------
        zone : Zone
            Zone to check
        min_columns : int
            Minimum columns needed
        min_rows : int
            Minimum rows needed
        
        Returns
        -------
        bool
            True if zone appears to be a table
        """
        if len(zone.rows) < min_rows:
            return False
        
        columns = self.detect_columns(zone)
        return len(columns) >= min_columns
    
    def has_label_colon_pattern(self, zone: Zone, min_patterns: int = 1) -> bool:
        """
        Check if zone has label:value pattern (indicator of form).
        
        Parameters
        ----------
        zone : Zone
            Zone to check
        min_patterns : int
            Minimum patterns needed
        
        Returns
        -------
        bool
            True if zone appears to be a form
        """
        count = 0
        for row in zone.rows:
            # Look for "label:" patterns in first 30 chars of row
            text = row.text[:30]
            if ":" in text or "-" in text[:15]:
                # Check if it looks like a label
                before_colon = text.split(":")[0] if ":" in text else text.split("-")[0]
                words = before_colon.split()
                if words and all(len(w) < 20 for w in words):
                    count += 1
        
        return count >= min_patterns
    
    def is_header_or_footer(self, zone: Zone) -> bool:
        """
        Check if zone is document header or footer.
        
        Parameters
        ----------
        zone : Zone
            Zone to check
        
        Returns
        -------
        bool
            True if zone appears to be header/footer
        """
        if zone.height < 50:  # Headers/footers are typically short
            return True
        
        # Check if content is company name, logo, address, etc.
        text = zone.text.lower()
        header_keywords = ["logo", "header", "address", "phone", "email", "website", "copyright", "page"]
        return any(kw in text for kw in header_keywords)


# =====================================================================
# CONVENIENCE FUNCTIONS
# =====================================================================

def create_token(text: str, x0: float, y0: float, x1: float, y1: float, page: int = 0) -> Token:
    """Create a Token object."""
    return Token(text=text, x0=x0, y0=y0, x1=x1, y1=y1, page=page)


def detect_zones(
    tokens: List[Token],
    y_cluster_tolerance: float = 5.0,
    x_cluster_tolerance: float = 10.0,
    min_vertical_gap: float = 50.0,
    min_zone_height: float = 20.0,
) -> List[Zone]:
    """
    Convenience function to detect zones.
    
    Parameters
    ----------
    tokens : List[Token]
        OCR tokens
    y_cluster_tolerance : float
        Y-distance tolerance for row clustering
    x_cluster_tolerance : float
        X-distance tolerance for column clustering
    min_vertical_gap : float
        Minimum gap for section boundary
    min_zone_height : float
        Minimum zone height
    
    Returns
    -------
    List[Zone]
        Detected zones
    """
    engine = ZoningEngine(
        y_cluster_tolerance=y_cluster_tolerance,
        x_cluster_tolerance=x_cluster_tolerance,
        min_vertical_gap=min_vertical_gap,
        min_zone_height=min_zone_height,
    )
    return engine.detect_zones(tokens)
