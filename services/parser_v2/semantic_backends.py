from __future__ import annotations

import json
import logging
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from PIL import Image

from services.parser.app.config import settings

from .semantic_models import (
    SemanticFieldOutput,
    SemanticRegionOutput,
    SemanticSourceToken,
    SemanticTableOutput,
    SemanticTableRowOutput,
)

logger = logging.getLogger("parser-debug")


SEMANTIC_REGION_TYPES = {
    "patient_info",
    "hospitalization_info",
    "insurance_info",
    "diagnosis",
    "expense_table",
    "bill_table",
    "table",
    "generic_table",
    "medication_table",
    "lab_table",
    "vitals_table",
    "prescription",
    "text",
    "title",
    "paragraph",
}

SEMANTIC_TABLE_KINDS = {
    "expenses",
    "medications",
    "lab_results",
    "vitals",
    "diagnoses",
    "generic_table",
}


@dataclass
class SemanticRequest:
    region_id: str
    region_type: str
    page: int | None
    document_id: str | None
    claim_id: str | None
    text: str
    tokens: list[dict[str, Any]]
    table_cells: list[list[dict[str, Any]]] | None = None
    image: Image.Image | None = None
    bbox: list[float] | None = None


class SemanticBackend(ABC):
    name: str = "semantic-backend"

    @abstractmethod
    def available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def analyze(self, request: SemanticRequest) -> dict[str, Any] | None:
        raise NotImplementedError

    @staticmethod
    def _source_tokens(request: SemanticRequest) -> list[SemanticSourceToken]:
        return [SemanticSourceToken(**token) for token in request.tokens if isinstance(token, dict)]


class _TransformersSemanticBackend(SemanticBackend):
    model_name: str
    processor_name: str | None
    model_class_candidates: tuple[str, ...] = ()
    processor_class_candidates: tuple[str, ...] = ()

    def __init__(self, model_name: str | None = None, processor_name: str | None = None):
        self.model_name = model_name or getattr(self, "model_name", None)
        self.processor_name = processor_name or getattr(self, "processor_name", None) or self.model_name
        self._model = None
        self._processor = None
        self._device = "cpu"

    def available(self) -> bool:
        if not self.model_name:
            return False
        try:
            self._ensure_loaded()
            return self._model is not None and self._processor is not None
        except Exception as exc:
            logger.debug("%s unavailable: %s", self.name, exc)
            return False

    def _ensure_loaded(self) -> None:
        if self._model is not None and self._processor is not None:
            return

        if not self.model_name:
            raise RuntimeError("No model configured")

        try:
            import torch
            from transformers import AutoProcessor

            self._device = "cuda" if torch.cuda.is_available() else "cpu"
            self._processor = AutoProcessor.from_pretrained(self.processor_name)

            last_exc: Exception | None = None
            for class_name in self.model_class_candidates:
                try:
                    import transformers

                    model_cls = getattr(transformers, class_name, None)
                    if model_cls is None:
                        continue
                    self._model = model_cls.from_pretrained(self.model_name)
                    self._model.eval()
                    if self._device == "cuda":
                        self._model.to("cuda")
                    return
                except Exception as exc:  # pragma: no cover - backend availability is runtime specific
                    last_exc = exc
                    self._model = None
                    continue

            if last_exc:
                raise last_exc
            raise RuntimeError(f"No supported transformers model class found for {self.name}")
        except Exception as exc:
            raise RuntimeError(f"Unable to load {self.name}: {exc}") from exc

    def _build_prompt(self, request: SemanticRequest) -> str:
        return _build_semantic_prompt(request)

    def _decode_output(self, output: Any) -> str:
        if isinstance(output, str):
            return output
        if hasattr(output, "tolist"):
            return str(output.tolist())
        return str(output)

    def analyze(self, request: SemanticRequest) -> dict[str, Any] | None:
        self._ensure_loaded()
        prompt = self._build_prompt(request)

        try:
            import torch

            inputs_kwargs: dict[str, Any] = {"return_tensors": "pt"}
            if request.image is not None:
                inputs = self._processor(images=request.image, text=prompt, **inputs_kwargs)
            else:
                inputs = self._processor(text=prompt, **inputs_kwargs)

            if hasattr(inputs, "to"):
                inputs = inputs.to(self._device)
            elif isinstance(inputs, dict):
                inputs = {k: (v.to(self._device) if hasattr(v, "to") else v) for k, v in inputs.items()}

            with torch.inference_mode():
                generated = self._model.generate(**inputs, max_new_tokens=512)

            decoded = self._processor.batch_decode(generated, skip_special_tokens=True)[0]
            return _parse_semantic_response(decoded, request, self.name)
        except Exception as exc:
            logger.debug("%s analysis failed: %s", self.name, exc)
            return None


