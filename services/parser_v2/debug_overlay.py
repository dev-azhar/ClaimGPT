import os
import json
import logging
from typing import List
from PIL import Image, ImageDraw, ImageFont
from .models import DocumentStructure, Region, TableRegion

logger = logging.getLogger("parser-debug")

def generate_overlays(doc: DocumentStructure, output_dir: str = "debug", 
                      normalized_fields=None, normalized_expenses=None):
    os.makedirs(output_dir, exist_ok=True)
    
    # Write JSON outputs
    regions_json = [
        {
            "region_id": r.region_id,
            "region_type": r.region_type,
            "bbox": r.bbox,
            "tokens": [{"text": t.text, "bbox": [t.x0, t.y0, t.x1, t.y1]} for t in r.tokens]
        }
        for r in doc.regions
    ]
    with open(os.path.join(output_dir, "detected_regions.json"), "w", encoding="utf-8") as f:
        json.dump(regions_json, f, indent=2)
        
    tables_json = [
        {
            "region_id": t.region_id,
            "bbox": t.bbox,
            "table_kind": getattr(t, "table_kind", None),
            "table_kind_confidence": getattr(t, "table_kind_confidence", None),
            "columns": getattr(t, "columns", []),
            "multiline_merges": getattr(t, "multiline_merges", []),
            "rows": [
                {
                    "row_id": getattr(row, "row_id", None),
                    "row_index": row.row_index,
                    "bbox": row.bbox,
                    "token_count": getattr(row, "token_count", len([cell for cell in row.cells for _ in cell.tokens])),
                    "cells": [
                        {
                            "cell_id": getattr(cell, "cell_id", None),
                            "row_id": getattr(cell, "row_id", None),
                            "column_id": getattr(cell, "column_id", None),
                            "text": cell.text,
                            "bbox": cell.bbox,
                            "token_count": getattr(cell, "token_count", len(cell.tokens)),
                        }
                        for cell in row.cells
                    ]
                }
                for row in t.rows
            ]
        }
        for t in doc.tables
    ]
    with open(os.path.join(output_dir, "reconstructed_rows.json"), "w", encoding="utf-8") as f:
        json.dump(tables_json, f, indent=2)

    with open(os.path.join(output_dir, "reconstructed_tables.json"), "w", encoding="utf-8") as f:
        json.dump(tables_json, f, indent=2)

    cell_assignments = []
    column_clusters = []
    multiline_merges = []
    for t in doc.tables:
        for column in getattr(t, "columns", []) or []:
            column_clusters.append({"table_id": t.region_id, **column})
        for merge in getattr(t, "multiline_merges", []) or []:
            multiline_merges.append({"table_id": t.region_id, **merge})
        for row in t.rows:
            for cell in row.cells:
                for token in cell.tokens:
                    cell_assignments.append({
                        "table_id": t.region_id,
                        "row_id": getattr(row, "row_id", None),
                        "column_id": getattr(cell, "column_id", None),
                        "cell_id": getattr(cell, "cell_id", None),
                        "token_text": token.text,
                        "bbox": [token.x0, token.y0, token.x1, token.y1],
                        "page": token.page,
                        "document_id": token.document_id,
                        "claim_id": token.claim_id,
                    })

    with open(os.path.join(output_dir, "cell_assignments.json"), "w", encoding="utf-8") as f:
        json.dump(cell_assignments, f, indent=2)
    with open(os.path.join(output_dir, "column_clusters.json"), "w", encoding="utf-8") as f:
        json.dump(column_clusters, f, indent=2)
    with open(os.path.join(output_dir, "multiline_merges.json"), "w", encoding="utf-8") as f:
        json.dump(multiline_merges, f, indent=2)

    # Export Form Fields
    fields_json = [
        {
            "key": f.key,
            "value": f.value,
            "key_bbox": f.key_bbox,
            "value_bbox": f.value_bbox,
            "page": f.page
        }
        for f in doc.fields
    ]
    with open(os.path.join(output_dir, "extracted_forms.json"), "w", encoding="utf-8") as f:
        json.dump(fields_json, f, indent=2)

    
    if normalized_fields is not None:
        with open(os.path.join(output_dir, "normalized_fields.json"), "w", encoding="utf-8") as f:
            json.dump(normalized_fields, f, indent=2)
            
    if normalized_expenses is not None:
        with open(os.path.join(output_dir, "normalized_expenses.json"), "w", encoding="utf-8") as f:
            json.dump(normalized_expenses, f, indent=2)

    # Calculate canvas size
    max_x, max_y = 0.0, 0.0
    for r in doc.regions:
        if r.bbox[2] > max_x: max_x = r.bbox[2]
        if r.bbox[3] > max_y: max_y = r.bbox[3]
        
    canvas_w = int(max_x + 100)
    canvas_h = int(max_y + 100)
    
    if canvas_w < 100 or canvas_h < 100:
        return # Nothing to draw
        
    # Generate regions overlay (Now called segmented_regions_overlay.png)
    regions_img = Image.new("RGB", (canvas_w, canvas_h), "white")
    regions_draw = ImageDraw.Draw(regions_img)

    
    colors = {
        "table": "blue",
        "expense_table": "blue",
        "patient_form": "green",
        "hospitalization_form": "green",
        "paragraph": "gray",
        "header": "yellow",
        "footer": "gray",
        "diagnosis_section": "orange"
    }

    
    for r in doc.regions:
        color = colors.get(r.region_type, "black")
        regions_draw.rectangle(r.bbox, outline=color, width=3)
        try:
            regions_draw.text((r.bbox[0], r.bbox[1] - 15), r.region_type, fill=color)
        except Exception:
            pass # Pillow text drawing can fail if no default font, it's fine for simple debug
        
        # Draw tokens for context
        for t in r.tokens:
            regions_draw.rectangle([t.x0, t.y0, t.x1, t.y1], outline="lightgray", width=1)
            try:
                # Add tiny text for tokens
                regions_draw.text((t.x0, t.y0), t.text[:5], fill="gray")
            except Exception:
                pass
            
    regions_img.save(os.path.join(output_dir, "segmented_regions_overlay.png"))
    
    # Generate tables overlay
    tables_img = Image.new("RGB", (canvas_w, canvas_h), "white")
    tables_draw = ImageDraw.Draw(tables_img)
    
    # Draw original tokens in light gray for background context
    for r in doc.regions:
        for t in r.tokens:
            tables_draw.rectangle([t.x0, t.y0, t.x1, t.y1], outline="#eeeeee", width=1)
            try:
                tables_draw.text((t.x0, t.y0), t.text, fill="#cccccc")
            except Exception:
                pass

    for t in doc.tables:
        # Draw table boundary
        tables_draw.rectangle(t.bbox, outline="red", width=4)

        for column in getattr(t, "columns", []) or []:
            x0 = column.get("x0")
            x1 = column.get("x1")
            if x0 is not None:
                tables_draw.line([(x0, t.bbox[1]), (x0, t.bbox[3])], fill="purple", width=2)
            if x1 is not None:
                tables_draw.line([(x1, t.bbox[1]), (x1, t.bbox[3])], fill="purple", width=2)
        
        for row in t.rows:
            # Draw row boundary
            tables_draw.rectangle(row.bbox, outline="blue", width=2)
            
            for cell in row.cells:
                # Draw cell boundary
                tables_draw.rectangle(cell.bbox, outline="green", width=1)
                for token in cell.tokens:
                    tables_draw.rectangle([token.x0, token.y0, token.x1, token.y1], outline="#b0b0b0", width=1)
                    try:
                        tables_draw.text((token.x0, token.y0), token.text[:8], fill="#666666")
                    except Exception:
                        pass
                
    tables_img.save(os.path.join(output_dir, "table_grid_overlay.png"))
    tables_img.save(os.path.join(output_dir, "table_overlay.png"))
    # Export Phase 3 Model Artifacts
    try:
        layout_regions = [
            {
                "id": r.region_id,
                "type": r.region_type,
                "bbox": r.bbox,
                "page": r.page,
                "confidence": r.confidence,
                "model": r.model_name
            }
            for r in doc.regions
        ]
        with open(os.path.join(output_dir, "layout_model_regions.json"), "w") as f:
            json.dump(layout_regions, f, indent=2)
            
        pp_tables = [
            {
                "id": t.region_id,
                "bbox": t.bbox,
                "rows_count": len(t.rows),
                "confidence": t.confidence,
                "model": t.model_name,
                "table_kind": getattr(t, "table_kind", None),
            }
            for t in doc.tables
        ]
        with open(os.path.join(output_dir, "ppstructure_tables.json"), "w") as f:
            json.dump(pp_tables, f, indent=2)
            
        logger.info("[DEBUG] Phase 3 model artifacts exported")
    except Exception as e:
        logger.warning(f"Failed to export Phase 3 artifacts: {e}")
