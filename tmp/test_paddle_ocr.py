import easyocr
from pathlib import Path
import os
import json

IMG_DIR = Path('shared/temp_images')
print('Looking for images in', IMG_DIR.resolve())
imgs = sorted([p for p in IMG_DIR.iterdir() if p.suffix.lower() in ('.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp', '.webp')])
if not imgs:
    print('No images found in', IMG_DIR)
    raise SystemExit(0)

reader = easyocr.Reader(['en'])

for p in imgs[:10]:
    print('\n---')
    img_path_str = str(p.resolve())
    print('testing', img_path_str)
    try:
        # Use EasyOCR for image OCR
        result = reader.readtext(img_path_str, detail=1, paragraph=True)
        print(f'method=easyocr result_type={type(result)}')
        print('OCR result:', json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f'Inference failed for {p}')
        import traceback
        traceback.print_exc()
        print(f'Error: {e}')