class Qwen2VLBackend(_TransformersSemanticBackend):
    name = "qwen2-vl"
    model_class_candidates = ("Qwen2VLForConditionalGeneration", "AutoModelForImageTextToText")
    processor_class_candidates = ("AutoProcessor",)


class Florence2Backend(_TransformersSemanticBackend):
    name = "florence-2"
    model_class_candidates = ("Florence2ForConditionalGeneration", "AutoModelForCausalLM")
    processor_class_candidates = ("AutoProcessor",)


class DonutBackend(_TransformersSemanticBackend):
    name = "donut"
    model_class_candidates = ("VisionEncoderDecoderModel",)
    processor_class_candidates = ("AutoProcessor",)


class LayoutLMv3Backend(SemanticBackend):
    name = "layoutlmv3"

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or settings.layoutlm_model
        self._available = bool(
            self.model_name
            and (
                os.path.exists(self.model_name)
                or os.getenv("PARSER_ENABLE_LAYOUTLM", "").lower() in {"1", "true", "yes"}
                or os.path.exists(os.path.join(os.getcwd(), self.model_name))
            )
        )

    def available(self) -> bool:
        return self._available

    def analyze(self, request: SemanticRequest) -> dict[str, Any] | None:
        # LayoutLMv3 is a strong token classifier when fine-tuned. In this repo we
        # use it as a region-level semantic signal, not as a regex substitute.
        # If a fine-tuned checkpoint is configured, we can let a local semantic LLM
        # interpret the region using LayoutLMv3-derived layout cues.
        if not self.available():
            return None
        return _layoutlm_region_summary(request, self.name)


class OllamaSemanticBackend(SemanticBackend):
    name = "ollama-semantic"

    def __init__(self, url: str | None = None, model: str | None = None, timeout_seconds: int | None = None):
        self.url = _resolve_ollama_url(url or settings.semantic_llm_url or settings.llm_url)
        self.model = model or settings.semantic_llm_model or _discover_ollama_model(self.url) or settings.llm_model or "qwen2.5:1.5b"
        self.timeout_seconds = timeout_seconds or settings.semantic_llm_timeout_seconds or settings.llm_timeout_seconds

    def available(self) -> bool:
        return bool(self.url and self.model)

    def analyze(self, request: SemanticRequest) -> dict[str, Any] | None:
        if not self.available():
            return None

        prompt = _build_semantic_prompt(request)
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }
        try:
            response = httpx.post(self.url, json=payload, timeout=self.timeout_seconds)
            response.raise_for_status()
            data = response.json()
            raw = data.get("response") if isinstance(data, dict) else None
            if not raw:
                return None
            return _parse_semantic_response(str(raw), request, self.name)
        except Exception as exc:
            logger.debug("Ollama semantic backend failed: %s", exc)
            return None


