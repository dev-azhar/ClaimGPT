#!/usr/bin/env python3
import os
import sys
import numpy as np
from PIL import Image

# Add project root to python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.ocr.app.engine import _get_paddle_engine, _ensure_paddle_imported

def main():
    _ensure_paddle_imported()
    engine = _get_paddle_engine()
    if not engine:
        print("Engine not loaded!")
        return
        
    img_path = "tmp/test_image.png"
    if not os.path.exists(img_path):
        print(f"Sample image {img_path} not found!")
        return
        
    img = Image.open(img_path)
    rgb = img.convert("RGB")
    arr = np.array(rgb)
    
    try:
        print("Running predict...")
        result = engine.predict(
            arr,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            text_rec_score_thresh=0.0,
        )
        print("Predict result type:", type(result))
        if isinstance(result, list):
            print("Predict result length:", len(result))
            if len(result) > 0:
                print("First item type:", type(result[0]))
                print("First item sample:", str(result[0])[:500])
        elif isinstance(result, dict):
            print("Predict result keys:", result.keys())
            for k, v in result.items():
                print(f"Key: {k}, type: {type(v)}, length: {len(v) if hasattr(v, '__len__') else 'N/A'}")
                if hasattr(v, '__len__') and len(v) > 0:
                    print(f"  First element: {str(v[0])[:200]}")
    except Exception as e:
        print("predict failed:", e)
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
