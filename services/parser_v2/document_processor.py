import logging
import uuid
from typing import List, Dict, Any, Optional
from PIL import Image
import numpy as np

from .models import DocumentStructure, Region, TableRegion, Row, Cell, Token
from services.parser.app.layout_analyzer import analyze_layout

logger = logging.getLogger(__name__)

class DocumentProcessor:
    """
    Orchestrates specialized document AI models (PP-StructureV3) 
    for layout and table detection.
    """

    @staticmethod
    def process(tokens: List[Dict[str, Any]], page_images: Optional[Dict[int, Image]] = None, document_paths: Optional[List[str]] = None, debug_dir: str = "debug") -> DocumentStructure:

        """
        Runs model-assisted layout and table detection on OCR tokens and page images.
        """
        logger.info("[PHASE 3] Starting Model-Assisted Document Processing")
        
        if not page_images and not document_paths:
            logger.warning("[PHASE 3] No images or document paths provided. Models cannot run. Falling back to heuristics.")
            return None # Pipeline will handle fallback


        try:
            # 1. Run PP-StructureV3 via existing layout_analyzer
            layout_result = analyze_layout(tokens, page_images=page_images, document_paths=document_paths, debug_dump_dir=debug_dir)

            
            # 2. Map layout sections to DocumentStructure
            doc = DocumentStructure(regions=[], tables=[], fields=[])
            
            for section in layout_result.get("sections", []):
                region_type = section.get("type", "text")
                bbox = section.get("bbox")
                page = section.get("page", 1)
                region_tokens = [Token(**t) for t in section.get("tokens", [])]
                
                if region_type == "table":
                    # Reconstruct TableRegion from PP-Structure cell output
                    table = DocumentProcessor._map_table_region(section, page)
                    doc.tables.append(table)
                    # Also add as a generic region for visualization
                    doc.regions.append(Region(
                        region_id=table.region_id,
                        region_type="table",
                        bbox=bbox,
                        tokens=region_tokens,
                        page=page,
                        confidence=section.get("confidence", 0.9),
                        model_name="PP-StructureV3"
                    ))
                else:
                    # Map other regions (text, title, footer, key_value)
                    # We map 'key_value' to 'patient_form' for our pipeline
                    mapped_type = region_type
                    if region_type in ["key_value", "form"]:
                        mapped_type = "patient_form"
                        
                    doc.regions.append(Region(
                        region_id=str(uuid.uuid4())[:8],
                        region_type=mapped_type,
                        bbox=bbox,
                        tokens=region_tokens,
                        page=page,
                        confidence=section.get("confidence", 0.8),
                        model_name="PP-StructureV3"
                    ))
            
            return doc

        except Exception as e:
            logger.error(f"[PHASE 3] Model-assisted processing failed: {e}")
            return None

    @staticmethod
    def _map_table_region(section: Dict[str, Any], page: int) -> TableRegion:
        """Maps PP-Structure table output to parser_v2 TableRegion model."""
        bbox = section.get("bbox", [0, 0, 0, 0])
        rows_data = section.get("cells", [])
        
        reconstructed_rows = []
        for i, row_cells in enumerate(rows_data):
            cells = []
            for cell_data in row_cells:
                # PP-Structure might return cell bbox and tokens
                cell_tokens = [Token(**t) for t in cell_data.get("tokens", [])]
                cells.append(Cell(
                    text=cell_data.get("text", ""),
                    bbox=cell_data.get("bbox", [0, 0, 0, 0]),
                    tokens=cell_tokens
                ))
            
            # Compute row bbox from cells
            if cells:
                row_x0 = min(c.bbox[0] for c in cells)
                row_y0 = min(c.bbox[1] for c in cells)
                row_x1 = max(c.bbox[2] for c in cells)
                row_y1 = max(c.bbox[3] for c in cells)
                row_bbox = [row_x0, row_y0, row_x1, row_y1]
            else:
                row_bbox = [0, 0, 0, 0]

            reconstructed_rows.append(Row(
                row_index=i,
                cells=cells,
                bbox=row_bbox
            ))

        return TableRegion(
            region_id=f"table_{str(uuid.uuid4())[:8]}",
            bbox=bbox,
            rows=reconstructed_rows,
            page=page,
            tokens=[Token(**t) for t in section.get("tokens", [])],
            region_type="table",
            confidence=section.get("confidence", 0.9),
            model_name="PP-StructureV3"
        )