class OpenRouterBackend(SemanticBackend):
    """Backend that calls an OpenRouter-hosted model using a bearer API key.

    This is a lightweight adapter that expects `settings.openrouter_api_key` to
    contain a test key (user said they would place it directly in code for testing).
    """
    name = "openrouter"

    def __init__(self, url: str | None = None, model: str | None = None, timeout_seconds: int | None = None):
        self.url = url or settings.openrouter_url
        self.model = model or settings.openrouter_model
        self.api_key = getattr(settings, "openrouter_api_key", "") or os.getenv("OPENROUTER_API_KEY", "")
        self.timeout_seconds = timeout_seconds or getattr(settings, "semantic_llm_timeout_seconds", 120)

    def available(self) -> bool:
        return bool(self.url and self.model and self.api_key)

    def analyze(self, request: SemanticRequest) -> dict[str, Any] | None:
        if not self.available():
            return None

        prompt = _build_semantic_prompt(request)
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        # Use chat/completions format (compatible with openrouter.ai/api/v1/chat/completions)
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1024,
            "temperature": 0.7,
        }

        # Setup debug log file before calling the API so it always exists even if rate limited or network fails
        from datetime import datetime
        ts = datetime.utcnow().isoformat() + "Z"
        base = os.path.join(os.getcwd(), "tmp", "parser_debug", "llm_calls")
        os.makedirs(base, exist_ok=True)
        model_safe = (self.model or "model").replace("/", "_").replace("\\", "_").replace(":", "_")
        fname = f"{ts.replace(':', '-')}_openrouter_semantic_{model_safe}.json"
        path = os.path.join(base, fname)
        
        # Initial pending state
        body = {
            "timestamp": ts,
            "provider": "openrouter",
            "model": self.model,
            "region_id": request.region_id,
            "region_type": request.region_type,
            "page": request.page,
            "claim_id": request.claim_id,
            "prompt": prompt,
            "response": "PENDING / CALL IN PROGRESS",
            "response_parsed": None,
        }
        
        def _write_debug(data_dict: dict):
            try:
                tmp_path = path + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data_dict, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, path)
            except Exception as e:
                logger.debug("Failed to write semantic debug file: %s", e)

        # Write initial call state containing the input prompt
        _write_debug(body)

        try:
            response = httpx.post(self.url, json=payload, headers=headers, timeout=self.timeout_seconds)
            
            if response.status_code != 200:
                err_msg = f"HTTP {response.status_code}: {response.text}"
                body["response"] = err_msg
                _write_debug(body)
                response.raise_for_status()

            data = response.json()

            # Chat/completions response format: {"choices": [{"message": {"content": "..."}}]}
            raw = None
            if isinstance(data, dict) and "choices" in data and isinstance(data["choices"], list) and data["choices"]:
                choice = data["choices"][0]
                message = choice.get("message")
                if isinstance(message, dict):
                    raw = message.get("content")
                else:
                    raw = message

            if not raw:
                logger.debug(f"OpenRouter response had no content: {data}")
                body["response"] = f"ERROR: Response had no content. Data: {json.dumps(data)}"
                _write_debug(body)
                return None

            raw_text = str(raw) if raw else ""
            body["response"] = raw_text

            # Attempt to parse response text into a clean JSON object for readability
            parsed_json = None
            try:
                cleaned_text = _strip_json_code_fences(raw_text)
                start = cleaned_text.find("{")
                end = cleaned_text.rfind("}")
                if start >= 0 and end >= 0 and end > start:
                    parsed_json = json.loads(cleaned_text[start : end + 1])
            except Exception:
                pass

            body["response_parsed"] = parsed_json
            _write_debug(body)
            logger.info("Persisted OpenRouter semantic call to %s", path)

            return _parse_semantic_response(raw_text, request, self.name)
        except Exception as exc:
            logger.debug("OpenRouter backend failed: %s", exc)
            body["response"] = f"ERROR: {str(exc)}"
            _write_debug(body)
            return None


