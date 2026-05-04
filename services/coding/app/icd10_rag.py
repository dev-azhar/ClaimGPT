"""
ICD-10 RAG (Retrieval-Augmented Generation) module for ClaimGPT.

Uses sentence-transformer embeddings + FAISS to perform semantic search
over the **complete** ICD-10-CM code set (~74,700 billable codes) loaded
from the ``simple-icd-10-cm`` package, plus CPT codes from
``icd10_codes.py``.

The index is built once (on first import or via ``build_index()``) and
persisted to disk.  Subsequent loads take <1 s even for the full set.

Public API
----------
- ``search_icd10_rag(query, max_results=5)`` — semantic search
- ``search_cpt_rag(query, max_results=5)``   — semantic search for CPT
- ``is_rag_available()``                      — check if index is loaded
- ``build_index(force=False)``                — (re)build the FAISS index
"""

from __future__ import annotations

import functools
import json
import logging
import os
import pathlib
from typing import Any

import numpy as np

logger = logging.getLogger("coding.rag")

# Cache config — tunable via env. Caching is per-process; restart clears it.
_RAG_CACHE_SIZE = int(os.environ.get("CODING_RAG_CACHE_SIZE", "512"))

# ── Paths ──────────────────────────────────────────────────────────
_DATA_DIR = pathlib.Path(__file__).parent / "rag_data"
_ICD10_INDEX_PATH = _DATA_DIR / "icd10_index.faiss"
_ICD10_META_PATH = _DATA_DIR / "icd10_meta.json"
_CPT_INDEX_PATH = _DATA_DIR / "cpt_index.faiss"
_CPT_META_PATH = _DATA_DIR / "cpt_meta.json"

# ── Lazy globals ───────────────────────────────────────────────────
_model = None
_model_load_attempted = False
_icd10_index = None
_icd10_meta: list[dict[str, str]] = []
_cpt_index = None
_cpt_meta: list[dict[str, str]] = []

_EMBEDDING_MODEL = os.environ.get(
    "CODING_EMBEDDING_MODEL", "all-MiniLM-L6-v2"
)
_EMBEDDING_DIM = 384  # for all-MiniLM-L6-v2


# ── ICD-10-CM Chapter mapping ─────────────────────────────────────
# Maps the first character(s) of an ICD-10 code to a clinical category.

_CHAPTER_MAP: list[tuple[str, str, str]] = [
    ("A", "B", "Infectious"),
    ("C", "C", "Neoplasm"),
    ("D", "D", "Blood/Neoplasm"),  # D00-D49 neoplasm, D50-D89 blood
    ("E", "E", "Endocrine"),
    ("F", "F", "Mental"),
    ("G", "G", "Nervous"),
    ("H", "H", "Eye/Ear"),  # H00-H59 eye, H60-H95 ear
    ("I", "I", "Circulatory"),
    ("J", "J", "Respiratory"),
    ("K", "K", "Digestive"),
    ("L", "L", "Skin"),
    ("M", "M", "Musculoskeletal"),
    ("N", "N", "Genitourinary"),
    ("O", "O", "Pregnancy"),
    ("P", "P", "Perinatal"),
    ("Q", "Q", "Congenital"),
    ("R", "R", "Symptoms"),
    ("S", "T", "Injury"),
    ("U", "U", "Special"),
    ("V", "Y", "External"),
    ("Z", "Z", "Factors"),
]


def _code_to_category(code: str) -> str:
    """Map an ICD-10 code to its clinical chapter/category."""
    if not code:
        return "Unknown"
    ch = code[0].upper()
    for start, end, cat in _CHAPTER_MAP:
        if start <= ch <= end:
            return cat
    return "Unknown"


# ── Clinical synonyms for high-frequency codes ────────────────────
# These boost retrieval for common clinical terms that don't appear in
# the official ICD-10 descriptions.  Only the most important ~700 codes
# need explicit synonyms — the embedding model handles the rest.

