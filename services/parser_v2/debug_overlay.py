import os
import json
from typing import List
from PIL import Image, ImageDraw, ImageFont
from .models import DocumentStructure, Region, TableRegion

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
            "rows": [
                {
                    "row_index": row.row_index,
                    "bbox": row.bbox,
                    "cells": [
                        {
                            "text": cell.text,
                            "bbox": cell.bbox
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
        
        for row in t.rows:
            # Draw row boundary
            tables_draw.rectangle(row.bbox, outline="blue", width=2)
            
            for cell in row.cells:
                # Draw cell boundary
                tables_draw.rectangle(cell.bbox, outline="green", width=1)
                
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
                "model": t.model_name
            }
            for t in doc.tables
        ]
        with open(os.path.join(output_dir, "ppstructure_tables.json"), "w") as f:
            json.dump(pp_tables, f, indent=2)
            
        logger.info("[DEBUG] Phase 3 model artifacts exported")
    except Exception as e:
        logger.warning(f"Failed to export Phase 3 artifacts: {e}")
