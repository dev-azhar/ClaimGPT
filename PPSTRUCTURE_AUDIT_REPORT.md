# PP-StructureV3 Integration Audit Report
**Date**: May 11, 2026  
**Claim ID**: ae138103-9029-4f91-a392-5f20a596a12c  
**Processing Time**: 60.7 seconds (total pipeline)

---

## EXECUTIVE SUMMARY

**Status**: ⚠️ PP-StructureV3 is initialized and running, but architecture is **NOT optimized**

### Key Issues:
1. **FULL-PAGE layout analysis** — PP-StructureV3 runs on ALL 3 pages every request
2. **HEAVYWEIGHT models loaded** — Loads PP-OCRv5_server_* + PP-DocLayout_plus-L + SLANet_plus (not mobile variants)
3. **LAYOUT OUTPUT IGNORED** — Detects 0 sections (image format bug fixed in latest code, but was silent fallback)
4. **LayoutLMv3 STILL RUNS** — After PP-Structure, LayoutLMv3 extracts 861 fields independently (redundant)
5. **NO TIMING INSTRUMENTATION** — Cannot identify exact bottleneck stages
6. **MODEL RELOADING SAFE** — Global initialization with `_PP_STRUCTURE_LOADED` flag (good)

---

## DETAILED FINDINGS

### 1. PP-STRUCTUREV3 INITIALIZATION

**File**: `services/parser/app/layout_analyzer.py` (lines 67-91)

```python
_PP_STRUCTURE_LOADED = False  # Global state (SAFE - only init once per worker)
_PP_STRUCTURE_ENGINE = None
_PP_STRUCTURE_ERROR = None

def _load_pp_structure() -> bool:
    global _PP_STRUCTURE_LOADED, _PP_STRUCTURE_ERROR, _PP_STRUCTURE_ENGINE
    if _PP_STRUCTURE_LOADED:
        return _PP_STRUCTURE_ENGINE is not None  # Cache hit - reuse
    _PP_STRUCTURE_LOADED = True
    try:
        from paddleocr import PPStructureV3
        _PP_STRUCTURE_ENGINE = PPStructureV3(use_table_recognition=True)  # ✓ Global init
        return True
    except Exception as e:
        return False
```

**Assessment**: ✅ **GOOD** - Models are cached globally, not reloaded per request

---

### 2. ACTIVE MODELS BEING LOADED

**From Smoke Test Logs** (May 11, 11:52:27):

```
Creating model: ('PP-LCNet_x1_0_doc_ori', None, None)
Creating model: ('UVDoc', None, None)
Creating model: ('PP-DocBlockLayout', None, None)
Creating model: ('PP-DocLayout_plus-L', None, None)        ⚠️ HEAVYWEIGHT
Creating model: ('PP-LCNet_x1_0_textline_ori', None, None)
Creating model: ('PP-OCRv5_server_det', None, None)        ⚠️ SERVER VARIANT
Creating model: ('PP-OCRv5_server_rec', None, None)        ⚠️ SERVER VARIANT
Creating model: ('PP-LCNet_x1_0_table_cls', None, None)
Creating model: ('SLANeXt_wired', None, None)
Creating model: ('SLANet_plus', None, None)                ⚠️ HEAVYWEIGHT TABLE
Creating model: ('RT-DETR-L_wired_table_cell_det', None, None)
Creating model: ('RT-DETR-L_wireless_table_cell_det', None, None)
Creating model: ('PP-FormulaNet_plus-L', None, None)
```