_SYNONYM_OVERLAY: dict[str, list[str]] = {
    # Infectious
    "A00.9": ["cholera"],
    "A01.0": ["typhoid", "enteric fever"],
    "A01.00": ["typhoid", "enteric fever"],
    "A02.0": ["salmonella", "food poisoning"],
    "A09": ["gastroenteritis infectious", "stomach flu"],
    "A15.0": ["pulmonary tb", "lung tb"],
    "A16.9": ["tb", "tuberculosis"],
    "A37.90": ["pertussis", "whooping cough"],
    "A41.9": ["sepsis", "septicemia", "blood poisoning"],
    "A69.20": ["lyme disease"],
    "A90": ["dengue", "dengue fever", "break bone fever"],
    "A91": ["dengue hemorrhagic", "severe dengue"],
    "A92.0": ["chikungunya"],
    "A97.0": ["dengue ns1"],
    # Infectious - viral
    "B00.9": ["herpes"],
    "B01.9": ["chickenpox", "varicella"],
    "B02.9": ["shingles", "herpes zoster"],
    "B05.9": ["measles"],
    "B06.9": ["rubella", "german measles"],
    "B15.9": ["hepatitis a"],
    "B16.9": ["hepatitis b acute"],
    "B17.10": ["hepatitis c acute"],
    "B18.1": ["chronic hepatitis b"],
    "B18.2": ["chronic hepatitis c"],
    "B20": ["hiv", "aids"],
    "B26.9": ["mumps"],
    "B34.9": ["viral infection"],
    "B37.3": ["vaginal yeast infection", "vaginal candidiasis"],
    "B50.9": ["falciparum malaria", "malaria"],
    "B54": ["malaria unspecified"],
    "B86": ["scabies"],
    "B97.29": ["coronavirus", "covid"],
    # Neoplasm
    "C16.9": ["stomach cancer", "gastric cancer"],
    "C18.9": ["colon cancer", "colorectal cancer"],
    "C22.0": ["hepatocellular carcinoma", "liver cancer", "hcc"],
    "C25.9": ["pancreatic cancer"],
    "C34.90": ["lung cancer"],
    "C50.919": ["breast cancer"],
    "C53.9": ["cervical cancer"],
    "C56.9": ["ovarian cancer"],
    "C61": ["prostate cancer"],
    "C71.9": ["brain cancer", "brain tumor"],
    "C73": ["thyroid cancer"],
    "C83.30": ["dlbcl", "lymphoma"],
    "C85.90": ["non hodgkin lymphoma", "nhl"],
    "C90.00": ["multiple myeloma"],
    "C91.00": ["all", "acute lymphoblastic leukemia"],
    "C92.00": ["aml", "acute myeloid leukemia"],
    "D25.9": ["uterine fibroid", "fibroid"],
    # Blood
    "D50.9": ["iron deficiency anemia"],
    "D56.1": ["thalassemia", "beta thalassemia"],
    "D57.1": ["sickle cell", "sickle cell anemia"],
    "D64.9": ["anemia"],
    "D65": ["dic"],
    "D69.3": ["itp"],
    "D69.6": ["thrombocytopenia", "low platelets"],
    "D86.9": ["sarcoidosis"],
    # Endocrine
    "E03.9": ["hypothyroidism", "underactive thyroid"],
    "E05.90": ["hyperthyroidism", "thyrotoxicosis"],
    "E06.3": ["hashimoto thyroiditis"],
    "E10.9": ["type 1 diabetes", "t1dm", "iddm"],
    "E10.10": ["dka", "diabetic ketoacidosis"],
    "E11.9": ["type 2 diabetes", "t2dm", "niddm", "diabetes"],
    "E11.65": ["hyperglycemia diabetes"],
    "E11.40": ["diabetic neuropathy"],
    "E11.21": ["diabetic nephropathy", "diabetic kidney"],
    "E11.311": ["diabetic retinopathy"],
    "E11.621": ["diabetic foot ulcer"],
    "E16.2": ["hypoglycemia", "low blood sugar"],
    "E24.9": ["cushing syndrome"],
    "E27.1": ["addison disease"],
    "E28.2": ["pcos", "polycystic ovary"],
    "E55.9": ["vitamin d deficiency"],
    "E66.9": ["obesity"],
    "E78.00": ["high cholesterol"],
    "E78.5": ["dyslipidemia"],
    "E84.9": ["cystic fibrosis", "cf"],
    "E86.0": ["dehydration"],
    "E87.1": ["hyponatremia"],
    "E87.5": ["hyperkalemia"],
    "E87.6": ["hypokalemia"],
    # Mental
    "F03.90": ["dementia"],
    "F10.20": ["alcoholism", "alcohol dependence"],
    "F20.9": ["schizophrenia"],
    "F31.9": ["bipolar disorder"],
    "F32.9": ["depression"],
    "F41.0": ["panic disorder", "panic attack"],
    "F41.1": ["gad", "anxiety"],
    "F42.9": ["ocd"],
    "F43.10": ["ptsd"],
    "F50.00": ["anorexia nervosa"],
    "F51.01": ["insomnia"],
    "F84.0": ["autism"],
    "F90.9": ["adhd"],
    # Nervous
    "G12.21": ["als", "motor neuron disease"],
    "G20": ["parkinson", "parkinsons"],
    "G30.9": ["alzheimer", "alzheimers"],
    "G35": ["multiple sclerosis", "ms"],
    "G40.909": ["epilepsy", "seizure disorder"],
    "G43.909": ["migraine"],
    "G45.9": ["tia"],
    "G47.33": ["sleep apnea", "osa"],
    "G51.0": ["bell palsy", "facial palsy"],
    "G56.00": ["carpal tunnel"],
    "G61.0": ["guillain barre", "gbs"],
    "G62.9": ["neuropathy", "polyneuropathy"],
    "G70.00": ["myasthenia gravis"],
    "G80.9": ["cerebral palsy"],
    "G91.9": ["hydrocephalus"],
    # Eye / Ear
    "H10.9": ["conjunctivitis", "pink eye"],
    "H25.9": ["cataract"],
    "H35.30": ["macular degeneration", "amd"],
    "H40.10X0": ["glaucoma"],
    "H66.90": ["otitis media", "ear infection"],
    "H81.10": ["bppv", "positional vertigo"],
    "H91.90": ["hearing loss"],
    "H93.19": ["tinnitus"],
    # Circulatory
    "I10": ["hypertension", "high blood pressure", "htn"],
    "I20.0": ["unstable angina"],
    "I20.9": ["angina"],
    "I21.3": ["stemi", "heart attack"],
    "I21.4": ["nstemi"],
    "I21.9": ["ami", "heart attack", "myocardial infarction"],
    "I25.10": ["coronary artery disease", "cad"],
    "I26.99": ["pulmonary embolism", "pe"],
    "I27.0": ["pulmonary hypertension"],
    "I34.0": ["mitral regurgitation"],
    "I35.0": ["aortic stenosis"],
    "I42.0": ["dilated cardiomyopathy", "dcm"],
    "I42.1": ["hocm", "hypertrophic cardiomyopathy"],
    "I48.91": ["atrial fibrillation", "afib"],
    "I50.9": ["heart failure", "chf"],
    "I60.9": ["subarachnoid hemorrhage", "sah"],
    "I63.9": ["stroke", "cerebral infarction", "cva"],
    "I71.4": ["aortic aneurysm", "aaa"],
    "I73.9": ["pvd", "peripheral arterial disease"],
    "I82.409": ["dvt", "deep vein thrombosis"],
    "I83.90": ["varicose veins"],
    # Respiratory
    "J00": ["common cold"],
    "J02.9": ["pharyngitis", "sore throat"],
    "J06.9": ["uri", "upper respiratory infection"],
    "J11.1": ["flu", "influenza"],
    "J18.9": ["pneumonia"],
    "J20.9": ["bronchitis"],
    "J30.9": ["allergic rhinitis", "hay fever"],
    "J44.9": ["copd"],
    "J44.1": ["copd exacerbation"],
    "J45.909": ["asthma"],
    "J47.9": ["bronchiectasis"],
    "J80": ["ards"],
    "J84.10": ["pulmonary fibrosis", "ipf"],
    "J90": ["pleural effusion"],
    "J93.9": ["pneumothorax"],
    "J96.00": ["acute respiratory failure"],
    # Digestive
    "K21.0": ["gerd", "acid reflux"],
    "K25.9": ["gastric ulcer", "stomach ulcer"],
    "K29.70": ["gastritis"],
    "K35.80": ["appendicitis"],
    "K40.90": ["inguinal hernia"],
    "K44.9": ["hiatal hernia"],
    "K50.90": ["crohn disease", "crohns"],
    "K51.90": ["ulcerative colitis"],
    "K56.60": ["intestinal obstruction", "bowel obstruction"],
    "K57.32": ["diverticulitis"],
    "K58.9": ["ibs", "irritable bowel"],
    "K64.9": ["hemorrhoids", "piles"],
    "K70.30": ["alcoholic cirrhosis"],
    "K74.60": ["cirrhosis"],
    "K76.0": ["fatty liver", "nafld"],
    "K80.20": ["gallstones"],
    "K81.0": ["cholecystitis"],
    "K85.90": ["acute pancreatitis"],
    "K92.2": ["gi bleed"],
    # Skin
    "L02.91": ["skin abscess"],
    "L03.90": ["cellulitis"],
    "L20.9": ["eczema", "atopic dermatitis"],
    "L40.0": ["psoriasis"],
    "L50.9": ["urticaria", "hives"],
    "L70.0": ["acne"],
    "L80": ["vitiligo"],
    # Musculoskeletal
    "M05.79": ["rheumatoid arthritis"],
    "M10.9": ["gout"],
    "M17.9": ["knee arthritis"],
    "M19.90": ["osteoarthritis"],
    "M32.9": ["sle", "lupus"],
    "M45.9": ["ankylosing spondylitis"],
    "M48.06": ["lumbar spinal stenosis"],
    "M51.16": ["lumbar disc herniation"],
    "M54.5": ["low back pain", "lbp"],
    "M54.16": ["sciatica", "lumbar radiculopathy"],
    "M75.10": ["rotator cuff tear"],
    "M79.7": ["fibromyalgia"],
    "M81.0": ["osteoporosis"],
    # Genitourinary
    "N04.9": ["nephrotic syndrome"],
    "N10": ["pyelonephritis"],
    "N17.9": ["acute kidney injury", "aki"],
    "N18.6": ["esrd", "end stage renal"],
    "N18.9": ["ckd", "chronic kidney disease"],
    "N20.0": ["kidney stone", "renal calculus"],
    "N39.0": ["uti", "urinary tract infection"],
    "N40.1": ["bph"],
    "N80.0": ["endometriosis"],
    "N83.20": ["ovarian cyst"],
    # Pregnancy
    "O00.90": ["ectopic pregnancy"],
    "O14.90": ["preeclampsia"],
    "O24.414": ["gestational diabetes"],
    "O72.1": ["postpartum hemorrhage"],
    "O80": ["normal delivery"],
    # Congenital
    "Q21.0": ["vsd", "ventricular septal defect"],
    "Q21.1": ["asd", "atrial septal defect"],
    "Q25.0": ["pda", "patent ductus arteriosus"],
    "Q61.3": ["polycystic kidney", "pkd"],
    "Q90.9": ["down syndrome", "trisomy 21"],
    # Symptoms
    "R05.9": ["cough"],
    "R06.02": ["shortness of breath"],
    "R07.9": ["chest pain"],
    "R10.9": ["abdominal pain"],
    "R11.2": ["vomiting"],
    "R19.7": ["diarrhea"],
    "R50.9": ["fever"],
    "R51.9": ["headache"],
    "R55": ["syncope", "fainting"],
    "R56.9": ["convulsion", "seizure"],
    # Injury
    "S06.0X0A": ["concussion"],
    "S72.001A": ["hip fracture", "femoral neck fracture"],
    "S82.201A": ["tibia fracture"],
    "S83.511A": ["acl tear"],
    "S93.401A": ["ankle sprain"],
    "T78.2XXA": ["anaphylaxis"],
    "T78.40XA": ["allergic reaction"],
    # Factors
    "Z23": ["vaccination"],
    "Z51.11": ["chemotherapy"],
    "Z51.0": ["radiation therapy"],
    "Z99.2": ["dialysis dependent"],
}


