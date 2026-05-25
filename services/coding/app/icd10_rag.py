"""
ICD-10 RAG (Retrieval-Augmented Generation) module for ClaimGPT.

Uses sentence-transformer embeddings + FAISS to perform semantic search
over ICD-10 code passages extracted from the bundled ICD-10 PDF in
``rag_data/input/icd-10-medical-diagnosis-codes.pdf``. CPT codes still
come from ``icd10_codes.py``.

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
import csv
import logging
import os
os.environ['TOKENIZERS_PARALLELISM'] = 'false'
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['VECLIB_MAXIMUM_THREADS'] = '1'
os.environ['NUMEXPR_NUM_THREADS'] = '1'
import pathlib
import pickle
import re
import time
from datetime import datetime, timezone
from typing import Any

import numpy as np
from math import sqrt

from .build_icd10_rag import INPUT_PDF, extract_chunks_from_pdf

try:
    from services.chat.app.llm import scrub_phi  # type: ignore
except Exception:
    def scrub_phi(x: str) -> str:
        return x

logger = logging.getLogger("coding.rag")

# Cache config — tunable via env. Caching is per-process; restart clears it.
_RAG_CACHE_SIZE = int(os.environ.get("CODING_RAG_CACHE_SIZE", "512"))

# ── Paths ──────────────────────────────────────────────────────────
_DATA_DIR = pathlib.Path(__file__).parent / "rag_data"
_ICD10_INDEX_PATH = _DATA_DIR / "icd10_index.faiss"
_ICD10_META_PATH = _DATA_DIR / "icd10_meta.json"
_ICD10_BM25_PATH = _DATA_DIR / "icd10_bm25.pkl"
_CPT_INDEX_PATH = _DATA_DIR / "cpt_index.faiss"
_CPT_META_PATH = _DATA_DIR / "cpt_meta.json"
_CPT_BM25_PATH = _DATA_DIR / "cpt_bm25.pkl"

_INDEX_SOURCE = "icd10_input_v1"
_CSV_INPUT_PATH = _DATA_DIR / "input" / "icd10.csv"
_PDF_INDEX_SOURCE = "icd10_pdf_v1"
_CSV_INDEX_SOURCE = "icd10_csv_v1"

# ── Lazy globals ───────────────────────────────────────────────────
_model = None
_model_load_attempted = False
_icd10_index = None
_icd10_meta: list[dict[str, str]] = []
_icd10_bm25 = None  # type: ignore[var-annotated]
_cpt_index = None
_cpt_meta: list[dict[str, str]] = []
_cpt_bm25 = None  # type: ignore[var-annotated]

# Local cached clinical embedding model (SentenceTransformer instance)
_clinical_embed_model = None

_EMBEDDING_MODEL = os.environ.get(
    # pritamdeka/S-PubMedBert-MS-MARCO: PubMedBERT fine-tuned for medical
    # semantic similarity. Understands clinical abbreviations (FTND, LSCS,
    # SVD) and maps them correctly to ICD-10 descriptions without any
    # hardcoded synonym tables.  Dim=768.  Override via CODING_EMBEDDING_MODEL.
    "CODING_EMBEDDING_MODEL", "pritamdeka/S-PubMedBert-MS-MARCO"
)
_EMBEDDING_DIM = int(os.environ.get("CODING_EMBEDDING_DIM", "768"))  # 768 for BERT-base models

# ── Hybrid retrieval config ────────────────────────────────────────
# RRF (Reciprocal Rank Fusion) constant — k=60 is the value from the
# original Cormack et al. paper and works well across regimes.
_RRF_K = int(os.environ.get("CODING_RRF_K", "60"))
# Reranker candidate pool default (can be overridden via env var)
_RERANK_POOL_DEFAULT = int(os.environ.get("CODING_RERANK_POOL", "200"))
# ── Reranker config ───────────────────────────────────────────────
# Local embedding reranker: opt-in (enabled by default).
_ENABLE_LOCAL_CLINICAL_RERANK = os.environ.get("CODING_ENABLE_LOCAL_RERANK", "1").strip().lower() in {"1", "true", "yes", "on"}

# Cross-encoder model for reranking.  A cross-encoder sees the query AND
# the candidate description together in one forward pass and outputs a direct
# relevance score — much more accurate than cosine similarity between
# independently encoded bi-encoder vectors (S-PubMedBert).
# ms-marco-MiniLM-L-6-v2 is fast (~50ms/batch on CPU) and accurate.
# Override via CODING_CROSSENCODER_MODEL env var.
_CROSSENCODER_MODEL = os.environ.get(
    "CODING_CROSSENCODER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"
)
_crossencoder_model = None  # lazy-loaded on first rerank call
_crossencoder_load_attempted = False
# Allowed search modes for the public API.
_VALID_MODES = {"dense", "bm25", "hybrid"}
# Default mode — hybrid catches both semantic-similar and exact-token
# matches (e.g. drug names, abbreviations) the dense model misses.
_DEFAULT_MODE = os.environ.get("CODING_SEARCH_MODE", "hybrid")


# ── Tokenizer for BM25 ────────────────────────────────────────────
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Lowercase + alphanum tokenization for BM25 indexing/queries.

    Only single-character tokens are excluded (noise from OCR).
    Clinical tokens like "in", "with", "without" are intentionally
    kept so BM25 can match ICD descriptions such as
    "diabetes mellitus in pregnancy" or "fracture without displacement".
    The local S-PubMedBert reranker handles final disambiguation.
    """
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if len(t) > 1]


# ── ICD-10-CM Chapter mapping ─────────────────────────────────────
# Maps the first character(s) of an ICD-10 code to a clinical category.