class SemanticBackendRegistry:
    def __init__(self) -> None:
        backend_order = [part.strip().lower() for part in (settings.semantic_backend_order or "").split(",") if part.strip()]
        if not backend_order:
            # OpenRouter is the primary backend; local vision models are optional fallbacks.
            backend_order = ["openrouter", "qwen2-vl", "layoutlmv3", "florence-2", "donut"]

        self.backends: list[SemanticBackend] = []
        for backend_name in backend_order:
            backend = self._create_backend(backend_name)
            if backend is not None:
                self.backends.append(backend)

    def _create_backend(self, backend_name: str) -> SemanticBackend | None:
        if backend_name == "qwen2-vl":
            model_name = settings.qwen2_vl_model or os.getenv("PARSER_QWEN2_VL_MODEL", "")
            return Qwen2VLBackend(model_name=model_name) if model_name else Qwen2VLBackend(model_name="")
        if backend_name == "layoutlmv3":
            return LayoutLMv3Backend(model_name=settings.layoutlm_model)
        if backend_name == "florence-2":
            model_name = settings.florence2_model or os.getenv("PARSER_FLORENCE2_MODEL", "")
            return Florence2Backend(model_name=model_name) if model_name else Florence2Backend(model_name="")
        if backend_name == "donut":
            model_name = settings.donut_model or os.getenv("PARSER_DONUT_MODEL", "")
            return DonutBackend(model_name=model_name) if model_name else DonutBackend(model_name="")
        if backend_name in {"ollama", "local-llm", "semantic-llm"}:
            return OllamaSemanticBackend()
        if backend_name in {"openrouter", "open-router"}:
            return OpenRouterBackend()
        return None

    def choose(self) -> SemanticBackend | None:
        for backend in self.backends:
            try:
                if backend.available():
                    logger.info("Semantic backend selected: %s", getattr(backend, "name", backend.__class__.__name__))
                    return backend
            except Exception:
                continue

        backend_names = [getattr(backend, "name", backend.__class__.__name__) for backend in self.backends]
        logger.warning(
            "No semantic backend available; tried=%s. Semantic table extraction will fall back to geometry and heuristics.",
            backend_names,
        )
        return None


def _text_only_request(request: SemanticRequest) -> str:
    return request.text[: max(1000, settings.semantic_prompt_max_chars)]


