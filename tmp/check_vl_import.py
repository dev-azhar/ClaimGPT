import services.ocr.app.engine as e
from services.ocr.app.config import settings

e._ensure_paddle_imported()
print("enable_paddle_vl=", settings.enable_paddle_vl)
print("has_paddle=", e._HAS_PADDLE)
print("has_paddle_vl=", e._HAS_PADDLE_VL)
print("paddle_class=", getattr(e.PaddleOCR, "__name__", str(type(e.PaddleOCR))))
print("vl_class=", getattr(e.PaddleOCRVL, "__name__", str(type(e.PaddleOCRVL))))