# ── Embedding model ───────────────────────────────────────────────

def _load_model():
    """Lazy-load the sentence-transformers embedding model."""
    global _model, _model_load_attempted
    if _model_load_attempted:
        return _model
    _model_load_attempted = True
    try:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(_EMBEDDING_MODEL)
        logger.info("Loaded embedding model '%s'", _EMBEDDING_MODEL)
    except Exception:
        logger.warning("Failed to load embedding model '%s'", _EMBEDDING_MODEL, exc_info=True)
    return _model


# ── Index building ─────────────────────────────────────────────────

def _build_texts_for_code(code: str, desc: str, category: str, synonyms: list[str]) -> str:
    """Create the text to embed for a single ICD-10 code."""
    parts = [desc]
    if synonyms:
        parts.append(" ".join(synonyms))
    parts.append(category)
    return " | ".join(parts)


def build_index(force: bool = False) -> bool:
    """
    Build the FAISS ICD-10 + CPT index.

    Loads **all** ~74,700 billable ICD-10-CM codes from
    ``simple-icd-10-cm``, merges synonym overlays from
    ``_SYNONYM_OVERLAY`` and ``icd10_codes.py``, embeds them with
    sentence-transformers, and saves to disk.

    Returns True on success.
    """
    import faiss

    model = _load_model()
    if model is None:
        logger.error("Cannot build index — embedding model unavailable")
        return False

    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Skip if already exists and not forced
    if not force and _ICD10_INDEX_PATH.exists() and _ICD10_META_PATH.exists():
        logger.info("FAISS index already exists at %s — use force=True to rebuild", _DATA_DIR)
        return True

    # ── Load ALL billable ICD-10-CM codes ──
    try:
        import simple_icd_10_cm as cm
    except ImportError:
        logger.error("simple-icd-10-cm not installed — run: pip install simple-icd-10-cm")
        return False

    all_codes = cm.get_all_codes()
    leaf_codes = [c for c in all_codes if cm.is_leaf(c)]
    logger.info("Loaded %d billable ICD-10-CM codes from simple-icd-10-cm", len(leaf_codes))

    # ── Collect synonyms from icd10_codes.py ──
    from .icd10_codes import ICD10_CM, CLINICAL_SYNONYMS

    existing_synonyms: dict[str, list[str]] = {}
    for syn_term, syn_codes in CLINICAL_SYNONYMS.items():
        for code in syn_codes:
            existing_synonyms.setdefault(code, []).append(syn_term)

    # ── Build ICD-10 entries ──
    icd10_entries: list[dict[str, Any]] = []
    for code in leaf_codes:
        desc = cm.get_description(code)
        cat = _code_to_category(code)

        # Merge synonyms: overlay > icd10_codes.py synonyms
        syns: list[str] = []
        if code in _SYNONYM_OVERLAY:
            syns.extend(_SYNONYM_OVERLAY[code])
        if code in existing_synonyms:
            seen = set(s.lower() for s in syns)
            for s in existing_synonyms[code]:
                if s.lower() not in seen:
                    syns.append(s)

        icd10_entries.append({
            "code": code,
            "description": desc,
            "category": cat,
            "synonyms": syns,
        })

    # Also add any codes from icd10_codes.py that are NOT in the leaf set
    # (e.g. 3-char parent codes that are used as-is in Indian claims)
    leaf_set = set(leaf_codes)
    for code, (_, desc, cat) in ICD10_CM.items():
        if code not in leaf_set:
            syns = existing_synonyms.get(code, [])
            if code in _SYNONYM_OVERLAY:
                overlay = _SYNONYM_OVERLAY[code]
                seen = set(s.lower() for s in syns)
                for s in overlay:
                    if s.lower() not in seen:
                        syns.append(s)
            icd10_entries.append({
                "code": code,
                "description": desc,
                "category": cat,
                "synonyms": syns,
            })

    # ── Build embedding texts ──
    icd10_texts = [
        _build_texts_for_code(e["code"], e["description"], e["category"], e["synonyms"])
        for e in icd10_entries
    ]

    # ── Encode in batches (74k+ codes) ──
    logger.info("Embedding %d ICD-10 codes (this may take a few minutes)...", len(icd10_texts))
    icd10_vectors = model.encode(
        icd10_texts,
        show_progress_bar=True,
        normalize_embeddings=True,
        batch_size=512,
    )
    icd10_vectors = np.array(icd10_vectors, dtype=np.float32)

    icd10_index = faiss.IndexFlatIP(icd10_vectors.shape[1])
    icd10_index.add(icd10_vectors)

    faiss.write_index(icd10_index, str(_ICD10_INDEX_PATH))
    with open(_ICD10_META_PATH, "w") as f:
        json.dump(icd10_entries, f)

    logger.info(
        "ICD-10 FAISS index saved: %d vectors, dim=%d, file=%s",
        icd10_index.ntotal, icd10_vectors.shape[1], _ICD10_INDEX_PATH,
    )

    # ── Build CPT index (unchanged — from icd10_codes.py) ──
    from .icd10_codes import CPT_CODES, CPT_SYNONYMS

    cpt_entries: list[dict[str, Any]] = []
    for code, (_, desc, cat) in CPT_CODES.items():
        syns = []
        for syn, codes in CPT_SYNONYMS.items():
            if code in codes:
                syns.append(syn)
        cpt_entries.append({"code": code, "description": desc, "category": cat, "synonyms": syns})

    cpt_texts = [
        _build_texts_for_code(e["code"], e["description"], e["category"], e["synonyms"])
        for e in cpt_entries
    ]

    logger.info("Embedding %d CPT codes...", len(cpt_texts))
    cpt_vectors = model.encode(cpt_texts, show_progress_bar=False, normalize_embeddings=True)
    cpt_vectors = np.array(cpt_vectors, dtype=np.float32)

    cpt_index = faiss.IndexFlatIP(cpt_vectors.shape[1])
    cpt_index.add(cpt_vectors)

    faiss.write_index(cpt_index, str(_CPT_INDEX_PATH))
    with open(_CPT_META_PATH, "w") as f:
        json.dump(cpt_entries, f)

    logger.info("CPT FAISS index saved: %d vectors, dim=%d", cpt_index.ntotal, cpt_vectors.shape[1])

    # Load into globals
    _load_indices()
    return True