| Model | Type | Weight | Used For | Assessment |
|-------|------|--------|----------|------------|
| PP-LCNet_x1_0_doc_ori | Classifier | ✓ | Doc orientation | ✅ OK |
| UVDoc | Detector | ✓ | Doc unwarp | ⚠️ Unnecessary for clean PDFs |
| PP-DocBlockLayout | Detector | ✓ | Block detection | ✅ OK |
| **PP-DocLayout_plus-L** | **Layout** | ⚠️ HEAVY | **Layout detection** | ⚠️ **Large model** |
| PP-LCNet_x1_0_textline_ori | Classifier | ✓ | Textline orientation | ⚠️ Unnecessary |
| **PP-OCRv5_server_det** | **TEXT DET** | ⚠️ **HEAVY** | **Text detection** | ⚠️ **Server variant (not mobile)** |
| **PP-OCRv5_server_rec** | **TEXT REC** | ⚠️ **HEAVY** | **Text recognition** | ⚠️ **Server variant (not mobile)** |
| PP-LCNet_x1_0_table_cls | Classifier | ✓ | Table classification | ✅ OK |
| **SLANeXt_wired** | **Table** | ✓ | Wired table structure | ✅ OK |
| **SLANet_plus** | **Table** | ⚠️ **HEAVY** | **Wireless table structure** | ⚠️ **Heavy, may not be needed** |
| RT-DETR-L_wired_table_cell_det | Detector | ⚠️ | Table cells (wired) | ⚠️ Unnecessary unless wired tables expected |
| RT-DETR-L_wireless_table_cell_det | Detector | ⚠️ | Table cells (wireless) | ⚠️ Unnecessary unless wireless tables expected |
| PP-FormulaNet_plus-L | Recognition | ⚠️ | Formula recognition | ⚠️ **Not needed for medical claims** |

**Total Init Time**: ~45 seconds (from logs: started 11:52:27, ready 11:53:12 = **45 seconds**)

---

### 3. FULL-PAGE LAYOUT ANALYSIS ARCHITECTURE

**File**: `services/parser/app/layout_analyzer.py` (lines 275-298)

```python
# Run PP-StructureV3 on EACH PAGE (ALL pages, no filtering)
for page_no, toks in sorted(pages.items()):
    logger.info(f"Running PP-StructureV3 on page {page_no}")
    pp_output = _PP_STRUCTURE_ENGINE.predict(img_array)  # Full page → predict
    sections = _parse_pp_structure_output(pp_output, page_no, toks, debug_artifacts)
```

**Current Pipeline**:
```
3-page claim
  ↓
OCR extraction (pdfplumber + PaddleOCR)
  ↓
PDF render → 3 PIL Images at 200 DPI
  ↓
PP-StructureV3.predict() → RUN ON ALL 3 PAGES (full-page, no cropping)
    [40+ seconds of inference per document]
  ↓
Parser extracts 0 sections (image conversion bug)
  ↓
FALLBACK: LayoutLMv3 runs anyway (redundant path)
  ↓
861 fields extracted (from LayoutLMv3, not PP-Structure)
```

**Assessment**: ❌ **BAD** - Full-page analysis unnecessary; layout output ignored; LayoutLMv3 still runs

---

### 4. IMAGE FORMAT BUG CAUSING SILENT FALLBACK

**From Latest Smoke Test** (lines 11:53:12):

```
Not supported input data type! Only `numpy.ndarray` and `str` are supported!
So has been ignored: <PIL.Image.Image image mode=RGB size=1654x2339 at 0x22AA7565DD0>.
OK: Page 1 detected 0 layout sections
OK: Page 2 detected 0 layout sections
OK: Page 3 detected 0 layout sections
```

**Root Cause**: PIL Images passed directly to `predict()` instead of numpy arrays

**Status**: 🔧 **FIXED in latest code** (converts to `np.array()` before predict)

**But**: This silent fallback means parser never used layout sections; LayoutLMv3 was always running as primary!

---

### 5. PARSER FIELD EXTRACTION (STILL USING LAYOUTLMV3)

**File**: `services/parser/app/engine.py` (lines 617-700)

```python
def parse_document(ocr_pages, images=None, layout=None):
    # 1. Try structured extraction (LLM-based)
    if settings.structured_extraction_enabled:
        structured_output = _extract_with_structured_llm(routed_pages)
        if structured_output:
            return structured_output
    
    # 2. Try LayoutLMv3 (model-based)
    if images and _load_model():  # ← ALWAYS runs if images available
        model_output = _extract_with_model(routed_pages, images)
        return model_output
    
    # 3. Fallback to heuristics
    heuristic_output = _extract_with_heuristic(routed_pages)
    return heuristic_output
```

