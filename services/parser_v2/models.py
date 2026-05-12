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
    confidence: float = 1.0
    model_name: Optional[str] = None



class Cell(BaseModel):
    text: str
    bbox: List[float]
    tokens: List[Token]


class Row(BaseModel):
    row_index: int
    cells: List[Cell]
    bbox: List[float]


class TableRegion(BaseModel):
    region_id: str
    bbox: List[float]
    rows: List[Row]
    confidence: float = 1.0
    model_name: Optional[str] = None



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

