import services.ocr.app.engine as e
from services.ocr.app.config import settings

print("enable_paddle_vl=", settings.enable_paddle_vl)
eng = e._get_paddle_engine()
print("engine_kind=", e._paddle_engine_kind)
print("engine_type=", type(eng).__name__ if eng else None)