_CHAPTER_MAP: list[tuple[str, str, str]] = [
    ("A", "B", "Infectious"),
    ("C", "C", "Neoplasm"),
    ("D", "D", "Blood"),
    ("E", "E", "Endocrine"),
    ("F", "F", "Mental"),
    ("G", "G", "Nervous"),
    ("H", "H", "Sensory"),
    ("I", "I", "Circulatory"),
    ("J", "J", "Respiratory"),
    ("K", "K", "Digestive"),
    ("L", "L", "Skin"),
    ("M", "M", "Musculoskeletal"),
    ("N", "N", "Genitourinary"),
    # O-codes: a small set of obstetric keywords helps the embedding model
    # connect short descriptions like "Single spontaneous delivery" (O80)
    # to clinical queries. Kept brief to avoid cross-contaminating E/N/P codes.
    ("O", "O", "obstetric pregnancy delivery"),
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

def _get_device() -> str:
    """Detect the best available PyTorch device (CUDA, DirectML, etc.), defaulting to CPU."""
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        # Check for DirectML (Intel/AMD/Nvidia integrated/discrete on Windows)
        try:
            import torch_directml
            if torch_directml.is_available():
                return "dml"
        except ImportError:
            pass
        # Check for Apple Silicon MPS
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def _load_model():
    """Lazy-load the sentence-transformers embedding model."""
    global _model, _model_load_attempted
    if _model_load_attempted:
        return _model
    _model_load_attempted = True
    try:
        try:
            import torch
            import os
            torch.set_num_threads(os.cpu_count() or 4)
        except Exception:
            pass
        _emit_progress(f"Loading embedding model: {_EMBEDDING_MODEL}")
        from sentence_transformers import SentenceTransformer
        device = _get_device()
        _model = SentenceTransformer(_EMBEDDING_MODEL, device=device)
        _emit_progress(f"Loaded embedding model: {_EMBEDDING_MODEL} on device: {device}")
    except Exception:
        logger.warning("Failed to load embedding model '%s'", _EMBEDDING_MODEL, exc_info=True)
    return _model


# ── Index building ─────────────────────────────────────────────────

def _build_texts_for_code(code: str, desc: str, category: str, synonyms: list[str]) -> str:
    """Create the text to embed for a single ICD-10 code.

    The embedded text combines:
      - The ICD-10 description (primary signal)
      - The chapter/category label (expanded to full clinical phrase)
      - Any synonyms passed in

    For very short descriptions (<=4 words, e.g. O80 "Single spontaneous
    delivery"), the category phrase provides the bulk of the semantic
    coverage that the embedding model needs to match clinical queries.
    """
    parts = [desc, category]
    if synonyms:
        parts.append(" ".join(synonyms))
    return " | ".join(parts)


def _emit_progress(message: str) -> None:
    print(message, flush=True)
    logger.warning(message)


def _meta_is_pdf_index() -> bool:
    if not _ICD10_META_PATH.exists():
        return False
    try:
        with open(_ICD10_META_PATH, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        return False
    if not isinstance(meta, list) or not meta:
        return False
    sample = meta[: min(5, len(meta))]
    # Consider any metadata built by our ICD-10 indexer valid (pdf or csv)
    return all(isinstance(entry, dict) and isinstance(entry.get("source"), str) and entry.get("source").startswith("icd10_") for entry in sample)


def _extract_icd10_csv_entries(csv_path: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not os.path.exists(csv_path):
        return entries
    with open(csv_path, "r", encoding="utf-8") as f:
        try:
            reader = csv.DictReader(f)
        except Exception:
            return entries
        for row in reader:
            code = (row.get("icd10_code") or row.get("code") or row.get("ICD10_CODE") or "").strip()
            if not code:
                continue
            desc = (row.get("code_description") or row.get("description") or row.get("code_description") or "").strip()
            if not desc:
                desc = code
            entries.append(
                {
                    "code": code,
                    "description": desc,
                    "category": _code_to_category(code),
                    "synonyms": [],
                    "source": _CSV_INDEX_SOURCE,
                    "text": desc,
                }
            )
    return entries


def _extract_icd10_pdf_entries(pdf_path: str) -> list[dict[str, Any]]:
    chunks = extract_chunks_from_pdf(pdf_path)
    code_re = re.compile(r"\b([A-TV-Z][0-9]{2}(?:\.[0-9A-Za-z]+)?)\b")
    entries_by_code: dict[str, dict[str, Any]] = {}

    for chunk in chunks:
        text = re.sub(r"\s+", " ", str(chunk.get("text") or "")).strip()
        if not text:
            continue
        matches = list(code_re.finditer(text))
        if not matches:
            continue

        for idx, match in enumerate(matches):
            code = match.group(1).upper()
            next_start = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            description = text[match.end():next_start].strip()
            description = re.sub(r"^[\s\-:|.]+", "", description).strip()
            description = re.sub(r"\s{2,}.*$", "", description).strip()
            if not description:
                description = code

            candidate = {
                "code": code,
                "description": description,
                "category": _code_to_category(code),
                "synonyms": [],
                "source": _INDEX_SOURCE,
                "page": chunk.get("page"),
                "text": text,
            }
            current = entries_by_code.get(code)
            if current is None or len(description) > len(str(current.get("description") or "")):
                entries_by_code[code] = candidate

    return list(entries_by_code.values())


def _encode_texts_with_progress(model, texts: list[str], label: str, batch_size: int = 256) -> np.ndarray:
    vectors: list[np.ndarray] = []
    total = len(texts)
    if total == 0:
        return np.empty((0, _EMBEDDING_DIM), dtype=np.float32)

    start = time.time()
    for batch_start in range(0, total, batch_size):
        batch_end = min(batch_start + batch_size, total)
        _emit_progress(f"Embedding {label}: {batch_end}/{total}")
        batch_vectors = model.encode(
            texts[batch_start:batch_end],
            show_progress_bar=False,
            normalize_embeddings=True,
            batch_size=batch_size,
        )
        vectors.append(np.array(batch_vectors, dtype=np.float32))

    result = np.vstack(vectors)
    _emit_progress(f"Finished embedding {label} in {time.time() - start:.1f}s")
    return result


def build_index(force: bool = False, load_after: bool = True) -> bool:
    """Build the FAISS ICD-10 + CPT index from the bundled ICD-10 PDF."""
    import faiss

    model = _load_model()
    if model is None:
        logger.error("Cannot build index — embedding model unavailable")
        return False

    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _emit_progress("Starting ICD-10 + CPT index build")

    # Skip if already exists and not forced, but only if the on-disk
    # ICD-10 metadata was already built from the PDF source.
    if not force and _ICD10_INDEX_PATH.exists() and _ICD10_META_PATH.exists() and _meta_is_pdf_index():
        _emit_progress(f"FAISS index already exists at {_DATA_DIR} — use force=True to rebuild")
        return True

    # Prefer a user-provided CSV if present; otherwise fall back to the bundled PDF
    if _CSV_INPUT_PATH.exists():
        _emit_progress(f"Building ICD-10 index from CSV: {_CSV_INPUT_PATH}")
        csv_start = time.time()
        icd10_entries = _extract_icd10_csv_entries(str(_CSV_INPUT_PATH))
        _emit_progress(f"Extracted {len(icd10_entries)} ICD-10 entries from CSV in {time.time() - csv_start:.1f}s")
    else:
        _emit_progress(f"Building ICD-10 index from PDF: {INPUT_PDF}")
        pdf_start = time.time()
        icd10_entries = _extract_icd10_pdf_entries(INPUT_PDF)
    if not icd10_entries:
        logger.error("No ICD-10 entries could be extracted from the input source")
        return False

    # ── Build embedding texts ──
    icd10_texts = [
        _build_texts_for_code(e["code"], e["description"], e["category"], e["synonyms"])
        for e in icd10_entries
    ]

    icd10_vectors = _encode_texts_with_progress(model, icd10_texts, "ICD-10 codes", batch_size=256)

    icd10_index = faiss.IndexFlatIP(icd10_vectors.shape[1])
    icd10_index.add(icd10_vectors)

    faiss.write_index(icd10_index, str(_ICD10_INDEX_PATH))
    with open(_ICD10_META_PATH, "w", encoding="utf-8") as f:
        json.dump(icd10_entries, f, ensure_ascii=False, indent=2)

    _emit_progress(
        f"ICD-10 FAISS index saved: {icd10_index.ntotal} vectors, dim={icd10_vectors.shape[1]}, file={_ICD10_INDEX_PATH}"
    )

    # ── Build BM25 sparse index over the same texts ──
    from rank_bm25 import BM25Okapi

    icd10_tokens = [_tokenize(t) for t in icd10_texts]
    icd10_bm25 = BM25Okapi(icd10_tokens)
    with open(_ICD10_BM25_PATH, "wb") as f:
        pickle.dump(icd10_bm25, f, protocol=pickle.HIGHEST_PROTOCOL)
    _emit_progress(
        f"ICD-10 BM25 index saved: {len(icd10_tokens)} docs, avgdl={icd10_bm25.avgdl:.1f}, file={_ICD10_BM25_PATH}"
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

    _emit_progress(f"Embedding {len(cpt_texts)} CPT codes...")
    cpt_vectors = _encode_texts_with_progress(model, cpt_texts, "CPT codes", batch_size=256)

    cpt_index = faiss.IndexFlatIP(cpt_vectors.shape[1])
    cpt_index.add(cpt_vectors)

    faiss.write_index(cpt_index, str(_CPT_INDEX_PATH))
    with open(_CPT_META_PATH, "w", encoding="utf-8") as f:
        json.dump(cpt_entries, f, ensure_ascii=False, indent=2)

    _emit_progress(f"CPT FAISS index saved: {cpt_index.ntotal} vectors, dim={cpt_vectors.shape[1]}")

    cpt_tokens = [_tokenize(t) for t in cpt_texts]
    cpt_bm25 = BM25Okapi(cpt_tokens)
    with open(_CPT_BM25_PATH, "wb") as f:
        pickle.dump(cpt_bm25, f, protocol=pickle.HIGHEST_PROTOCOL)
    _emit_progress(f"CPT BM25 index saved: {len(cpt_tokens)} docs")

    if load_after:
        _load_indices()
    return True


# ── Index loading ──────────────────────────────────────────────────

def _load_indices():
    """Load pre-built FAISS + BM25 indices from disk into memory."""
    global _icd10_index, _icd10_meta, _cpt_index, _cpt_meta
    global _icd10_bm25, _cpt_bm25

    try:
        import faiss
    except ImportError:
        logger.warning("faiss-cpu not installed — RAG search unavailable")
        return

    if _ICD10_INDEX_PATH.exists() and _ICD10_META_PATH.exists():
        if not _meta_is_pdf_index():
            logger.warning("Existing ICD-10 index is not PDF-based; rebuilding from the PDF source")
            if not build_index(force=True, load_after=False):
                return
        _icd10_index = faiss.read_index(str(_ICD10_INDEX_PATH))
        with open(_ICD10_META_PATH) as f:
            _icd10_meta = json.load(f)
        logger.info("Loaded ICD-10 FAISS index: %d codes", _icd10_index.ntotal)

    if _CPT_INDEX_PATH.exists() and _CPT_META_PATH.exists():
        _cpt_index = faiss.read_index(str(_CPT_INDEX_PATH))
        with open(_CPT_META_PATH) as f:
            _cpt_meta = json.load(f)
        logger.info("Loaded CPT FAISS index: %d codes", _cpt_index.ntotal)

    # BM25 indices are optional — older deployments may only have FAISS
    # on disk. In that case hybrid/bm25 search modes silently fall back
    # to dense.
    if _ICD10_BM25_PATH.exists():
        try:
            with open(_ICD10_BM25_PATH, "rb") as f:
                _icd10_bm25 = pickle.load(f)
            logger.info(
                "Loaded ICD-10 BM25 index: %d docs",
                len(getattr(_icd10_bm25, "doc_freqs", [])),
            )
        except Exception:
            logger.warning("Failed to load ICD-10 BM25 index", exc_info=True)
            _icd10_bm25 = None

    if _CPT_BM25_PATH.exists():
        try:
            with open(_CPT_BM25_PATH, "rb") as f:
                _cpt_bm25 = pickle.load(f)
            logger.info(
                "Loaded CPT BM25 index: %d docs",
                len(getattr(_cpt_bm25, "doc_freqs", [])),
            )
        except Exception:
            logger.warning("Failed to load CPT BM25 index", exc_info=True)
            _cpt_bm25 = None

    # Indices were rebuilt or freshly loaded — drop any stale cached
    # results so subsequent searches use the current index.
    try:
        _search_icd10_rag_cached.cache_clear()
        _search_cpt_rag_cached.cache_clear()
    except NameError:
        # Cached helpers defined later in module — first load is safe.
        pass


def preload_rag_models():
    """Preload FAISS/BM25 indices and embedding models into process memory.

    Safe to call from worker startup to avoid per-request model downloads
    and index loading latency. Non-fatal on failure; logs warnings.
    """
    global _clinical_embed_model, _crossencoder_model, _crossencoder_load_attempted
    try:
        import torch
        import os
        torch.set_num_threads(os.cpu_count() or 4)
    except Exception:
        pass

    try:
        _load_indices()
    except Exception:
        logger.warning("Preloading indices failed", exc_info=True)

    try:
        _load_model()
    except Exception:
        logger.warning("Preloading embedding model failed", exc_info=True)

    try:
        if _crossencoder_model is None and not _crossencoder_load_attempted:
            _crossencoder_load_attempted = True
            from sentence_transformers import CrossEncoder  # type: ignore
            _crossencoder_model = CrossEncoder(_CROSSENCODER_MODEL)
            logger.info("Preloaded cross-encoder reranker: %s", _CROSSENCODER_MODEL)
    except Exception:
        logger.warning("Preloading cross-encoder model failed", exc_info=True)

    try:
        if _ENABLE_LOCAL_CLINICAL_RERANK and _clinical_embed_model is None:
            from sentence_transformers import SentenceTransformer  # type: ignore
            model_name = os.environ.get("CLINICAL_EMBED_MODEL", _EMBEDDING_MODEL)
            _clinical_embed_model = SentenceTransformer(model_name)
            logger.info("Preloaded clinical embedding model: %s", model_name)
    except Exception:
        logger.debug("Clinical embed model not available for preload", exc_info=True)


# ── Public search API ──────────────────────────────────────────────

def is_rag_available() -> bool:
    """Check whether the RAG index is loaded and ready."""
    if _icd10_index is None:
        _load_indices()
    return _icd10_index is not None


def is_bm25_available() -> bool:
    """Whether BM25 sparse indices are present (enables hybrid search)."""
    if _icd10_bm25 is None and _cpt_bm25 is None:
        _load_indices()
    return _icd10_bm25 is not None


def _resolve_mode(mode: str | None) -> str:
    """Coerce ``mode`` to a valid search mode, falling back gracefully.

    If ``hybrid`` or ``bm25`` is requested but BM25 indices aren't loaded,
    silently fall back to ``dense`` so old deployments keep working.
    """
    m = (mode or _DEFAULT_MODE).lower()
    if m not in _VALID_MODES:
        m = "dense"
    if m in ("hybrid", "bm25") and not is_bm25_available():
        logger.debug("BM25 not available; falling back to dense for mode=%r", mode)
        m = "dense"
    return m


def search_icd10_rag(
    query: str,
    max_results: int = 5,
    min_score: float = 0.25,
    mode: str | None = None,
) -> list[tuple[str, str, str, float]]:
    """
    Search for ICD-10 codes.

    Parameters
    ----------
    query : str
        Free-text clinical query.
    max_results : int
        Max results to return.
    min_score : float
        Minimum score for ``mode="dense"`` (cosine similarity in [0,1]).
        Ignored for ``bm25`` and ``hybrid`` modes since their score
        distributions aren't directly comparable to cosine similarity.
    mode : str
        ``"dense"`` (FAISS only), ``"bm25"`` (lexical only), or
        ``"hybrid"`` (RRF fusion of both — default; best recall).

    Returns
    -------
    list of (code, description, category, score) tuples,
    sorted by descending score.

    Results are cached per-process via an LRU keyed on the normalized
    query + parameters (size configurable via CODING_RAG_CACHE_SIZE).
    Use ``clear_search_cache()`` to invalidate (e.g. after rebuilding
    the index).
    """
    q = (query or "").strip().lower()
    if not q:
        return []
    return list(_search_icd10_rag_cached(q, max_results, min_score, _resolve_mode(mode)))


def search_cpt_rag(
    query: str,
    max_results: int = 5,
    min_score: float = 0.25,
    mode: str | None = None,
) -> list[tuple[str, str, str, float]]:
    """
    Search for CPT codes. See ``search_icd10_rag`` for parameter docs.
    """
    q = (query or "").strip().lower()
    if not q:
        return []
    return list(_search_cpt_rag_cached(q, max_results, min_score, _resolve_mode(mode)))


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


# ── Internal: ranking primitives ──────────────────────────────────

def _dense_rank(query: str, faiss_index, meta: list[dict], top_k: int) -> list[tuple[int, float]]:
    """Return [(meta_idx, cosine_score)] from FAISS for ``query``."""
    model = _load_model()
    if model is None or faiss_index is None:
        return []
    query_vec = model.encode([query], normalize_embeddings=True, show_progress_bar=False)
    query_vec = np.array(query_vec, dtype=np.float32)
    scores, indices = faiss_index.search(query_vec, min(top_k, faiss_index.ntotal))
    return [
        (int(idx), float(score))
        for idx, score in zip(indices[0], scores[0])
        if idx >= 0
    ]


def _bm25_rank(query: str, bm25, top_k: int) -> list[tuple[int, float]]:
    """Return [(meta_idx, bm25_score)] from BM25 for ``query``."""
    if bm25 is None:
        return []
    tokens = _tokenize(query)
    if not tokens:
        return []
    scores = bm25.get_scores(tokens)
    if len(scores) == 0:
        return []
    # Top-k by score, descending. argsort is ascending so flip.
    k = min(top_k, len(scores))
    top_idx = np.argpartition(scores, -k)[-k:]
    top_idx = top_idx[np.argsort(-scores[top_idx])]
    return [(int(i), float(scores[i])) for i in top_idx if scores[i] > 0]


def _rrf_fuse(
    rankings: list[list[tuple[int, float]]],
    k: int = _RRF_K,
) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion across multiple ranker outputs.

    score(doc) = sum_{r in rankers} 1 / (k + rank_in_r(doc))

    This is robust because it ignores the absolute score distributions
    of each ranker — it only needs ordinal positions.
    """
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, (idx, _) in enumerate(ranking):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return sorted(fused.items(), key=lambda x: x[1], reverse=True)


def _to_results(
    pairs: list[tuple[int, float]],
    meta: list[dict],
    max_results: int,
) -> tuple[tuple[str, str, str, float], ...]:
    out: list[tuple[str, str, str, float]] = []
    for idx, score in pairs:
        if idx < 0 or idx >= len(meta):
            continue
        e = meta[idx]
        if not isinstance(e, dict):
            logger.warning("Skipping malformed coding index entry at idx=%s: expected dict, got %s", idx, type(e).__name__)
            continue

        code = e.get("code")
        if not code:
            logger.warning("Skipping malformed coding index entry at idx=%s: missing code", idx)
            continue

        out.append(
            (
                str(code),
                str(e.get("description") or ""),
                str(e.get("category") or ""),
                float(score),
            )
        )
        if len(out) >= max_results:
            break
    return tuple(out)


def _synonym_prior_results(query: str, max_results: int) -> list[tuple[str, str, str, float]]:
    """Return high-confidence exact/near-exact ICD matches from the loaded RAG metadata.

    This reuses the loaded RAG metadata to surface exact clinical phrases/codes
    before semantic reranking, without relying on hardcoded clinical synonym tables
    or calling recursive search functions.
    """
    global _icd10_meta
    if not _icd10_meta:
        return []

    text_lower = query.lower().strip()
    out: list[tuple[str, str, str, float]] = []
    seen = set()
    idx = 0

    # 1. Exact match by code or description
    for entry in _icd10_meta:
        code = str(entry.get("code") or "").strip()
        desc = str(entry.get("description") or "").strip()
        cat = str(entry.get("category") or "").strip()
        
        if code.lower() == text_lower or desc.lower() == text_lower:
            if code not in seen:
                seen.add(code)
                out.append((code, desc, cat, 1.0 - idx * 0.001))
                idx += 1
                if len(out) >= max_results:
                    return out

    return out


def _merge_prior_and_ranked(
    prior: list[tuple[str, str, str, float]],
    ranked: list[tuple[str, str, str, float]],
    max_results: int,
) -> tuple[tuple[str, str, str, float], ...]:
    prior_codes = {code for code, _desc, _cat, _score in prior}
    merged = prior + [row for row in ranked if row[0] not in prior_codes]
    return tuple(merged[:max_results])


def _score_icd_candidate(query: str, code: str, description: str, category: str, base_score: float) -> float:
    """Adjust a retrieval score using generic query support and contradiction penalties.

    This keeps the CSV as the source of truth while making candidate ranking
    follow the extracted clinical phrase. Heuristics here are intentionally
    minimal — only used for validation and tie-breaking after model rerankers.
    """
    q_tokens = set(_tokenize(query))
    d_tokens = set(_tokenize(description))

    score = float(base_score)

    # Small boost for overlap; only a tie-breaker.
    shared = q_tokens & d_tokens
    score += min(len(shared) * 0.02, 0.08)

    # Slightly prefer parent codes when query is broad (dotted subcodes mean more specific).
    if "." in code:
        score -= 0.01
    else:
        score += 0.005

    # Penalize candidate descriptions that introduce many extra long terms
    # not present in the query — indicates the candidate is more specific.
    extra_terms = {tok for tok in d_tokens - q_tokens if len(tok) > 3}
    score -= min(len(extra_terms) * 0.008, 0.06)

    return max(score, 0.0)


def _prefer_parent_code_if_query_broad(
    query: str,
    candidate_map: dict[str, tuple[str, str, str, float]],
    code: str,
) -> str:
    """Prefer the broader parent code when the query does not mention child-specific wording."""
    if "." not in code:
        return code

    parent_code = code.split(".", 1)[0]
    parent = candidate_map.get(parent_code)
    child = candidate_map.get(code)
    if not parent or not child:
        return code

    query_tokens = set(_tokenize(query))
    child_tokens = set(_tokenize(child[1]))
    parent_tokens = set(_tokenize(parent[1]))
    shared_tokens = child_tokens & parent_tokens
    structural_noise = {"and", "or", "of", "the", "with", "without", "other", "unspecified", "specified", "abnormal", "normal"}
    specific_child_tokens = {tok for tok in child_tokens - shared_tokens if tok not in structural_noise}
    if specific_child_tokens and not (specific_child_tokens & query_tokens):
        return parent_code
    return code


def _rerank_icd_results(query: str, results: list[tuple[str, str, str, float]]) -> list[tuple[str, str, str, float]]:
    """Apply the query-aware scoring step to the candidate list."""
    # Prefer OpenRouter (ClinicalGPT via OpenRouter) reranker first
    candidate_map = {code: (code, desc, cat, score) for code, desc, cat, score in results}
    llm_choice = _try_llm_rerank_icd(query, results)
    if llm_choice:
        llm_choice = _prefer_parent_code_if_query_broad(query, candidate_map, llm_choice)
        chosen = [row for row in results if row[0] == llm_choice]
        if chosen:
            return chosen + [row for row in results if row[0] != llm_choice]

    # Cross-encoder reranker: sees query + candidate description TOGETHER
    # in one forward pass → direct relevance score → much more accurate
    # than bi-encoder cosine similarity.
    if _ENABLE_LOCAL_CLINICAL_RERANK:
        try:
            cross_results = _try_crossencoder_rerank(query, results)
        except Exception:
            cross_results = None
        if cross_results:
            return cross_results

        # S-PubMedBert bi-encoder as last ML resort before deterministic scorer
        try:
            local_choice = _try_local_clinical_rerank(query, results)
        except Exception:
            local_choice = None
        if local_choice:
            local_choice = _prefer_parent_code_if_query_broad(query, candidate_map, local_choice)
            chosen = [row for row in results if row[0] == local_choice]
            if chosen:
                return chosen + [row for row in results if row[0] != local_choice]

    # Deterministic minimal scoring as final tie-breaker
    reranked = [
        (code, desc, cat, _score_icd_candidate(query, code, desc, cat, score))
        for code, desc, cat, score in results
    ]
    reranked.sort(key=lambda item: item[3], reverse=True)
    if reranked:
        top_code = _prefer_parent_code_if_query_broad(query, {code: row for code, *row in reranked}, reranked[0][0])
        if top_code != reranked[0][0]:
            parent_row = next((row for row in reranked if row[0] == top_code), None)
            if parent_row:
                reranked = [parent_row] + [row for row in reranked if row[0] != top_code]
    return reranked


def _persist_icd_rerank_debug(
    stage: str,
    query: str,
    candidates: list[tuple[str, str, str, float]],
    system_prompt: str,
    user_message: str,
    response_text: str,
) -> None:
    try:
        base = os.path.join(os.getcwd(), "tmp", "parser_debug", "llm_calls")
        os.makedirs(base, exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat()
        payload = {
            "timestamp": ts,
            "provider": "openrouter",
            "stage": stage,
            "query": scrub_phi(query),
            "candidates": [
                {"code": code, "description": desc, "category": cat, "score": score}
                for code, desc, cat, score in candidates
            ],
            "system_prompt": scrub_phi(system_prompt),
            "user_message": scrub_phi(user_message),
            "response": scrub_phi(response_text),
        }
        filename = f"{ts.replace(':', '-')}_{stage}.json"
        path = os.path.join(base, filename)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        logger.exception("Failed to persist ICD rerank debug")


def _try_llm_rerank_icd(query: str, candidates: list[tuple[str, str, str, float]]) -> str | None:
    """Ask OpenRouter to pick the best ICD code. Disabled by default (CODING_ENABLE_LLM_RERANK=1 to enable)."""
    if not candidates:
        return None
    if os.environ.get("CODING_ENABLE_LLM_RERANK", "0").strip().lower() not in {"1", "true", "yes", "on"}:
        return None
    try:
        import httpx
        from services.parser.app.config import settings as parser_settings  # type: ignore
    except Exception:
        return None
    api_key = getattr(parser_settings, "openrouter_api_key", "") or os.environ.get("OPENROUTER_API_KEY", "")
    model = getattr(parser_settings, "openrouter_model", "") or os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    url = getattr(parser_settings, "openrouter_url", "") or "https://openrouter.ai/api/v1/chat/completions"
    if not api_key:
        logger.warning("OpenRouter API key not configured — skipping LLM reranking for coding")
        return None
    short_list = sorted(candidates, key=lambda item: item[3], reverse=True)[:40]
    system_prompt = (
        "You are an ICD-10 reranker. Choose the single best ICD-10 code from the candidates. "
        "Prefer the code that matches the primary clinical event. "
        "When both a parent code and a subtype are candidates, prefer the parent unless the query specifies the subtype. "
        "Return only the code, no explanation."
    )
    candidate_block = "\n".join(f"- {code}: {desc} [{cat}]" for code, desc, cat, _score in short_list)
    user_message = f"Query: {query}\n\nCandidates:\n{candidate_block}\n\nPick the single best code."
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}],
        "temperature": 0.0,
        "max_tokens": 12,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        resp = httpx.post(url, json=payload, headers=headers,
                          timeout=int(os.environ.get("CODING_RERANKER_TIMEOUT", "20")))
        resp.raise_for_status()
        data = resp.json()
        raw = ""
        if isinstance(data, dict) and data.get("choices"):
            msg = data["choices"][0].get("message", {})
            raw = str(msg.get("content") or "") if isinstance(msg, dict) else str(msg)
        _persist_icd_rerank_debug("openrouter_icd_rerank", query, short_list,
                                  system_prompt, user_message, raw)
        codes = {c.upper(): c for c, *_ in short_list}
        norm = re.sub(r"[^A-Z0-9.]", "", raw.upper())
        if norm in codes:
            return codes[norm]
        for c in codes.values():
            if c.upper() in raw.upper():
                return c
        return None
    except Exception as exc:
        logger.warning("LLM reranker (OpenRouter) is unavailable or failed: %s", exc)
        return None


def _try_crossencoder_rerank(query: str, candidates: list[tuple[str, str, str, float]]) -> list[tuple[str, str, str, float]] | None:
    """Rerank ICD candidates using a cross-encoder model.

    A cross-encoder takes (query, candidate_description) as a PAIR and produces
    a direct relevance score in a single forward pass.  This is far more accurate
    than bi-encoder cosine similarity (S-PubMedBert) because the model attends to
    BOTH texts simultaneously.

    Model: cross-encoder/ms-marco-MiniLM-L-6-v2 (fast, ~50ms/batch on CPU).
    Override via CODING_CROSSENCODER_MODEL env var.
    """
    global _crossencoder_model, _crossencoder_load_attempted
    if not candidates:
        return None
    try:
        try:
            import torch
            import os
            torch.set_num_threads(os.cpu_count() or 4)
        except Exception:
            pass
        if _crossencoder_model is None and not _crossencoder_load_attempted:
            _crossencoder_load_attempted = True
            from sentence_transformers import CrossEncoder  # type: ignore
            device = _get_device()
            _crossencoder_model = CrossEncoder(_CROSSENCODER_MODEL, device=device)
            logger.info("Loaded cross-encoder reranker: %s on device: %s", _CROSSENCODER_MODEL, device)
        if _crossencoder_model is None:
            return None
        # Score top-50 candidates; cross-encoder is fast enough for this pool size.
        short_list = sorted(candidates, key=lambda item: item[3], reverse=True)[:50]
        pairs = [(query, f"{desc} | {cat}") for code, desc, cat, _score in short_list]
        scores = _crossencoder_model.predict(pairs, show_progress_bar=False)
        
        # Build list of scored candidates
        scored_candidates = []
        for idx, (code, desc, cat, _) in enumerate(short_list):
            scored_candidates.append((code, desc, cat, float(scores[idx])))
            
        # Sort by cross-encoder score descending
        scored_candidates.sort(key=lambda x: x[3], reverse=True)
        
        # Apply parent code preference threshold if needed
        best_code = scored_candidates[0][0]
        best_score = scored_candidates[0][3]
        parent_pref = float(os.environ.get("CODING_PARENT_PREF_THRESH", "0.05"))
        chosen_code = best_code
        for i, (code, _desc, _cat, score) in enumerate(scored_candidates):
            if "." in code:
                parent = code.split(".", 1)[0]
                for j, (pcode, *_) in enumerate(scored_candidates):
                    if pcode == parent:
                        if (best_score - scored_candidates[j][3]) <= parent_pref:
                            chosen_code = parent
                        break
        
        # Move the chosen parent code to the top if it changed
        if chosen_code != best_code:
            chosen_row = next((row for row in scored_candidates if row[0] == chosen_code), None)
            if chosen_row:
                scored_candidates = [chosen_row] + [row for row in scored_candidates if row[0] != chosen_code]
                
        # Filter out candidates with very low cross-encoder relevance scores (e.g. < 1.0)
        # to prevent returning completely irrelevant codes (like breech delivery for vertex delivery).
        # We only apply this if there is at least one highly relevant candidate (best_score >= 2.0).
        if best_score >= 2.0:
            filtered_candidates = []
            for code, desc, cat, score in scored_candidates:
                if score >= 1.0 or code == chosen_code:
                    # Keep the candidate but normalize its score to [0, 1] range for RAG downstream compatibility
                    norm_score = max(0.01, min(1.0, (score + 2.0) / 10.0))
                    filtered_candidates.append((code, desc, cat, norm_score))
            scored_candidates = filtered_candidates
        else:
            # Map scores to [0, 1] range for RAG compatibility
            scored_candidates = [
                (code, desc, cat, max(0.01, min(1.0, (score + 2.0) / 10.0)))
                for code, desc, cat, score in scored_candidates
            ]
            
        try:
            _persist_icd_rerank_debug("crossencoder_rerank", query, short_list,
                                      f"cross_encoder:{_CROSSENCODER_MODEL}",
                                      "cross_encoder_relevance_scoring", chosen_code)
        except Exception:
            pass
            
        return scored_candidates
    except Exception:
        logger.debug("Cross-encoder reranker failed", exc_info=True)
        return None


def _try_local_clinical_rerank(query: str, candidates: list[tuple[str, str, str, float]]) -> str | None:
    """S-PubMedBert bi-encoder fallback reranker (used when cross-encoder is unavailable)."""
    global _clinical_embed_model
    if not candidates:
        return None
    try:
        try:
            import torch
            import os
            torch.set_num_threads(os.cpu_count() or 4)
        except Exception:
            pass
        if _clinical_embed_model is None:
            from sentence_transformers import SentenceTransformer  # type: ignore
            device = _get_device()
            _clinical_embed_model = SentenceTransformer(
                os.environ.get("CLINICAL_EMBED_MODEL", "pritamdeka/S-PubMedBert-MS-MARCO"),
                device=device
            )
        short_list = sorted(candidates, key=lambda item: item[3], reverse=True)[:16]
        texts = [query] + [f"{desc} | {cat}" for code, desc, cat, _ in short_list]
        embs = _clinical_embed_model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        q_emb = embs[0]
        q_norm = sqrt((q_emb * q_emb).sum())
        sims = np.array([
            float((q_emb @ e) / (q_norm * sqrt((e * e).sum()))) if q_norm * sqrt((e * e).sum()) > 0 else 0.0
            for e in embs[1:]
        ])
        best_idx = int(np.argmax(sims))
        best_score = float(sims[best_idx])
        chosen = short_list[best_idx][0]
        parent_pref = float(os.environ.get("CODING_PARENT_PREF_THRESH", "0.05"))
        for i, (code, *_) in enumerate(short_list):
            if "." in code:
                parent = code.split(".", 1)[0]
                for j, (pcode, *_r) in enumerate(short_list):
                    if pcode == parent and (best_score - float(sims[j])) <= parent_pref:
                        chosen = parent
                        break
        try:
            _persist_icd_rerank_debug("local_clinical_rerank", query, candidates,
                                      "bi_encoder:S-PubMedBert", "cosine_rerank", chosen)
        except Exception:
            pass
        return chosen
    except Exception:
        logger.debug("Local clinical reranker unavailable or failed", exc_info=True)
        return None


def lookup_icd10_rag(code: str) -> tuple[str, str, str] | None:
    """Return the exact ICD-10 entry from the loaded RAG metadata, if present.

    This avoids falling back to the hardcoded ``icd10_codes.py`` lookup path.
    """
    if not code:
        return None
    if not is_rag_available():
        return None

    normalized = re.sub(r"[^A-Z0-9]", "", str(code).strip().upper())
    assert _icd10_meta is not None
    for entry in _icd10_meta:
        if not isinstance(entry, dict):
            continue
        entry_code = re.sub(r"[^A-Z0-9]", "", str(entry.get("code") or "").strip().upper())
        if entry_code == normalized:
            return (
                str(entry.get("code") or normalized),
                str(entry.get("description") or ""),
                str(entry.get("category") or ""),
            )
    return None


@functools.lru_cache(maxsize=_RAG_CACHE_SIZE)
def _search_icd10_rag_cached(
    query: str,
    max_results: int,
    min_score: float,
    mode: str,
) -> tuple[tuple[str, str, str, float], ...]:
    """LRU-cached inner search. Returns tuple (immutable) for hashability.

    Pipeline: FAISS dense + BM25 sparse → RRF fusion → local S-PubMedBert
    reranker → top-k results.  The reranker is controlled by
    CODING_ENABLE_LOCAL_RERANK (default: 1 = on).
    """
    if not is_rag_available():
        return ()
    assert _icd10_index is not None  # narrow for type checker

    # Pull a wider candidate pool so the reranker sees enough depth to
    # surface the correct code (e.g. O80 at rank 4 in raw retrieval).
    pool = max(max_results * 10, _RERANK_POOL_DEFAULT)

    prior = _synonym_prior_results(query, max_results)

    if mode == "dense":
        dense = _dense_rank(query, _icd10_index, _icd10_meta, pool)
        # min_score gate only meaningful for cosine similarity scores.
        filtered = [(i, s) for i, s in dense if s >= min_score]
        dense_results = list(_to_results(filtered, _icd10_meta, pool))
        reranked = _rerank_icd_results(query, dense_results)
        return _merge_prior_and_ranked(prior, reranked, max_results)

    if mode == "bm25":
        bm25_hits = list(_to_results(_bm25_rank(query, _icd10_bm25, pool), _icd10_meta, pool))
        reranked = _rerank_icd_results(query, bm25_hits)
        return _merge_prior_and_ranked(prior, reranked, max_results)

    # hybrid (default): FAISS dense + BM25 sparse → RRF → reranker
    dense = _dense_rank(query, _icd10_index, _icd10_meta, pool)
    sparse = _bm25_rank(query, _icd10_bm25, pool)
    fused = list(_to_results(_rrf_fuse([dense, sparse]), _icd10_meta, pool))
    reranked = _rerank_icd_results(query, fused)
    return _merge_prior_and_ranked(prior, reranked, max_results)


@functools.lru_cache(maxsize=_RAG_CACHE_SIZE)
def _search_cpt_rag_cached(
    query: str,
    max_results: int,
    min_score: float,
    mode: str,
) -> tuple[tuple[str, str, str, float], ...]:
    """LRU-cached inner CPT search."""
    if _cpt_index is None:
        _load_indices()
    if _cpt_index is None:
        return ()

    pool = max(max_results * 4, 20)

    if mode == "dense":
        dense = _dense_rank(query, _cpt_index, _cpt_meta, pool)
        filtered = [(i, s) for i, s in dense if s >= min_score]
        return _to_results(filtered, _cpt_meta, max_results)

    if mode == "bm25":
        return _to_results(
            _bm25_rank(query, _cpt_bm25, pool), _cpt_meta, max_results,
        )

    # hybrid
    dense = _dense_rank(query, _cpt_index, _cpt_meta, pool)
    sparse = _bm25_rank(query, _cpt_bm25, pool)
    return _to_results(_rrf_fuse([dense, sparse]), _cpt_meta, max_results)