def _build_semantic_prompt(request: SemanticRequest) -> str:
    region_type = request.region_type.lower()
    # Prefer a compact table preview: headers / first few rows to reduce noise,
    # but keep enough context for multi-row billing tables.
    text = _text_only_request(request)
    table_rows = []
    max_rows = 150
    for row_index, row in enumerate((request.table_cells or [])[:max_rows]):
        cells = [(cell.get("text") or "").strip() for cell in row if (cell.get("text") or "").strip()]
        if cells:
            table_rows.append(f"row {row_index + 1}: " + " | ".join(cells))
    table_hint = "\n".join(table_rows)

    return f"""
You are a medical document understanding system.
Analyze only this isolated region from a larger claim document.

Return STRICT JSON only with this shape:
{{
  "region_type": "patient_info|hospitalization_info|insurance_info|diagnosis|expense_table|medication_table|lab_table|vitals_table|prescription|other",
  "table_kind": "expenses|medications|lab_results|vitals|diagnoses|generic_table",
  "confidence": 0.0,
  "notes": "",
  "fields": [
    {{
      "canonical_field": "patient_name",
      "value": "",
      "confidence": 0.0
    }}
  ],
  "tables": [
    {{
      "table_kind": "expenses",
      "headers": ["category", "description", "amount"],
      "rows": [
        {{"category": "", "description": "", "amount": ""}}
      ],
      "confidence": 0.0
    }}
  ]
}}

Do not extract or infer patient, hospital, insurance, or diagnosis fields in this backend.
This backend is for expense-table normalization only.

EXPENSE TABLE EXTRACTION (CRITICAL):
EXPENSE tables contain actual medical/hospital charges like: ICU, Room, Surgery, Pharmacy, Lab, Radiology, Nursing, Consultations, Medications, Tests, Equipment, Supplies, etc.

When the table includes headers such as description, qty, rate, gross, net payable, or total, use the item rows underneath the header and ignore the header row itself.

Return every unique bill line item visible in the region. Do not collapse the table to only the total or summary rows.

NEVER classify as expense_table if it contains:
- "Claims" (insurance claim counts)
- "Claim vs Sum Insured" (insurance comparison)
- "Policy", "Payer", "Premium", "Deductible" (insurance terms)
- "Risk Factor", "Previous Claims" (insurance metadata)
These should be classified as "generic_table" or "insurance_info" instead.

If this IS an expense/billing table (any format), ALWAYS:
1. Understand the table structure - may be: daily charges, itemized expenses, category-wise breakdown, or mixed format
2. Extract EACH UNIQUE medical expense as a separate row with: category, description, amount
3. For multi-day charges (e.g., "ICU - 5 Days @ Rs. 15,000/day"):
    - TOTAL: Calculate qty × unit_price = total amount (e.g., 5 × 15000 = 75000)
    - RETURN: One row with category="ICU", description="ICU - 5 Days @ Rs. 15,000/day", amount="75000"
4. For itemized tables: Extract each line item as-is
5. REMOVE DUPLICATES: If same expense appears multiple times, keep only ONE with highest amount
6. Do NOT include: summary rows, total rows, grand totals, headers, metadata, or insurance information
7. Preserve exact amounts - do NOT modify, truncate, or divide amounts
8. Return amounts as numeric values without currency symbols
9. If a row has multiple numeric columns (e.g., Qty, Rate, Gross, NP/Non-Payable, Payable), ALWAYS select the value from the absolute final column (Payable/Amount) as the amount, never the earlier Gross or NP/Non-Payable columns. If there is only one numeric column, select that as the amount.

CRITICAL EXCLUSION - NEVER extract these as expense rows, even if they have a numeric amount:
- "Gross Hospital Bill" / "Gross Bill" / "Gross Amount" — this is the document-level billing total, NOT a charge
- "Less: Deductible / Excess" / "Deductible" — this is an insurance deduction calculation, NOT a medical service
- "Less: Non-Payable (NP) Items" / "Non-Payable Deductions" — this is an insurance deduction, NOT a medical service
- "Non-Payable Items", "NP Items" — insurance adjustment rows, NOT medical services
- "Final Amount Admissible" / "Amount Admissible" / "Admissible Amount" — insurance settlement figure, NOT a charge
- "Net Payable" / "Net Amount Payable" — final settlement total, NOT a charge
- "Patient Share" / "Co-Pay" / "Co Pay" — patient responsibility portion, NOT a new charge
- "Balance Amount" / "Balance Payable" — residual amount, NOT a charge
- "Ward: General Ward LOS: N" — this is patient stay metadata (length of stay), NOT a charge
- "Managed in General Ward for N days" — stay description metadata, NOT a charge
- Any row whose description starts with "Less:" — all "Less:" rows are deduction calculations.

Extraction Guidance:
- ALWAYS extract age and gender if visible, even if region seems to be "lab_results"
- ALWAYS extract doctor_name/treating_doctor and diagnosis if visible
- Never return regex explanations or metadata
- Prefer semantic interpretation over keyword matching
- If this is a table, classify by meaning: expenses, medications, lab results, vitals, or diagnoses
- If this is a form/summary block, extract canonical fields
- Preserve medically relevant values exactly as shown
- Do not invent data

Region type hint: {region_type}
Tabular hint (if present):
{table_hint}
Document text (truncated):
{text}
""".strip()


def _layoutlm_region_summary(request: SemanticRequest, model_name: str) -> dict[str, Any]:
    # Region summarization when a dedicated LayoutLMv3 checkpoint exists. We don't
    # assume a fine-tuned label set here; instead we expose a semantic request that
    # downstream code can use for provenance and debug output.
    text = request.text[: max(1000, settings.semantic_prompt_max_chars)]
    return {
        "region_type": request.region_type,
        "table_kind": "generic_table" if request.table_cells else "other",
        "confidence": 0.45,
        "notes": f"LayoutLMv3 backend placeholder for region summarization: {text[:120]}",
        "fields": [],
        "tables": [],
        "model_name": model_name,
    }


def _resolve_ollama_url(candidate: str | None) -> str:
    urls = [candidate, "http://localhost:11434/api/generate", "http://127.0.0.1:11434/api/generate"]
    for url in urls:
        if not url:
            continue
        try:
            tags_url = url.replace("/api/generate", "/api/tags")
            response = httpx.get(tags_url, timeout=3)
            if response.status_code == 200:
                return url
        except Exception:
            continue
    return candidate or "http://localhost:11434/api/generate"


