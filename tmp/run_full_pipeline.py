import json, os, sys
sys.path.insert(0, os.getcwd())
from services.parser_v2.pipeline import parse_document

IN = 'tmp/parser_debug/619405e9-fa71-4d9f-a04c-a127ee64c38f_d00bd6f4-e031-47b4-b037-c3b3eb9ba49e_real_tokens.json'
OUT_FIELDS = 'tmp/parser_debug/extracted_forms.run.json'
OUT_NORM = 'tmp/parser_debug/normalized_fields.run.json'

with open(IN,'r',encoding='utf-8') as f:
    ocr_tokens = json.load(f)

# run parser pipeline
os.makedirs('tmp/parser_debug', exist_ok=True)
doc = parse_document(ocr_tokens, debug_dir='tmp/parser_debug')

with open(OUT_FIELDS,'w',encoding='utf-8') as f:
    json.dump([fld.model_dump() if hasattr(fld,'model_dump') else fld.dict() for fld in doc.fields], f, indent=2, ensure_ascii=False)
with open(OUT_NORM,'w',encoding='utf-8') as f:
    json.dump(doc.normalized_fields, f, indent=2, ensure_ascii=False)

print('WROTE', OUT_FIELDS, OUT_NORM)
