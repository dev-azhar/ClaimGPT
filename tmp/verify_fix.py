from app.engine import _ocr_with_paddle
from PIL import Image

img = Image.open('/app/tmp/test_image.png')
text, conf, tokens = _ocr_with_paddle(img)
print(f"Text length: {len(text)}")
print(f"Tokens count: {len(tokens)}")
if tokens:
    print("First 5 tokens:")
    for t in tokens[:5]:
        print(f"Text: '{t['text']}' -> Coordinates: ({t['x0']}, {t['y0']}, {t['x1']}, {t['y1']})")
else:
    print("No tokens extracted!")