def _discover_ollama_model(url: str | None) -> str | None:
    if not url:
        return None
    try:
        tags_url = url.replace("/api/generate", "/api/tags")
        response = httpx.get(tags_url, timeout=5)
        response.raise_for_status()
        payload = response.json()
        models = payload.get("models", []) if isinstance(payload, dict) else []
        if not models:
            return None
        preferred_names = ["qwen2.5:1.5b", "qwen2.5", "llama3.2", "llama3", "mistral", "phi3"]
        available_names = [str(m.get("name") or m.get("model") or "") for m in models if isinstance(m, dict)]
        for preferred in preferred_names:
            for name in available_names:
                if preferred in name:
                    return name
        return available_names[0] if available_names else None
    except Exception:
        return None


def _strip_json_code_fences(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    return cleaned


def _parse_semantic_response(raw_text: str, request: SemanticRequest, model_name: str) -> dict[str, Any] | None:
    cleaned = _strip_json_code_fences(raw_text)
    if not cleaned:
        return None

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < 0 or end <= start:
        return None

    cleaned = cleaned[start : end + 1]
    try:
        data = json.loads(cleaned)
    except Exception:
        return None

    fields: list[SemanticFieldOutput] = []
    for field_item in data.get("fields", []) or []:
        if not isinstance(field_item, dict):
            continue
        canonical_field = str(field_item.get("canonical_field") or "").strip()
        value = str(field_item.get("value") or "").strip()
        if not canonical_field or not value:
            continue
        fields.append(SemanticFieldOutput(
            canonical_field=canonical_field,
            value=value,
            confidence=float(field_item.get("confidence") or data.get("confidence") or 0.0),
            source_region_id=request.region_id,
            source_region_type=request.region_type,
            source_tokens=SemanticBackend._source_tokens(request),
            model_name=model_name,
            extractor_name=model_name,
            metadata={"raw": field_item},
        ))

    tables: list[SemanticTableOutput] = []
    for table_item in data.get("tables", []) or []:
        if not isinstance(table_item, dict):
            continue
        table_kind = str(table_item.get("table_kind") or data.get("table_kind") or "generic_table").strip()
        rows: list[SemanticTableRowOutput] = []
        for row_index, row_item in enumerate(table_item.get("rows", []) or []):
            if isinstance(row_item, dict):
                rows.append(SemanticTableRowOutput(
                    row_index=row_index,
                    row_type=str(row_item.get("row_type") or "").strip() or None,
                    cells={k: v for k, v in row_item.items() if k not in {"row_type"}},
                    confidence=float(row_item.get("confidence") or table_item.get("confidence") or data.get("confidence") or 0.0),
                ))
            else:
                rows.append(SemanticTableRowOutput(row_index=row_index, cells={"value": row_item}))

        tables.append(SemanticTableOutput(
            table_kind=table_kind,
            confidence=float(table_item.get("confidence") or data.get("confidence") or 0.0),
            source_region_id=request.region_id,
            source_region_type=request.region_type,
            source_tokens=SemanticBackend._source_tokens(request),
            headers=[str(h) for h in table_item.get("headers", []) if str(h).strip()],
            rows=rows,
            model_name=model_name,
            metadata={"raw": table_item},
        ))

    return {
        "region_id": request.region_id,
        "region_type": str(data.get("region_type") or request.region_type).strip(),
        "semantic_type": str(data.get("region_type") or request.region_type).strip(),
        "confidence": float(data.get("confidence") or 0.0),
        "source_page": request.page,
        "document_id": request.document_id,
        "claim_id": request.claim_id,
        "source_tokens": [token.model_dump() for token in SemanticBackend._source_tokens(request)],
        "fields": [field.model_dump() for field in fields],
        "tables": [table.model_dump() for table in tables],
        "model_name": model_name,
        "notes": data.get("notes"),
        "metadata": data,
    }