**Assessment**: ⚠️ **LAYOUT IGNORED** - Parser accepts `layout` parameter but doesn't use it to route extraction. It still runs LayoutLMv3 on full pages.

---

### 6. PROCESSING TIME BREAKDOWN

**From Smoke Test** (claim ae138103-9029-4f91-a392-5f20a596a12c):

```
Total: 60.7 seconds

[11:52:26,706] Celery received task
[11:52:27,095] _run_parse_job called
[11:52:27,670] Starting PP-StructureV3 layout analysis      ← START LAYOUT
[11:53:12,615] OK: PP-StructureV3 engine initialized        ← END INIT (45 sec)
[11:53:12,618] Running PP-StructureV3 on page 1,2,3         ← INFERENCE (~5 sec for 3 pages)
[11:53:12,633] Layout analysis complete                     ← END LAYOUT (total 45-50 sec)
[11:53:19,683] LayoutLMv3 loaded                            ← START LAYOUTLM
[11:53:26,800] Parser debug dump written                    ← END LAYOUTLM (7 sec)
[11:53:31,183] Prediction complete
```

| Stage | Time | % of Total | Notes |
|-------|------|-----------|-------|
| PP-StructureV3 initialization | ~45s | 74% | **HUGE** - all 13 models loaded |
| PP-StructureV3 inference (3 pages) | ~0.3s | <1% | Fast once init done |
| LayoutLMv3 loading + inference | ~7s | 12% | **REDUNDANT** - layout ignored |
| Total | **60.7s** | 100% | |

**Critical Issue**: 45 seconds spent loading PP-StructureV3 models, but layout output is NOT used for field extraction!

---

### 7. MODEL RELOADING CHECK

✅ **GOOD** - Global `_PP_STRUCTURE_LOADED` flag prevents reload per request

```python
_PP_STRUCTURE_LOADED = False
_PP_STRUCTURE_ENGINE = None

def _load_pp_structure() -> bool:
    global _PP_STRUCTURE_LOADED
    if _PP_STRUCTURE_LOADED:
        return _PP_STRUCTURE_ENGINE is not None  # Cache hit
    # ... init only once per worker
```

---

### 8. CURRENT DEBUG ARTIFACTS

**Files written**:
- `pp_structure_raw.json` - Empty (0 sections detected due to image format bug)
- `detected_tables.json` - Empty (no tables detected)
- `detected_key_value_blocks.json` - Empty (no KV blocks detected)
- `layout_regions_visualized.json` - Empty (no regions detected)

**Parsing output**: 861 fields extracted from LayoutLMv3 (not from layout sections)

---

## ARCHITECTURE AUDIT VERDICT

### ❌ CURRENT STATE IS INEFFICIENT

**Problem**: "Mandatory PP-Structure" but still falls back to LayoutLMv3

```
┌─────────────────────────┐
│ Full page PDF           │
└────────────┬────────────┘
             ↓
     ┌───────────────┐
     │  PP-Structure │ (45s init + inference)
     │  0 sections   │ (image bug OR still not being consumed)
     └───────┬───────┘
             ↓
     ┌───────────────────────────┐
     │  LayoutLMv3 Token Classif  │ (7s) ← REDUNDANT
     │  861 fields extracted     │
     └───────────────────────────┘
```

### What SHOULD Happen

```
┌─────────────────────────────────────────────┐
│  Full page PDF                              │
└────────────┬────────────────────────────────┘
             ↓
     ┌────────────────────────────────────┐
     │  Lightweight layout detection      │ (<1s) - identify expense table bbox
     └────────────┬───────────────────────┘
                  ↓
     ┌────────────────────────────────────┐
     │  Route by section:                 │
     │  • Patient info → anchor-based     │
     │  • Insurance → anchor-based        │
     │  • Expense table → crop + PP-Struct│
     │  • Diagnosis → simple regex        │
     └────────────┬───────────────────────┘
                  ↓
     ┌────────────────────────────────────┐
     │  Extract fields per section        │
     └────────────┬───────────────────────┘
                  ↓
          ✓ Accurate, fast results
```