# ── Index loading ──────────────────────────────────────────────────

def _load_indices():
    """Load pre-built FAISS indices from disk into memory."""
    global _icd10_index, _icd10_meta, _cpt_index, _cpt_meta

    try:
        import faiss
    except ImportError:
        logger.warning("faiss-cpu not installed — RAG search unavailable")
        return

    if _ICD10_INDEX_PATH.exists() and _ICD10_META_PATH.exists():
        _icd10_index = faiss.read_index(str(_ICD10_INDEX_PATH))
        with open(_ICD10_META_PATH) as f:
            _icd10_meta = json.load(f)
        logger.info("Loaded ICD-10 FAISS index: %d codes", _icd10_index.ntotal)

    if _CPT_INDEX_PATH.exists() and _CPT_META_PATH.exists():
        _cpt_index = faiss.read_index(str(_CPT_INDEX_PATH))
        with open(_CPT_META_PATH) as f:
            _cpt_meta = json.load(f)
        logger.info("Loaded CPT FAISS index: %d codes", _cpt_index.ntotal)

    # Indices were rebuilt or freshly loaded — drop any stale cached
    # results so subsequent searches use the current index.
    try:
        _search_icd10_rag_cached.cache_clear()
        _search_cpt_rag_cached.cache_clear()
    except NameError:
        # Cached helpers defined later in module — first load is safe.
        pass


