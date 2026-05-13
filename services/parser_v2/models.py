from typing import List, Dict, Any, Optional
from pydantic import BaseModel

class Token(BaseModel):
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page: int
    document_id: Optional[str] = None
    claim_id: Optional[str] = None

    @property
    def x_center(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def y_center(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


class Region(BaseModel):
    region_id: str
    region_type: str # "table" | "form" | "paragraph" | "header" | "footer"
    bbox: List[float] # [x0, y0, x1, y1]
    tokens: List[Token]
    page: int
    document_id: Optional[str] = None
    claim_id: Optional[str] = None
    confidence: float = 1.0
    model_name: Optional[str] = None



class Cell(BaseModel):
    cell_id: Optional[str] = None
    row_id: Optional[str] = None
    column_id: Optional[str] = None
    text: str
    bbox: List[float]
    tokens: List[Token]
    token_count: int = 0


class Row(BaseModel):
    row_id: Optional[str] = None
    row_index: int
    cells: List[Cell]
    bbox: List[float]
    token_count: int = 0
    source_row_ids: List[str] = []


class TableRegion(BaseModel):
    region_id: str
    bbox: List[float]
    rows: List[Row]
    page: int
    confidence: float = 1.0
    model_name: Optional[str] = None
    columns: List[Dict[str, Any]] = []
    multiline_merges: List[Dict[str, Any]] = []
    table_kind: Optional[str] = None
    table_kind_confidence: float = 0.0



class FormField(BaseModel):
    key: str
    value: str
    key_bbox: List[float]
    value_bbox: List[float]
    page: int

class DocumentStructure(BaseModel):
    regions: List[Region]
    tables: List[TableRegion]
    fields: List[FormField] = []
    normalized_fields: List[Dict[str, Any]] = []
    normalized_expenses: List[Dict[str, Any]] = []
    canonical_claim: Dict[str, Any] = {}
    claim_id: Optional[str] = None
    document_id: Optional[str] = None