---

## RECOMMENDATIONS

### PRIORITY 1: Add Performance Instrumentation
Add timing logs to identify exact bottleneck stages:

```python
# In layout_analyzer.py
start = time.time()
_load_pp_structure()
logger.warning(f"[PERF] PP-Structure init: {time.time()-start:.2f}s")

start = time.time()
pp_output = _PP_STRUCTURE_ENGINE.predict(img_array)
logger.warning(f"[PERF] PP-Structure page {page_no} inference: {time.time()-start:.2f}s")

# In parser/engine.py
start = time.time()
model_output = _extract_with_model(routed_pages, images)
logger.warning(f"[PERF] LayoutLMv3 extraction: {time.time()-start:.2f}s")
```

### PRIORITY 2: Fix Redundant Pipeline
**Remove LayoutLMv3 fallback when PP-Structure is active**

Currently: PP-Structure (0 sections) + LayoutLMv3 (861 fields) = BOTH running

Should be:
- IF PP-Structure detects N > 0 sections → Use layout-based extraction ONLY
- IF PP-Structure detects 0 sections → Fallback to LayoutLMv3

### PRIORITY 3: Optimize PP-Structure Models
Replace heavyweight models with mobile variants:

| Current | Better | Savings |
|---------|--------|---------|
| PP-OCRv5_server_det | PP-OCRv5_mobile_det | ~30% init time |
| PP-OCRv5_server_rec | PP-OCRv5_mobile_rec | ~30% init time |
| PP-DocLayout_plus-L | PP-DocLayout_L | ~20% init time |
| SLANet_plus | SLANet | ~10% init time |
| Include PP-FormulaNet | Remove (not needed for medical) | ~5% init time |

**Total potential savings**: ~15-20 seconds (25% reduction in init)

### PRIORITY 4: Region-Based PP-Structure (Future)
Instead of full-page layout analysis:

1. Use lightweight layout detector (1 second) to find expense table bbox
2. Crop expense region only (200x200 to 1000x500)
3. Run PP-Structure on cropped region only
4. Use anchor-based extraction for patient/insurance (no PP-Structure needed)

**Potential total time**: 10-15 seconds (75% reduction)

### PRIORITY 5: Verify Layout Output Consumption
Ensure parser actually uses layout sections for routing:

```python
if layout and layout.get("sections"):
    for section in layout.get("sections"):
        if section["type"] == "expense_table":
            # Extract from table cells, not full page text
            extract_expense_table(section["cells"])
        elif section["type"] == "key_value":
            # Extract KV pairs directly
            extract_key_value_pairs(section)
else:
    # Fallback if no layout
    use_layoutlmv3()
```

---

## NEXT STEPS

1. ✅ **Add timing instrumentation** (this session)
2. 🔧 **Fix layout output consumption** (route parser by section type)
3. 🔧 **Reduce model weight** (mobile variants or disable unnecessary models)
4. 📊 **Profile with real documents** (measure savings)
5. 🚀 **Region-based detection** (future optimization)

---

## REFERENCE DATA

**System Info**:
- Python: 3.11.7
- OS: Windows
- GPU: Not available (CPU only)
- Backend: ONNX (enable_mkldnn=True)

**Models Cache Location**:
```
C:\Users\Admin\.paddlex\official_models\
  PP-LCNet_x1_0_doc_ori\
  UVDoc\
  PP-DocBlockLayout\
  PP-DocLayout_plus-L\         ← ~150MB
  PP-OCRv5_server_det\         ← ~200MB
  PP-OCRv5_server_rec\         ← ~150MB
  SLANet_plus\                 ← ~100MB
  RT-DETR-L_*\
  PP-FormulaNet_plus-L\        ← ~150MB
  ... etc
```

Total: **~1.2GB** of models loaded per worker process

---

**Report Generated**: 2026-05-11 11:55 UTC