# ── Public search API ──────────────────────────────────────────────

def is_rag_available() -> bool:
    """Check whether the RAG index is loaded and ready."""
    if _icd10_index is None:
        _load_indices()
    return _icd10_index is not None


def search_icd10_rag(
    query: str,
    max_results: int = 5,
    min_score: float = 0.25,
) -> list[tuple[str, str, str, float]]:
    """
    Semantic search for ICD-10 codes.

    Returns list of (code, description, category, score) tuples,
    sorted by descending similarity score.

    Results are cached per-process via an LRU keyed on the normalized
    query + parameters (size configurable via CODING_RAG_CACHE_SIZE).
    Use ``clear_search_cache()`` to invalidate (e.g. after rebuilding
    the index).
    """
    q = (query or "").strip().lower()
    if not q:
        return []
    return list(_search_icd10_rag_cached(q, max_results, min_score))


def search_cpt_rag(
    query: str,
    max_results: int = 5,
    min_score: float = 0.25,
) -> list[tuple[str, str, str, float]]:
    """
    Semantic search for CPT codes.

    Returns list of (code, description, category, score) tuples.
    Results are cached per-process; see ``search_icd10_rag``.
    """
    q = (query or "").strip().lower()
    if not q:
        return []
    return list(_search_cpt_rag_cached(q, max_results, min_score))


