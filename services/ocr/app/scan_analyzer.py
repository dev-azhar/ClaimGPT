"""
Medical Scan Analyzer — detects and extracts findings from MRI, CT, X-Ray,
and Ultrasound images/reports uploaded as supporting documents.

Two analysis modes:
1. TEXT-BASED: Analyses OCR-extracted text from radiology reports
2. IMAGE-BASED: Analyses DICOM-like images via pixel characteristics

Returns structured findings: scan_type, body_part, modality, findings, impression.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("ocr.scan_analyzer")

# ── Scan type detection patterns ──
_SCAN_TYPE_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    ("MRI", "Magnetic Resonance Imaging", re.compile(
        r"\b(?:MRI|M\.R\.I|magnetic\s+resonance|MR\s+imaging|MR\s+scan)\b", re.IGNORECASE)),
    ("CT", "Computed Tomography", re.compile(
        r"\b(?:CT\s+scan|C\.T|computed\s+tomography|HRCT|CECT|NCCT|CT\s+with\s+contrast|CAT\s+scan)\b", re.IGNORECASE)),
    ("X-Ray", "X-Ray Radiograph", re.compile(
        r"\b(?:X[\-\s]?Ray|radiograph|plain\s+film|chest\s+PA|AP\s+view|lateral\s+view)\b", re.IGNORECASE)),
    ("Ultrasound", "Ultrasonography", re.compile(
        r"\b(?:ultrasound|ultrasonography|USG|sonography|doppler)\b", re.IGNORECASE)),
    ("PET", "Positron Emission Tomography", re.compile(
        r"\b(?:PET\s+scan|PET[\-/]CT|positron\s+emission)\b", re.IGNORECASE)),
    ("Mammography", "Mammogram", re.compile(
        r"\b(?:mammogra(?:m|phy)|breast\s+imaging)\b", re.IGNORECASE)),
    ("Angiography", "Angiogram", re.compile(
        r"\b(?:angiogra(?:m|phy)|DSA|catheter\s+study|coronary\s+angio)\b", re.IGNORECASE)),
]

# ── Body part detection ──
_BODY_PART_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("Brain / Head", re.compile(r"\b(?:brain|head|cranial|intracranial|cerebr|skull|sella)\b", re.IGNORECASE)),
    ("Spine", re.compile(r"\b(?:spine|spinal|lumbar|cervical|thoracic|vertebr|disc|lumbosacral|dorsal\s+spine)\b", re.IGNORECASE)),
    ("Chest", re.compile(r"\b(?:chest|thorax|lung|pulmonary|pleural|mediastin|cardiac|heart)\b", re.IGNORECASE)),
    ("Abdomen", re.compile(r"\b(?:abdomen|abdominal|liver|hepat|spleen|pancrea|kidney|renal|gallbladder|biliary)\b", re.IGNORECASE)),
    ("Pelvis", re.compile(r"\b(?:pelvi[cs]|hip|uterus|ovary|prostate|bladder|sacroiliac)\b", re.IGNORECASE)),
    ("Knee", re.compile(r"\b(?:knee|patell|meniscus|cruciate|tibial\s+plateau)\b", re.IGNORECASE)),
    ("Shoulder", re.compile(r"\b(?:shoulder|rotator\s+cuff|glenohumeral|acromi)\b", re.IGNORECASE)),
    ("Neck", re.compile(r"\b(?:neck|thyroid|laryn|pharyn|cervical\s+soft)\b", re.IGNORECASE)),
    ("Extremity", re.compile(r"\b(?:hand|wrist|elbow|ankle|foot|femur|tibia|humerus|forearm|leg)\b", re.IGNORECASE)),
    ("Whole Body", re.compile(r"\b(?:whole\s+body|full\s+body)\b", re.IGNORECASE)),
]

# ── Report section patterns ──
_FINDINGS_PATTERN = re.compile(
    r"(?:FINDINGS|Findings|OBSERVATION|Observation)[:\s]*\n?([\s\S]*?)(?=\n\s*(?:IMPRESSION|Impression|CONCLUSION|Conclusion|OPINION|Opinion|RECOMMENDATION|$))",
    re.IGNORECASE,
)
_IMPRESSION_PATTERN = re.compile(
    r"(?:IMPRESSION|Impression|CONCLUSION|Conclusion|OPINION|Opinion)[:\s]*\n?([\s\S]*?)(?=\n\s*(?:RECOMMENDATION|Recommendation|ADVICE|Advised|$))",
    re.IGNORECASE,
)
_RECOMMENDATION_PATTERN = re.compile(
    r"(?:RECOMMENDATION|Recommendation|ADVICE|Advised|SUGGESTED|FOLLOW[\-\s]UP)[:\s]*\n?([\s\S]*?)$",
    re.IGNORECASE,
)

# ── Abnormality keywords ──
_ABNORMAL_KEYWORDS = re.compile(
    r"\b(?:fracture|mass|lesion|tumor|tumour|nodule|opacity|effusion|stenosis|"
    r"herniat|bulge|tear|rupture|infarct|hemorrhage|haemorrhage|thrombus|"
    r"thrombosis|embolism|aneurysm|dissection|edema|oedema|collection|abscess|"
    r"calcif|calculus|stone|obstruction|perforation|collapse|atelectasis|"
    r"consolidation|infiltrate|fibrosis|necrosis|erosion|degenerat|"
    r"spondylol|narrowing|compression|displacement|abnormal|irregular|"
    r"enlarged|dilat|hypertrop|atroph|malignant|metastas|polyp|cyst|"
    r"inflammation|inflamed|swelling|thickening|heterogeneous|suspicious)\b",
    re.IGNORECASE,
)

_NORMAL_KEYWORDS = re.compile(
    r"\b(?:normal|unremarkable|no\s+(?:significant|abnormal|evidence)|within\s+normal\s+limits|"
    r"no\s+fracture|no\s+mass|no\s+lesion|essentially\s+normal|no\s+acute|negative|"
    r"no\s+focal|preserved|intact|symmetrical|clear\s+lung)\b",
    re.IGNORECASE,
)

# ── Scan-relevant file detection ──
_SCAN_FILE_EXTENSIONS = {".dcm", ".dicom", ".nii", ".nii.gz"}
_SCAN_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp"}
_RADIOLOGY_KEYWORDS = re.compile(
    r"\b(?:radiology|radiolog|scan\s+report|imaging\s+report|MRI\s+report|CT\s+report|"
    r"X[\-\s]?Ray\s+report|ultrasound\s+report|sonography\s+report|"
    r"diagnostic\s+imaging|nuclear\s+medicine)\b",
    re.IGNORECASE,
)


@dataclass
class ScanFinding:
    finding: str
    severity: str = "info"  # info, warning, critical
    confidence: float = 0.0


@dataclass
class ScanResult:
    scan_type: str  # MRI, CT, X-Ray, Ultrasound, PET, etc.
    scan_type_full: str
    body_part: str
    modality: str  # e.g., "T2-weighted", "with contrast", "plain"
    findings: list[ScanFinding]
    impression: str
    recommendation: str
    is_abnormal: bool
    confidence: float
    raw_text: str = ""


def is_scan_document(file_name: str, ocr_text: str) -> bool:
    """Detect whether a document is a medical scan or radiology report."""
    name_lower = file_name.lower()
    ext = Path(file_name).suffix.lower()

    # Explicit scan file formats
    if ext in _SCAN_FILE_EXTENSIONS:
        return True

    # File name hints
    scan_name_hints = re.compile(
        r"(?:mri|ct|x[\-_]?ray|scan|radiology|ultrasound|usg|dicom|imaging|xray)",
        re.IGNORECASE,
    )
    if scan_name_hints.search(name_lower):
        return True

    # Check OCR text for radiology report markers
    if _RADIOLOGY_KEYWORDS.search(ocr_text):
        return True

    # Check for scan type mentions in text, but avoid classifying clinical summaries
    # as radiology docs purely due generic terms unless radiology context exists.
    for stype, _, pattern in _SCAN_TYPE_PATTERNS:
        if pattern.search(ocr_text):
            if stype == "Ultrasound":
                if _RADIOLOGY_KEYWORDS.search(ocr_text) or re.search(r"\b(?:ultrasound|usg|sonography|doppler\s+study)\b", ocr_text, re.IGNORECASE):
                    return True
                continue
            return True

    return False


def analyze_scan(file_name: str, ocr_text: str, file_path: str | None = None) -> ScanResult | None:
    """
    Analyze a medical scan document and extract structured findings.

    Works in two modes:
    1. Text analysis of radiology report OCR text
    2. Image analysis for actual scan images (basic metadata)
    """
    if not ocr_text and not file_path:
        return None

    text = ocr_text or ""

    # ── Detect scan type ──
    scan_type = "Unknown"
    scan_type_full = "Medical Imaging Study"
    for stype, sfull, pattern in _SCAN_TYPE_PATTERNS:
        if pattern.search(text) or pattern.search(file_name):
            scan_type = stype
            scan_type_full = sfull
            break

    # ── Detect body part ──
    body_part = "Unspecified"
    for bpart, pattern in _BODY_PART_PATTERNS:
        if pattern.search(text):
            body_part = bpart
            break

    # ── Detect modality details ──
    modality = _detect_modality(text, scan_type)

    # ── Extract report sections ──
    findings_text = ""
    impression_text = ""
    recommendation_text = ""

    m = _FINDINGS_PATTERN.search(text)
    if m:
        findings_text = m.group(1).strip()[:1500]

    m = _IMPRESSION_PATTERN.search(text)
    if m:
        impression_text = m.group(1).strip()[:800]

    m = _RECOMMENDATION_PATTERN.search(text)
    if m:
        recommendation_text = m.group(1).strip()[:500]

    # If no structured sections found, try to extract key sentences
    if not findings_text and not impression_text:
        findings_text, impression_text = _extract_unstructured(text)

    # ── Parse individual findings ──
    findings = _parse_findings(findings_text or impression_text or text)

    # ── Determine abnormality ──
    full_report = f"{findings_text} {impression_text}"
    abnormal_count = len(_ABNORMAL_KEYWORDS.findall(full_report))
    normal_count = len(_NORMAL_KEYWORDS.findall(full_report))
    is_abnormal = abnormal_count > normal_count

    # ── Confidence score ──
    confidence = _compute_confidence(text, findings_text, impression_text, scan_type)

    # ── Image-based analysis if available ──
    if file_path and not findings_text:
        img_info = _analyze_image_metadata(file_path)
        if img_info:
            if not findings:
                findings.append(ScanFinding(
                    finding=f"Medical image uploaded ({img_info.get('format', 'unknown')} format, "
                            f"{img_info.get('width', '?')}x{img_info.get('height', '?')} pixels)",
                    severity="info",
                    confidence=0.6,
                ))
            if img_info.get("is_grayscale"):
                findings.append(ScanFinding(
                    finding="Image appears to be a grayscale medical scan (consistent with radiology imaging)",
                    severity="info",
                    confidence=0.7,
                ))

    if not findings:
        return None

    return ScanResult(
        scan_type=scan_type,
        scan_type_full=scan_type_full,
        body_part=body_part,
        modality=modality,
        findings=findings,
        impression=impression_text or _build_auto_impression(findings, is_abnormal),
        recommendation=recommendation_text,
        is_abnormal=is_abnormal,
        confidence=confidence,
        raw_text=text[:500],
    )


def _detect_modality(text: str, scan_type: str) -> str:
    """Detect imaging modality details."""
    modality_parts = []
    if re.search(r"\bwith\s+contrast|CECT|post[\-\s]contrast|gadolinium|IV\s+contrast\b", text, re.IGNORECASE):
        modality_parts.append("with contrast")
    elif re.search(r"\bwithout\s+contrast|NCCT|plain|non[\-\s]contrast\b", text, re.IGNORECASE):
        modality_parts.append("plain / without contrast")

    if scan_type == "MRI":
        if re.search(r"\bT1[\-\s]?weighted|T1W\b", text, re.IGNORECASE):
            modality_parts.append("T1-weighted")
        if re.search(r"\bT2[\-\s]?weighted|T2W\b", text, re.IGNORECASE):
            modality_parts.append("T2-weighted")
        if re.search(r"\bFLAIR\b", text, re.IGNORECASE):
            modality_parts.append("FLAIR")
        if re.search(r"\bDWI|diffusion\b", text, re.IGNORECASE):
            modality_parts.append("DWI")
    elif scan_type == "CT":
        if re.search(r"\bHRCT\b", text, re.IGNORECASE):
            modality_parts.append("high-resolution")
    elif scan_type == "Ultrasound":
        if re.search(r"\bdoppler\b", text, re.IGNORECASE):
            modality_parts.append("Doppler")

    return " / ".join(modality_parts) if modality_parts else scan_type


def _extract_unstructured(text: str) -> tuple[str, str]:
    """Extract findings from unstructured text by looking for key sentences."""
    sentences = re.split(r"[.\n]", text)
    finding_sentences = []
    impression_sentences = []

    for s in sentences:
        s = s.strip()
        if not s or len(s) < 10:
            continue
        if _ABNORMAL_KEYWORDS.search(s) or _NORMAL_KEYWORDS.search(s):
            finding_sentences.append(s)
        elif re.search(r"\b(?:suggest|correlat|advis|recommend|follow|review)\b", s, re.IGNORECASE):
            impression_sentences.append(s)

    return (
        ". ".join(finding_sentences[:8]),
        ". ".join(impression_sentences[:3]),
    )


def _parse_findings(text: str) -> list[ScanFinding]:
    """Parse individual findings from findings text."""
    if not text:
        return []

    findings: list[ScanFinding] = []
    # Split on bullet points, numbered items, or line breaks
    items = re.split(r"\n\s*[-•*\d.]+\s*|\n{2,}", text)

    for item in items:
        item = item.strip()
        if len(item) < 10:
            continue

        # Determine severity — check negation first
        has_negation = bool(re.search(
            r"\b(?:no|not|without|absent|negative|nil|none|unremarkable|normal)\b",
            item, re.IGNORECASE,
        ))
        has_abnormal = bool(_ABNORMAL_KEYWORDS.search(item))
        has_normal = bool(_NORMAL_KEYWORDS.search(item))

        if has_abnormal and not has_negation:
            critical_words = re.search(
                r"\b(?:fracture|mass|tumor|tumour|malignant|metastas|hemorrhage|haemorrhage|"
                r"infarct|thrombus|thrombosis|embolism|aneurysm|perforation|necrosis)\b",
                item, re.IGNORECASE,
            )
            severity = "critical" if critical_words else "warning"
            conf = 0.85 if critical_words else 0.75
        elif has_normal or has_negation:
            severity = "info"
            conf = 0.80
        else:
            severity = "info"
            conf = 0.60

        findings.append(ScanFinding(finding=item[:300], severity=severity, confidence=conf))

    # Limit to most significant findings
    findings.sort(key=lambda f: {"critical": 0, "warning": 1, "info": 2}.get(f.severity, 3))
    return findings[:12]


def _build_auto_impression(findings: list[ScanFinding], is_abnormal: bool) -> str:
    """Build an auto-generated impression when the report doesn't have one."""
    if not findings:
        return "No significant findings extracted."

    critical = [f for f in findings if f.severity == "critical"]
    warnings = [f for f in findings if f.severity == "warning"]

    if critical:
        return f"Significant abnormalities detected: {len(critical)} critical finding(s). Clinical correlation advised."
    elif warnings:
        return f"Abnormalities noted: {len(warnings)} finding(s) requiring attention."
    elif is_abnormal:
        return "Minor abnormalities detected. Clinical correlation recommended."
    else:
        return "Study appears within normal limits."


def _compute_confidence(text: str, findings_text: str, impression_text: str, scan_type: str) -> float:
    """Compute overall confidence in the scan analysis."""
    score = 0.3  # base

    # Bonus for structured report sections
    if findings_text:
        score += 0.25
    if impression_text:
        score += 0.15

    # Bonus for identified scan type
    if scan_type != "Unknown":
        score += 0.15

    # Bonus for text length (more text = more info)
    if len(text) > 500:
        score += 0.1
    if len(text) > 1500:
        score += 0.05

    return min(score, 0.98)


def _analyze_image_metadata(file_path: str) -> dict[str, Any] | None:
    """Extract basic metadata from a medical image file."""
    try:
        from PIL import Image
        p = Path(file_path)
        if p.suffix.lower() not in _SCAN_IMAGE_EXTENSIONS:
            return None
        with Image.open(p) as img:
            info: dict[str, Any] = {
                "format": img.format,
                "width": img.width,
                "height": img.height,
                "mode": img.mode,
                "is_grayscale": img.mode in ("L", "I", "F"),
            }
            # Check if high-resolution (typical of medical scans)
            if img.width >= 512 and img.height >= 512:
                info["is_high_res"] = True
            return info
    except Exception:
        return None