def clear_search_cache() -> None:
    """Invalidate the LRU caches (call after rebuilding indices)."""
    _search_icd10_rag_cached.cache_clear()
    _search_cpt_rag_cached.cache_clear()


def get_cache_stats() -> dict[str, dict[str, int]]:
    """Return LRU cache statistics for monitoring."""
    icd_info = _search_icd10_rag_cached.cache_info()
    cpt_info = _search_cpt_rag_cached.cache_info()
    return {
        "icd10": {
            "hits": icd_info.hits,
            "misses": icd_info.misses,
            "current_size": icd_info.currsize,
            "max_size": icd_info.maxsize or 0,
        },
        "cpt": {
            "hits": cpt_info.hits,
            "misses": cpt_info.misses,
            "current_size": cpt_info.currsize,
            "max_size": cpt_info.maxsize or 0,
        },
    }


@functools.lru_cache(maxsize=_RAG_CACHE_SIZE)
def _search_icd10_rag_cached(
    query: str,
    max_results: int,
    min_score: float,
) -> tuple[tuple[str, str, str, float], ...]:
    """LRU-cached inner search. Returns tuple (immutable) for hashability."""
    if not is_rag_available():
        return ()
    assert _icd10_index is not None  # narrow for type checker

    model = _load_model()
    if model is None:
        return ()

    query_vec = model.encode([query], normalize_embeddings=True)
    query_vec = np.array(query_vec, dtype=np.float32)

    scores, indices = _icd10_index.search(query_vec, min(max_results * 2, _icd10_index.ntotal))

    results: list[tuple[str, str, str, float]] = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0 or score < min_score:
            continue
        entry = _icd10_meta[idx]
        results.append((entry["code"], entry["description"], entry["category"], float(score)))
        if len(results) >= max_results:
            break

    return tuple(results)


@functools.lru_cache(maxsize=_RAG_CACHE_SIZE)
def _search_cpt_rag_cached(
    query: str,
    max_results: int,
    min_score: float,
) -> tuple[tuple[str, str, str, float], ...]:
    """LRU-cached inner CPT search."""
    if _cpt_index is None:
        _load_indices()
    if _cpt_index is None:
        return ()

    model = _load_model()
    if model is None:
        return ()

    query_vec = model.encode([query], normalize_embeddings=True)
    query_vec = np.array(query_vec, dtype=np.float32)

    scores, indices = _cpt_index.search(query_vec, min(max_results * 2, _cpt_index.ntotal))

    results: list[tuple[str, str, str, float]] = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0 or score < min_score:
            continue
        entry = _cpt_meta[idx]
        results.append((entry["code"], entry["description"], entry["category"], float(score)))
        if len(results) >= max_results:
            break

    return tuple(results)
