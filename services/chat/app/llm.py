"""
LLM integration layer  --  RAG-powered ClaimGPT brain.

Architecture:
  1. **RAG context builder** — gathers all claim data (OCR text, parsed fields,
     ICD/CPT codes, predictions, validations, document sections) into a rich
     structured context injected as system prompt.
  2. **Ollama LLM** — calls local Ollama server (Llama 3.2, etc.) with full
     claim context for deep reasoning.
  3. **Local assistant fallback** — comprehensive rule-based conversational engine
     that responds naturally using claim data when LLM is unavailable.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from .config import settings

logger = logging.getLogger("chat.llm")

TIMEOUT = httpx.Timeout(60.0, connect=5.0)

# ------------------------------------------------------------------ PHI scrubber

_PHI_PATTERNS = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN_REDACTED]"),
    (re.compile(r"\b\d{9}\b"), "[ID_REDACTED]"),
    (re.compile(r"\b[A-Z]{2}\d{7,10}\b"), "[POLICY_REDACTED]"),
]


def scrub_phi(text: str) -> str:
    for pat, repl in _PHI_PATTERNS:
        text = pat.sub(repl, text)
    return text


# ------------------------------------------------------------------ RAG context builder

def _build_rag_context(claim_context: dict[str, Any]) -> str:
    """Build a rich RAG context string from all claim data sources.
    Uses full OCR text and question-relevant chunks — no arbitrary truncation."""
    parts: list[str] = []

    parts.append("=== CLAIM DATA (Retrieved from ClaimGPT database) ===\n")

    claim_id = claim_context.get("claim_id", "unknown")
    status = claim_context.get("status", "UNKNOWN")
    parts.append(f"Claim ID: {claim_id}")
    parts.append(f"Status: {status}")
    if claim_context.get("policy_id"):
        parts.append(f"Policy ID: {claim_context['policy_id']}")

    page_count = claim_context.get("ocr_page_count", 0)
    if page_count:
        parts.append(f"Document Pages: {page_count}")

    # Parsed fields
    fields = claim_context.get("parsed_fields", {})
    if fields:
        parts.append("\n--- EXTRACTED FIELDS ---")
        for k, v in fields.items():
            parts.append(f"  {k}: {v}")

    # Medical entities (NER)
    entities = claim_context.get("medical_entities", [])
    if entities:
        by_type: dict[str, list[str]] = {}
        for e in entities:
            t = e.get("type", "OTHER")
            by_type.setdefault(t, []).append(e.get("text", ""))
        parts.append("\n--- MEDICAL ENTITIES (NER extracted) ---")
        for etype, texts in by_type.items():
            unique = list(dict.fromkeys(texts))  # deduplicate preserving order
            parts.append(f"  {etype}: {', '.join(unique[:20])}")

    # Medical codes
    codes = claim_context.get("medical_codes", [])
    icd = [c for c in codes if c.get("code_type") in ("ICD-10", "ICD10")]
    cpt = [c for c in codes if c.get("code_type") == "CPT"]
    if icd:
        parts.append("\n--- ICD-10 CODES (Diagnosis) ---")
        for c in icd:
            conf = f" (confidence: {c['confidence']:.0%})" if c.get("confidence") else ""
            parts.append(f"  {c['code']} - {c.get('description', 'N/A')}{conf}")
    if cpt:
        parts.append("\n--- CPT CODES (Procedures) ---")
        for c in cpt:
            conf = f" (confidence: {c['confidence']:.0%})" if c.get("confidence") else ""
            parts.append(f"  {c['code']} - {c.get('description', 'N/A')}{conf}")

    # Predictions
    preds = claim_context.get("predictions", [])
    if preds:
        parts.append("\n--- RISK PREDICTION ---")
        for p in preds:
            parts.append(f"  Rejection Score: {p.get('rejection_score', 'N/A')}")
            parts.append(f"  Model: {p.get('model_name', 'N/A')}")
            reasons = p.get("top_reasons", [])
            if reasons:
                parts.append("  Risk Factors:")
                for r in (reasons if isinstance(reasons, list) else [reasons]):
                    parts.append(f"    - {r}")

    # Validations
    vals = claim_context.get("validations", [])
    if vals:
        passed = sum(1 for v in vals if v.get("passed"))
        parts.append(f"\n--- VALIDATION RESULTS ({passed}/{len(vals)} passed) ---")
        for v in vals:
            status_icon = "PASS" if v.get("passed") else "FAIL"
            parts.append(f"  [{status_icon}] {v.get('rule_name', v.get('rule_id', 'Rule'))}: {v.get('message', '')}")

    # Document text — question-relevant chunks (already filtered by _search_ocr_for_query)
    relevant = claim_context.get("relevant_text", "")
    if relevant:
        parts.append(f"\n--- FULL DOCUMENT TEXT (from OCR — {page_count} pages) ---\n{relevant}")

    return "\n".join(parts)


# ------------------------------------------------------------------ system prompt

def build_system_prompt(claim_context: dict[str, Any] | None) -> str:
    base = (
        "You are ClaimGPT, an expert AI assistant for medical insurance claims processing. "
        "You combine deep medical coding knowledge (ICD-10-CM, CPT, HCPCS) with insurance billing "
        "expertise, TPA submission workflows, and claim adjudication intelligence.\n\n"

        "## Your Personality\n"
        "You are warm, conversational, and proactive — like a knowledgeable colleague who genuinely "
        "wants to help. You explain complex medical and billing concepts in plain language, "
        "but you're precise when it matters (codes, amounts, dates).\n\n"

        "## Response Guidelines\n"
        "- **Be interactive**: Ask clarifying questions when the query is ambiguous. "
        "Offer to dive deeper into specific areas. End responses with a relevant follow-up.\n"
        "- **Use rich formatting**: Markdown bold, bullets, tables, code blocks for codes. "
        "Use emojis sparingly (📋 🏥 💰 ⚠️ ✅ 🔬) for visual scanning.\n"
        "- **Be thorough but scannable**: Use headers and bullet points. Lead with the key insight, "
        "then provide supporting detail.\n"
        "- **Always show your reasoning**: When analyzing claims, explain WHY something is a risk, "
        "not just that it is one. Connect codes to diagnoses to treatments.\n"
        "- **Proactive insights**: If you spot issues (code mismatches, missing fields, high risk), "
        "flag them immediately with specific recommendations.\n"
        "- **Cross-reference data**: Connect ICD codes to procedures, link billing to diagnosis, "
        "check if the amounts make sense for the treatment.\n"
        "- **Comparison context**: When relevant, mention typical ranges (\"Room charges of ₹X are "
        "typical for a Y-day stay\", \"This rejection risk is higher than average\").\n"
        "- **Never reveal raw PHI** — refer to patients by claim ID only.\n"
        "- **End with a question or suggestion** to keep the conversation flowing.\n\n"

        "## Expertise Areas\n"
        "- ICD-10-CM diagnosis coding (70,000+ codes)\n"
        "- CPT procedure coding and modifiers\n"
        "- Medical necessity and clinical documentation\n"
        "- Insurance claim lifecycle (submission → adjudication → payment/denial)\n"
        "- Pre-authorization and concurrent review\n"
        "- Denial management and appeal strategies\n"
        "- TPA workflows and payer-specific requirements\n"
        "- Fraud/waste/abuse detection patterns\n"
        "- Indian insurance regulations (IRDAI) and common TPAs\n\n"

        "## Data Editing Capability\n"
        "Users can add, update, or delete claim fields through chat. When a user mentions "
        "a field is missing, wrong, or needs to change, acknowledge the change and confirm it. "
        "Examples:\n"
        "- 'Patient name is missing, it should be Rahul Sharma' → Confirm you'll add patient_name\n"
        "- 'Change the diagnosis to Type 2 Diabetes' → Confirm the update\n"
        "- 'Remove the policy id' → Confirm the deletion\n"
        "- 'Hospital name is wrong, it should be Apollo Hospital' → Confirm the correction\n"
        "When the user provides field data, respond confirming what will be changed "
        "and tell the user to click the action button to apply it.\n"
    )

    if not claim_context:
        return base + (
            "\n## Current State\n"
            "No specific claim is selected. Help the user understand ClaimGPT's capabilities "
            "and guide them to upload a document or select a claim. Be enthusiastic and show "
            "what you can do with example interactions."
        )

    rag_context = _build_rag_context(claim_context)
    return f"{base}\n## Active Claim Data\n{rag_context}\n\nUse ALL the above data to give precise, data-driven answers. Cross-reference fields when relevant."


# ------------------------------------------------------------------ LLM provider (Ollama)


def _call_ollama(system_prompt: str, messages: list[dict[str, str]]) -> str:
    """Call Ollama local server (supports meditron, medllama2, llama3, etc.)."""
    chat_messages = [{"role": "system", "content": system_prompt}]
    for m in messages:
        chat_messages.append({"role": m["role"], "content": scrub_phi(m["content"])})

    with httpx.Client() as client:
        resp = client.post(
            f"{settings.ollama_base_url}/api/chat",
            json={
                "model": settings.ollama_model,
                "messages": chat_messages,
                "stream": False,
                "options": {"temperature": 0.7, "num_predict": settings.llm_max_tokens},
            },
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"]


# ------------------------------------------------------------------ unified LLM call


def call_llm(
    messages: list[dict[str, str]],
    claim_context: dict[str, Any] | None = None,
) -> str:
    system_prompt = build_system_prompt(claim_context)

    try:
        logger.info("Calling Ollama LLM")
        return _call_ollama(system_prompt, messages)
    except Exception as exc:
        logger.info("Ollama failed (%s) — using local assistant", exc)
        return _local_assistant(messages, claim_context)


# ------------------------------------------------------------------ streaming LLM calls

import json as _json


async def stream_llm(
    messages: list[dict[str, str]],
    claim_context: dict[str, Any] | None = None,
):
    """
    Async generator that yields SSE-formatted chunks from the LLM.
    Falls back to yielding the full local assistant response in one chunk.
    """
    system_prompt = build_system_prompt(claim_context)

    try:
        async for chunk in _stream_ollama(system_prompt, messages):
            yield f"data: {_json.dumps({'content': chunk})}\n\n"
        yield "data: [DONE]\n\n"
    except Exception as exc:
        logger.info("Ollama stream failed (%s) — falling back", exc)
        text = _local_assistant(messages, claim_context)
        yield f"data: {_json.dumps({'content': text})}\n\n"
        yield "data: [DONE]\n\n"


async def _stream_ollama(system_prompt: str, messages: list[dict[str, str]]):
    """Stream from local Ollama server (Llama 3.2, etc.)."""
    import httpx as _httpx
    chat_messages = [{"role": "system", "content": system_prompt}]
    for m in messages:
        chat_messages.append({"role": m["role"], "content": scrub_phi(m["content"])})

    async with _httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            f"{settings.ollama_base_url}/api/chat",
            json={
                "model": settings.ollama_model,
                "messages": chat_messages,
                "stream": True,
                "options": {"temperature": 0.7, "num_predict": settings.llm_max_tokens},
            },
            timeout=TIMEOUT.as_dict(),
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    data = _json.loads(line)
                    content = data.get("message", {}).get("content", "")
                    if content:
                        yield content
                    if data.get("done"):
                        break
                except _json.JSONDecodeError:
                    continue





# ------------------------------------------------------------------ conversational assistant

def _local_assistant(
    messages: list[dict[str, str]],
    claim_context: dict[str, Any] | None = None,
) -> str:
    """
    Conversational assistant that understands claim data and responds
    naturally like ChatGPT — warm, detailed, and helpful.
    """
    # Build conversation history for context
    history = []
    last_user = ""
    for m in messages:
        role = m.get("role", "").lower()
        content = m.get("content", "").strip()
        if role == "user":
            history.append(("user", content))
            last_user = content.lower()
        elif role == "assistant":
            history.append(("assistant", content))

    if not last_user:
        return (
            "Hey there! 👋 I'm ClaimGPT, your AI-powered claims assistant. "
            "I can help you with everything from uploading and reviewing claim documents "
            "to understanding ICD-10/CPT codes, checking rejection risk scores, and "
            "generating TPA-ready PDFs.\n\n"
            "Go ahead and upload a document on the left, or just ask me anything!"
        )

    if claim_context:
        return _conversational_with_context(last_user, claim_context, history)

    return _conversational_general(last_user, history)


def _conversational_with_context(query: str, ctx: dict[str, Any], history: list) -> str:
    """Natural conversational response using claim data."""
    claim_id = ctx.get("claim_id", "unknown")[:8]
    status = ctx.get("status", "UNKNOWN")
    policy_id = ctx.get("policy_id")
    fields = ctx.get("parsed_fields", {})
    full_ocr = ctx.get("full_ocr_text", "")
    relevant_text = ctx.get("relevant_text", "")
    page_count = ctx.get("ocr_page_count", 0)
    predictions = ctx.get("predictions", [])
    validations = ctx.get("validations", [])
    codes = ctx.get("medical_codes", [])
    entities = ctx.get("medical_entities", [])

    icd_codes = [c for c in codes if c.get("code_type") in ("ICD-10", "ICD10")] if codes else []
    cpt_codes = [c for c in codes if c.get("code_type") in ("CPT",)] if codes else []

    patient_name = fields.get("patient_name") or fields.get("member_name") or "the patient"
    provider = fields.get("provider_name") or fields.get("rendering_provider") or fields.get("hospital") or "the provider"

    # ── Greeting with claim context
    if _matches(query, ["hello", "hi", "hey", "good morning", "good afternoon", "good evening"]):
        return (
            f"Hi! 👋 I'm currently looking at claim **{claim_id}** (status: {status}). "
            f"This claim is for {patient_name}.\n\n"
            "Feel free to ask me anything — like \"What's the diagnosis?\", "
            "\"Show me the billing details\", or \"What's the rejection risk?\" "
            "I'm here to help!"
        )

    # ── Thorough summary / review / overview / tell me about / what is this
    if _matches(query, ["summary", "summarize", "overview", "review", "tell me about",
                        "what is this", "details", "look at", "check", "explain", "describe",
                        "show me everything", "full report", "what do you see"]):
        parts = [f"Great question! Here's a comprehensive overview of claim **{claim_id}**:\n"]

        parts.append(f"📋 **Status:** {status}")
        if policy_id:
            parts.append(f"📄 **Policy:** {policy_id}")
        parts.append(f"👤 **Patient:** {patient_name}")
        parts.append(f"🏥 **Provider:** {provider}")

        # Key fields
        service_date = fields.get("service_date") or fields.get("admission_date")
        discharge = fields.get("discharge_date")
        if service_date:
            date_str = f"**Date:** {service_date}"
            if discharge:
                date_str += f" → {discharge}"
            parts.append(f"📅 {date_str}")

        diag = fields.get("primary_diagnosis") or fields.get("diagnosis")
        if diag:
            parts.append(f"\n🔬 **Primary Diagnosis:** {diag}")

        if icd_codes:
            parts.append("\n**ICD-10 Codes:**")
            for c in icd_codes[:5]:
                parts.append(f"  • `{c.get('code', '?')}` — {c.get('description', 'N/A')}")

        proc = fields.get("procedure") or fields.get("service_description")
        if proc:
            parts.append(f"\n🔧 **Procedure:** {proc}")

        if cpt_codes:
            parts.append("\n**CPT Codes:**")
            for c in cpt_codes[:5]:
                parts.append(f"  • `{c.get('code', '?')}` — {c.get('description', 'N/A')}")

        amount = fields.get("total_amount") or fields.get("amount") or fields.get("billed_amount")
        if amount:
            parts.append(f"\n💰 **Billed Amount:** ₹{amount}")

        if predictions:
            p = predictions[0]
            score = p.get("rejection_score", p.get("score", "N/A"))
            risk_label = _risk_label(score)
            parts.append(f"\n⚠️ **Rejection Risk:** {score} ({risk_label})")

        if validations:
            passed = sum(1 for v in validations if v.get("passed"))
            failed = len(validations) - passed
            parts.append(f"\n✅ **Validation:** {passed} passed, {failed} failed")

        if not fields and not codes:
            if full_ocr:
                preview = full_ocr[:600]
                parts.append(f"\n📄 I've read the full document ({page_count} pages). Here's a snippet:\n> \"{preview}...\"")
                parts.append("\nThe document hasn't been fully processed through the pipeline yet. "
                            "Once it's processed, I'll have detailed diagnosis codes, procedures, and billing info.")
            else:
                parts.append("\nThe document hasn't been processed yet. The workflow pipeline will extract "
                            "all the medical details automatically.")

        if entities:
            diag_ents = [e["text"] for e in entities if e.get("type") == "DIAGNOSIS"]
            proc_ents = [e["text"] for e in entities if e.get("type") == "PROCEDURE"]
            med_ents = [e["text"] for e in entities if e.get("type") == "MEDICATION"]
            if diag_ents:
                parts.append(f"\n🔬 **Detected Conditions:** {', '.join(dict.fromkeys(diag_ents))}")
            if proc_ents:
                parts.append(f"🔧 **Detected Procedures:** {', '.join(dict.fromkeys(proc_ents))}")
            if med_ents:
                parts.append(f"💊 **Medications:** {', '.join(dict.fromkeys(med_ents))}")

        if page_count:
            parts.append(f"\n📖 Document has **{page_count} pages** — I've read every word.")

        parts.append("\n---\nFeel free to ask about specifics — diagnosis, billing, risk score, or anything else!")
        return "\n".join(parts)

    # ── Status
    if _matches(query, ["status", "where", "progress", "stage", "state", "what stage"]):
        status_map = {
            "UPLOADED": "just been uploaded and is queued for processing",
            "PROCESSING": "currently being processed through our AI pipeline (OCR → Parsing → Coding → Prediction → Validation)",
            "COMPLETED": "been fully processed! All data has been extracted and analyzed",
            "WORKFLOW_FAILED": "encountered an error during processing. You might want to try re-uploading",
            "SUBMITTED": "been submitted to the TPA/payer for review",
        }
        desc = status_map.get(status, f"in status: {status}")
        return (
            f"Claim **{claim_id}** has {desc}.\n\n"
            "Our processing pipeline goes through these stages:\n"
            "1. **Upload** → 2. **OCR** (text extraction) → 3. **Parse** (field extraction) → "
            "4. **Code** (ICD-10/CPT mapping) → 5. **Predict** (risk scoring) → "
            "6. **Validate** (rule checks) → 7. **Generate TPA PDF**\n\n"
            "Want me to dive into any specific stage?"
        )

    # ── Diagnosis / ICD
    if _matches(query, ["diagnosis", "diagnos", "icd", "condition", "disease", "ailment", "illness",
                        "what wrong", "medical condition"]):
        parts = []
        diag = fields.get("primary_diagnosis") or fields.get("diagnosis")
        if diag:
            parts.append(f"The primary diagnosis for this claim is **{diag}**.")

        if icd_codes:
            parts.append(f"\nI found {len(icd_codes)} ICD-10 code(s) mapped to this claim:\n")
            for c in icd_codes[:8]:
                conf = c.get("confidence")
                conf_str = f" (confidence: {conf:.0%})" if isinstance(conf, (int, float)) else ""
                parts.append(f"  • **`{c.get('code', '?')}`** — {c.get('description', 'N/A')}{conf_str}")
            parts.append("\nThese codes were automatically extracted from the medical documents "
                        "using our NLP engine (scispaCy + medical knowledge base).")
        elif diag:
            parts.append("The coding pipeline hasn't assigned specific ICD-10 codes yet. "
                        "Once the workflow completes, you'll see the mapped codes here.")
        else:
            # Search the document text for diagnosis info
            if relevant_text:
                answer = _search_document_for_answer(query, relevant_text, fields, entities)
                if answer:
                    return answer
            parts.append("I haven't found any diagnosis information in the structured fields yet. "
                        "The document may contain this info — try asking more specifically.")

        return "\n".join(parts) if parts else "No diagnosis information available yet."

    # ── Procedure / CPT
    if _matches(query, ["procedure", "cpt", "treatment", "surgery", "service",
                        "what was done", "operation"]):
        parts = []
        proc = fields.get("procedure") or fields.get("service_description")
        if proc:
            parts.append(f"The procedure recorded for this claim is: **{proc}**")

        if cpt_codes:
            parts.append(f"\nI found {len(cpt_codes)} CPT code(s):\n")
            for c in cpt_codes[:8]:
                conf = c.get("confidence")
                conf_str = f" (confidence: {conf:.0%})" if isinstance(conf, (int, float)) else ""
                parts.append(f"  • **`{c.get('code', '?')}`** — {c.get('description', 'N/A')}{conf_str}")
            parts.append("\nCPT codes map procedures and services to standardized billing categories.")
        elif proc:
            parts.append("CPT codes haven't been assigned yet — the coding pipeline may still be running.")
        else:
            if relevant_text:
                answer = _search_document_for_answer(query, relevant_text, fields, entities)
                if answer:
                    return answer
            parts.append("No procedure information has been extracted yet.")

        return "\n".join(parts) if parts else "No procedure data available."

    # ── Amount / billing / cost
    if _matches(query, ["amount", "cost", "charge", "total", "price", "billed", "paid",
                        "bill", "expense", "money", "how much", "billing", "fee"]):
        amount = fields.get("total_amount") or fields.get("amount") or fields.get("billed_amount")
        parts = []
        if amount:
            parts.append(f"The total billed amount for this claim is **₹{amount}**.")
            # Check for sub-items
            room = fields.get("room_charges")
            medicine = fields.get("medicine_charges")
            consultation = fields.get("consultation_charges")
            investigation = fields.get("investigation_charges")
            if any([room, medicine, consultation, investigation]):
                parts.append("\nHere's the breakdown:")
                if room:
                    parts.append(f"  • Room charges: ₹{room}")
                if medicine:
                    parts.append(f"  • Medicine: ₹{medicine}")
                if consultation:
                    parts.append(f"  • Consultation: ₹{consultation}")
                if investigation:
                    parts.append(f"  • Investigation/tests: ₹{investigation}")
                other = fields.get("other_charges")
                if other:
                    parts.append(f"  • Other: ₹{other}")
        else:
            if relevant_text:
                answer = _search_document_for_answer(query, relevant_text, fields, entities)
                if answer:
                    return answer
            parts.append("I couldn't find specific billing amounts in the parsed data. "
                        "The document may contain this info in unstructured form.")

        return "\n".join(parts)

    # ── Insurance / coverage / deductible / copay
    if _matches(query, ["coverage", "insurance", "payer", "deductible", "copay",
                        "reimbursement", "eligible", "network", "tpa", "insurer",
                        "pre-auth", "preauth", "authorization"]):
        parts = [f"Here's the insurance & coverage info for claim **{claim_id}**:\n"]
        payer = fields.get("payer_name") or fields.get("insurance_company") or fields.get("tpa_name")
        policy = ctx.get("policy_id") or fields.get("policy_number")
        member_id = fields.get("member_id") or fields.get("insurance_id")
        plan_type = fields.get("plan_type") or fields.get("insurance_type")
        preauth = fields.get("pre_authorization") or fields.get("preauth_number")

        if payer:
            parts.append(f"🏢 **Payer / TPA:** {payer}")
        if policy:
            parts.append(f"📄 **Policy Number:** {policy}")
        if member_id:
            parts.append(f"🆔 **Member ID:** {member_id}")
        if plan_type:
            parts.append(f"📋 **Plan Type:** {plan_type}")
        if preauth:
            parts.append(f"✅ **Pre-Authorization:** {preauth}")

        amount = fields.get("total_amount") or fields.get("amount") or fields.get("billed_amount")
        eligible = fields.get("eligible_amount") or fields.get("approved_amount")
        copay = fields.get("copay") or fields.get("copayment")
        deductible = fields.get("deductible") or fields.get("deductible_amount")

        if amount or eligible or copay or deductible:
            parts.append("\n💰 **Financial Summary:**")
            if amount:
                parts.append(f"  • Total Billed: ₹{amount}")
            if eligible:
                parts.append(f"  • Eligible Amount: ₹{eligible}")
            if deductible:
                parts.append(f"  • Deductible: ₹{deductible}")
            if copay:
                parts.append(f"  • Copay: ₹{copay}")

        if not payer and not policy and not amount:
            if relevant_text:
                answer = _search_document_for_answer(query, relevant_text, fields, entities)
                if answer:
                    return answer
            parts.append("I couldn't find specific insurance details in the structured data. "
                        "Check if the uploaded document contains payer/policy information.")

        parts.append("\n💡 **Tip:** Make sure all insurance fields are complete before TPA submission "
                     "to avoid claim rejection due to missing payer information.")
        return "\n".join(parts)

    # ── Why rejected / explain rejection — comprehensive analysis
    if _matches(query, ["why rejected", "why deny", "why denied", "why was", "reason for rejection",
                        "explain rejection", "explain the rejection", "claim rejected",
                        "got rejected", "was rejected", "rejection reason", "denial reason",
                        "why did", "cause of rejection", "cause of denial", "rejected why",
                        "denied why", "what went wrong", "why fail"]):

        parts = [f"## 🔍 Rejection Analysis for Claim **{claim_id}**\n"]
        issues: list[dict] = []  # collect all issues with severity + category for ranking

        # 1. Prediction risk analysis
        if predictions:
            p = predictions[0]
            score = p.get("rejection_score", 0)
            risk_label = _risk_label(score)
            model = p.get("model_name", "ensemble")
            reasons = p.get("top_reasons", [])

            parts.append("### 📊 ML Risk Assessment")
            parts.append(f"**Rejection Score:** {score if isinstance(score, str) else f'{score:.0%}'} — **{risk_label}**")
            parts.append(f"_Model: {model}_\n")

            if isinstance(score, (int, float)):
                if score <= 0.3:
                    parts.append("The ML model considers this claim **low risk** — it's unlikely to be rejected on its own merit.\n")
                elif score <= 0.6:
                    parts.append("The ML model flags **moderate risk** — there are some factors that could trigger a rejection.\n")
                else:
                    parts.append("The ML model flags **high risk** — multiple factors suggest this claim is likely to face rejection.\n")

            if reasons and isinstance(reasons, list):
                parts.append("**Key risk factors identified by the model:**")
                for i, r in enumerate(reasons[:5], 1):
                    reason_text = r.get("reason", str(r)) if isinstance(r, dict) else str(r)
                    weight = r.get("weight", 0) if isinstance(r, dict) else 0
                    feature = r.get("feature", "") if isinstance(r, dict) else ""
                    severity = "🔴" if weight >= 0.12 else "🟡" if weight >= 0.08 else "🟠"
                    parts.append(f"  {i}. {severity} **{reason_text}**")
                    if weight:
                        parts.append(f"     _Impact weight: {weight:.2f}_")
                    issues.append({"category": "prediction", "text": reason_text, "weight": weight, "feature": feature})
                parts.append("")

        # 2. Validation failures
        failed_rules = [v for v in validations if not v.get("passed")]
        if failed_rules:
            parts.append("### ⚠️ Validation Failures")
            parts.append(f"**{len(failed_rules)}** of **{len(validations)}** rules failed:\n")

            errors = [v for v in failed_rules if v.get("severity") == "ERROR"]
            warnings = [v for v in failed_rules if v.get("severity") != "ERROR"]

            if errors:
                parts.append("**Critical Errors (will cause rejection):**")
                for v in errors:
                    fix = _get_fix_hint(v.get("rule_name", ""), v.get("message", ""))
                    parts.append(f"  🔴 **{v.get('rule_name', 'Rule')}:** {v.get('message', '')}")
                    if fix:
                        parts.append(f"     → _Fix: {fix}_")
                    issues.append({"category": "validation_error", "text": v.get("message", ""), "weight": 0.20})
                parts.append("")

            if warnings:
                parts.append("**Warnings (may trigger manual review):**")
                for v in warnings:
                    fix = _get_fix_hint(v.get("rule_name", ""), v.get("message", ""))
                    parts.append(f"  🟡 **{v.get('rule_name', 'Rule')}:** {v.get('message', '')}")
                    if fix:
                        parts.append(f"     → _Fix: {fix}_")
                    issues.append({"category": "validation_warn", "text": v.get("message", ""), "weight": 0.10})
                parts.append("")

        # 3. Missing critical fields
        critical_fields = {
            "patient_name": "Patient Name",
            "policy_number": "Policy / Insurance Number",
            "diagnosis": "Primary Diagnosis",
            "primary_diagnosis": "Primary Diagnosis",
            "service_date": "Date of Service",
            "total_amount": "Total Billed Amount",
            "provider_name": "Provider / Hospital Name",
        }
        missing = [(k, label) for k, label in critical_fields.items() if not fields.get(k)]
        if missing:
            parts.append("### 📝 Missing Critical Fields")
            parts.append("These fields are required by most payers and their absence is a common rejection trigger:\n")
            for _k, label in missing:
                parts.append(f"  ❌ **{label}** — not found in extracted data")
                issues.append({"category": "missing_field", "text": f"Missing {label}", "weight": 0.15})
            parts.append("")

        # 4. Medical coding gaps
        icd_codes = [c for c in codes if c.get("code_type") in ("ICD-10", "ICD10")]
        cpt_codes = [c for c in codes if c.get("code_type") == "CPT"]
        coding_issues = []
        if not icd_codes:
            coding_issues.append("❌ **No ICD-10 codes** — diagnosis coding is required for claim adjudication")
            issues.append({"category": "coding", "text": "No ICD-10 diagnosis codes", "weight": 0.15})
        if not cpt_codes:
            coding_issues.append("❌ **No CPT codes** — procedure codes are needed for reimbursement")
            issues.append({"category": "coding", "text": "No CPT procedure codes", "weight": 0.10})
        has_primary = any(c.get("is_primary") for c in icd_codes)
        if icd_codes and not has_primary:
            coding_issues.append("⚠️ **No primary ICD code designated** — a principal diagnosis must be flagged")
            issues.append({"category": "coding", "text": "No primary diagnosis designated", "weight": 0.08})
        if coding_issues:
            parts.append("### 🏥 Medical Coding Issues")
            for ci in coding_issues:
                parts.append(f"  {ci}")
            parts.append("")

        # 5. Summary verdict
        parts.append("---")
        if not issues:
            parts.append("### ✅ No Rejection Factors Found")
            parts.append("This claim appears to be complete and low-risk. If it was rejected, "
                        "the reason may be payer-specific (e.g., pre-authorization required, "
                        "coverage limits, or network restrictions) rather than a data quality issue.")
            parts.append("\n💡 Consider checking the **Explanation of Benefits (EOB)** or denial letter from the payer.")
        else:
            # Rank issues by weight
            issues.sort(key=lambda x: x.get("weight", 0), reverse=True)
            top3 = issues[:3]
            parts.append("### 🎯 Most Likely Rejection Causes (ranked)")
            for i, issue in enumerate(top3, 1):
                parts.append(f"  **{i}.** {issue['text']}")

            parts.append(f"\n**Total issues found:** {len(issues)}")

            if any(i["category"] == "validation_error" for i in issues):
                parts.append("\n🚨 **Critical errors detected.** These must be fixed before resubmission.")
            elif len(issues) >= 3:
                parts.append("\n⚠️ **Multiple issues found.** Addressing the top 3 will significantly improve approval chances.")
            else:
                parts.append("\n💡 Fixing these issues should improve the claim's chances of approval.")

        parts.append("\n---\n*Would you like help fixing any of these issues?*")
        return "\n".join(parts)

    # ── Fix / improve / reduce risk
    if _matches(query, ["fix", "improve", "reduce", "correct", "resolve", "better",
                        "how to fix", "what should i", "recommendation", "suggest"]):
        parts = [f"Here are my recommendations to improve claim **{claim_id}**:\n"]

        issues_found = False

        # Check validation failures
        failed_rules = [v for v in validations if not v.get("passed")]
        if failed_rules:
            issues_found = True
            parts.append("🔧 **Fix Validation Issues:**")
            for v in failed_rules:
                sev = v.get("severity", "INFO")
                icon = "🔴" if sev == "ERROR" else "🟡"
                fix_hint = _get_fix_hint(v.get("rule_name", ""), v.get("message", ""))
                parts.append(f"  {icon} **{v.get('rule_name', 'Rule')}:** {v.get('message', '')}")
                if fix_hint:
                    parts.append(f"     → _Fix: {fix_hint}_")
            parts.append("")

        # Check prediction risk
        if predictions:
            p = predictions[0]
            score = p.get("rejection_score", 0)
            if isinstance(score, (int, float)) and score > 0.3:
                issues_found = True
                reasons = p.get("top_reasons", [])
                parts.append(f"📊 **Reduce Rejection Risk** (currently {score:.0%}):")
                if reasons and isinstance(reasons, list):
                    for r in reasons[:3]:
                        parts.append(f"  • Address: {r}")
                parts.append("")

        # Check missing critical fields
        critical = ["patient_name", "primary_diagnosis", "total_amount",
                     "service_date", "provider_name"]
        missing = [f for f in critical if not fields.get(f)]
        if missing:
            issues_found = True
            parts.append("📝 **Complete Missing Fields:**")
            for f in missing:
                parts.append(f"  • {f.replace('_', ' ').title()}")
            parts.append("")

        # Check if codes are assigned
        if not codes:
            issues_found = True
            parts.append("🏥 **Medical Coding:** No ICD-10/CPT codes found. "
                        "Run the coding pipeline or manually assign codes.\n")

        if not issues_found:
            parts.append("✅ This claim looks good! No major issues were detected.\n")
            parts.append("You can proceed to generate the TPA PDF for submission.")

        parts.append("---\nNeed help with any specific issue? Just ask!")
        return "\n".join(parts)

    # ── Prediction / risk
    if _matches(query, ["predict", "risk", "reject", "denial", "score", "chance",
                        "will it", "approved", "approval", "likely"]):
        if predictions:
            p = predictions[0]
            score = p.get("rejection_score", p.get("score", "N/A"))
            risk_label = _risk_label(score)
            reasons = p.get("top_reasons", [])
            model = p.get("model_name", "ensemble")

            parts = [f"The rejection risk score for this claim is **{score}** — that's **{risk_label}** risk."]

            if isinstance(score, (int, float)):
                if score <= 0.3:
                    parts.append("\n✅ This looks good! The claim has a high chance of being approved.")
                elif score <= 0.6:
                    parts.append("\n⚠️ There's a moderate risk of rejection. I'd recommend reviewing the flagged areas.")
                else:
                    parts.append("\n🚨 This claim has a high rejection risk. I'd strongly suggest addressing the issues before submission.")

            if reasons and isinstance(reasons, list):
                parts.append("\n**Top risk factors:**")
                for r in reasons[:5]:
                    parts.append(f"  • {r}")

            parts.append(f"\n_Scored by: {model}_")
            return "\n".join(parts)

        return ("No prediction has been run for this claim yet. "
                "Once the workflow pipeline completes, our ML models (XGBoost + LightGBM ensemble) "
                "will analyze the claim and generate a risk score.")

    # ── Validation
    if _matches(query, ["valid", "rule", "error", "issue", "problem", "fail",
                        "check", "compliance", "what's wrong"]):
        if validations:
            passed = sum(1 for v in validations if v.get("passed"))
            failed_rules = [v for v in validations if not v.get("passed")]
            total = len(validations)

            parts = ["Here are the validation results for this claim:\n"]
            parts.append(f"✅ **{passed}/{total}** rules passed")

            if failed_rules:
                parts.append(f"\n❌ **{len(failed_rules)} rule(s) failed:**\n")
                for v in failed_rules:
                    sev = v.get("severity", "INFO")
                    icon = "🔴" if sev == "ERROR" else "🟡" if sev == "WARN" else "ℹ️"
                    parts.append(f"  {icon} **{v.get('rule_name', v.get('rule_id', 'Rule'))}** — {v.get('message', 'No details')}")
                parts.append("\nI'd recommend fixing the ERROR-level issues before submitting to the TPA.")
            else:
                parts.append("\n🎉 All rules passed! This claim looks clean and ready for submission.")

            return "\n".join(parts)

        return ("No validation has been run yet. The validation step checks for common "
                "claim issues like missing required fields, code mismatches, and business rule violations.")

    # ── Patient / provider / hospital
    if _matches(query, ["patient", "name", "provider", "doctor", "physician", "member",
                        "hospital", "who", "admitted"]):
        parts = []
        pname = fields.get("patient_name") or fields.get("member_name")
        dob = fields.get("date_of_birth") or fields.get("dob")
        gender = fields.get("gender")
        prov = fields.get("provider_name") or fields.get("rendering_provider")
        hospital = fields.get("hospital") or fields.get("hospital_name")
        member_id = fields.get("member_id")

        if pname:
            parts.append(f"**Patient:** {pname}")
        if dob:
            parts.append(f"**Date of Birth:** {dob}")
        if gender:
            parts.append(f"**Gender:** {gender}")
        if member_id:
            parts.append(f"**Member ID:** {member_id}")
        if hospital:
            parts.append(f"\n**Hospital:** {hospital}")
        if prov:
            parts.append(f"**Provider:** {prov}")

        if not parts:
            # No structured fields — search the document text
            if relevant_text:
                answer = _search_document_for_answer(query, relevant_text, fields, entities)
                if answer:
                    return answer
            parts.append("I couldn't find patient/provider details in the parsed fields. "
                        "The document may contain this info in unstructured form.")

        return "\n".join(parts)

    # ── Document content / OCR
    if _matches(query, ["document", "file", "ocr", "text", "read", "page", "content",
                        "uploaded", "what does it say", "show me the doc", "raw text"]):
        if full_ocr:
            # Show a generous portion of the document
            preview = full_ocr[:2000]
            more_note = ""
            if len(full_ocr) > 2000:
                more_note = f"\n\n_...showing first portion of {page_count} pages ({len(full_ocr):,} characters total). Ask about specific sections for more detail._"
            return (
                f"Here's what I extracted from the uploaded document ({page_count} pages, {len(full_ocr):,} chars total):\n\n"
                f"---\n{preview}\n---{more_note}\n\n"
                f"I've read **every word** of the document. "
                f"Ask me about specific details like medications, dates, vitals, or any section!"
            )
        return ("I don't have the document text available yet. "
                "This usually means the OCR step hasn't run. "
                "The workflow pipeline runs automatically after upload.")

    # ── TPA / PDF / download / submission
    if _matches(query, ["tpa", "pdf", "download", "generate pdf", "submit to",
                        "send to payer", "print claim"]):
        return (
            "You can generate a TPA-ready PDF for this claim! "
            "Click the **\"Download TPA PDF\"** button in the claim card on the left sidebar.\n\n"
            "The PDF includes:\n"
            "  • Patient & provider details\n"
            "  • Diagnosis with ICD-10 codes\n"
            "  • Procedures with CPT codes\n"
            "  • Billing breakdown\n"
            "  • Rejection risk assessment\n"
            "  • Validation results\n"
            "  • Document excerpts\n\n"
            "This PDF is formatted for TPA submission — ready to print and send!"
        )

    # ── Codes mapping / how it works
    if _matches(query, ["how", "map", "mapping", "assigned", "extract", "work",
                        "process", "pipeline", "algorithm"]):
        return (
            "Great question! Here's how ClaimGPT processes your claim:\n\n"
            "1. **📤 Upload** — You upload a discharge summary, expense bill, or claim form\n"
            "2. **🔍 OCR** — We extract text from the document (even scanned images)\n"
            "3. **📋 Parse** — Our AI (LayoutLMv3) identifies key fields: patient name, diagnosis, amounts, etc.\n"
            "4. **🏥 Medical Coding** — Using scispaCy NER, we detect medical conditions and map them to:\n"
            "   • **ICD-10** codes (diagnoses)\n"
            "   • **CPT** codes (procedures)\n"
            "5. **📊 Risk Prediction** — XGBoost + LightGBM ensemble scores the rejection risk\n"
            "6. **✅ Validation** — Business rules check for missing info, code mismatches\n"
            "7. **📄 TPA PDF** — Generate a submission-ready document\n\n"
            "All of this happens automatically after upload! Would you like to know more about any specific step?"
        )

    # ── Thank you / bye
    if _matches(query, ["thank", "thanks", "appreciate", "great", "awesome", "perfect"]):
        return "You're welcome! 😊 Happy to help. Let me know if there's anything else you need!"

    if _matches(query, ["bye", "goodbye", "later", "see you"]):
        return "Goodbye! 👋 Feel free to come back anytime. Your claims data is always here when you need it."

    # ── Fallback — intelligent search across full document text ──
    # If the question didn't match any specific category, search the document
    if relevant_text:
        # Try to find the answer directly in the document text
        answer = _search_document_for_answer(query, relevant_text, fields, entities)
        if answer:
            return answer

    if fields or full_ocr or codes:
        parts = [f"I have the data for claim **{claim_id}** loaded up ({page_count} pages read). "]
        if status == "COMPLETED":
            parts.append("The claim has been fully processed. ")
        parts.append("Here are some things you can ask me:\n")
        parts.append("  • 📋 \"Give me a summary\" — full overview of the claim")
        parts.append("  • 🔬 \"What's the diagnosis?\" — ICD-10 codes and conditions")
        parts.append("  • 🔧 \"What procedures were done?\" — CPT codes")
        parts.append("  • 💰 \"Show me the billing\" — charges and amounts")
        parts.append("  • ⚠️ \"What's the rejection risk?\" — ML prediction score")
        parts.append("  • ✅ \"Are there any validation issues?\" — rule check results")
        parts.append("  • 👤 \"Patient details\" — name, DOB, provider info")
        parts.append("  • 📄 \"Show the document text\" — raw OCR content")
        parts.append("  • 📥 \"How do I get the TPA PDF?\" — download submission PDF")
        parts.append("\nJust ask in natural language — I understand context! 🙂")
        return "\n".join(parts)

    return (
        f"I see claim **{claim_id}** is in status **{status}**. "
        "It looks like the document hasn't been fully processed through the pipeline yet.\n\n"
        "Once processing completes, I'll be able to tell you about:\n"
        "  • Diagnosis and ICD-10 codes\n"
        "  • Procedures and CPT codes\n"
        "  • Billing amounts\n"
        "  • Rejection risk score\n"
        "  • Validation results\n\n"
        "Hang tight — it should be ready shortly! 🕐"
    )


def _search_document_for_answer(
    query: str,
    relevant_text: str,
    fields: dict[str, Any],
    entities: list[dict[str, Any]],
) -> str | None:
    """
    Search the full document text to find content that answers the user's question.
    Returns a natural-language response or None if nothing relevant found.
    """
    import re

    query_lower = query.lower()

    # Extract meaningful keywords from the query
    stop_words = {
        "the", "is", "at", "which", "on", "a", "an", "and", "or", "but",
        "in", "with", "to", "for", "of", "this", "that", "what", "how",
        "where", "when", "who", "me", "my", "i", "it", "was", "were",
        "are", "be", "been", "being", "do", "does", "did", "have", "has",
        "had", "can", "could", "will", "would", "shall", "should", "may",
        "might", "about", "from", "into", "show", "tell", "give",
        "please", "find", "get", "look", "see", "any", "all", "much",
    }
    words = re.findall(r"[a-z0-9]+", query_lower)
    keywords = [w for w in words if w not in stop_words and len(w) > 2]

    if not keywords:
        return None

    # Find paragraphs/lines containing the keywords
    lines = relevant_text.split("\n")
    matching_lines = []
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue
        line_lower = line_stripped.lower()
        score = sum(1 for kw in keywords if kw in line_lower)
        if score > 0:
            matching_lines.append((score, line_stripped))

    matching_lines.sort(key=lambda x: -x[0])

    if not matching_lines:
        return None

    # Build response from the most relevant lines
    top_matches = matching_lines[:15]
    match_text = "\n".join(f"  • {line}" for _, line in top_matches)

    # Also check if any parsed field matches
    field_matches = []
    for k, v in fields.items():
        k_lower = k.lower().replace("_", " ")
        if any(kw in k_lower or kw in str(v).lower() for kw in keywords):
            field_matches.append(f"  • **{k.replace('_', ' ').title()}:** {v}")

    entity_matches = []
    for e in entities:
        if any(kw in e.get("text", "").lower() for kw in keywords):
            entity_matches.append(f"  • [{e.get('type', 'ENTITY')}] {e.get('text', '')}")

    parts = ["Here's what I found in the document related to your question:\n"]

    if field_matches:
        parts.append("**From extracted fields:**")
        parts.extend(field_matches)
        parts.append("")

    if entity_matches:
        unique_ents = list(dict.fromkeys(entity_matches))
        parts.append("**Medical entities detected:**")
        parts.extend(unique_ents[:10])
        parts.append("")

    parts.append("**From document text:**")
    parts.append(match_text)

    if len(matching_lines) > 15:
        parts.append(f"\n_...found {len(matching_lines)} matching lines. Ask more specifically to narrow down._")

    parts.append("\nWant me to elaborate on any of these details?")

    return "\n".join(parts)


def _conversational_general(query: str, history: list) -> str:
    """Natural conversational response without claim context."""

    if _matches(query, ["hello", "hi", "hey", "good morning", "good afternoon",
                        "good evening", "what's up", "howdy"]):
        return (
            "Hey there! Welcome to **ClaimGPT** - your AI-powered claims brain!\n\n"
            "Here's what I can do:\n\n"
            "**Upload Any Document** - PDF, images, Word, Excel, CSV, text files\n"
            "**Smart Extraction** - OCR + NLP to read even scanned/handwritten docs\n"
            "**Auto Medical Coding** - Map diagnoses to ICD-10 and procedures to CPT (280+ codes)\n"
            "**Risk Prediction** - ML ensemble scores rejection risk before you submit\n"
            "**Preview Before Submit** - Review the full claim data before generating TPA PDF\n"
            "**TPA PDF Generation** - Professional submission-ready document\n"
            "**Ask Anything** - I understand your claims data deeply and can answer any question\n\n"
            "Upload a document on the left to get started, or ask me anything!"
        )

    if _matches(query, ["help", "what can you", "how do", "guide", "assist", "capabilities"]):
        return (
            "Of course! Here's everything I can help you with:\n\n"
            "**Document Upload** (PDF, DOCX, Excel, Images, CSV, Text, JSON, XML - up to 50 MB)\n"
            "Upload discharge summaries, expense bills, lab reports, prescriptions - any medical document.\n\n"
            "**Smart OCR & Extraction**\n"
            "Advanced multi-pass OCR with adaptive preprocessing reads even scanned/low-quality documents. "
            "Extracts 40+ field types including patient info, billing, vitals, and clinical data.\n\n"
            "**Medical Coding (280+ ICD-10 + 120+ CPT codes)**\n"
            "NLP engine with 146 clinical synonyms maps diagnoses to ICD-10 and procedures to CPT codes. "
            "You can accept, reject, or correct code suggestions for continuous improvement.\n\n"
            "**Risk Prediction (XGBoost + LightGBM)**\n"
            "ML ensemble predicts rejection risk with top contributing factors.\n\n"
            "**Preview & Validate**\n"
            "Preview the full extracted data before submission. Validation catches missing fields and mismatches.\n\n"
            "**TPA PDF Generation**\n"
            "Generate a professional 9-section TPA-readable PDF ready for submission.\n\n"
            "**Chat With Your Data**\n"
            "Ask anything about your claims - I have deep context on every field, code, and prediction."
        )

    if _matches(query, ["upload", "how to upload", "submit", "file", "document"]):
        return (
            "Uploading a claim is easy!\n\n"
            "1. **Drag & drop** a file onto the upload area, or **click** to browse\n"
            "2. Supported formats: **PDF, Images (JPEG/PNG/TIFF/BMP), Word (.docx), Excel (.xlsx), CSV, Text, JSON, XML, HTML** - up to 50 MB\n"
            "3. After upload, the AI pipeline runs automatically:\n"
            "   - **OCR** - Multi-pass text extraction with adaptive preprocessing\n"
            "   - **Parse** - 40+ field patterns + section detection for medical docs\n"
            "   - **Code** - NLP maps to ICD-10/CPT (280+ codes + 146 clinical synonyms)\n"
            "   - **Predict** - XGBoost + LightGBM risk scoring\n"
            "   - **Validate** - Business rules check\n"
            "4. **Preview** the data, then **download the TPA PDF** or ask me anything!\n\n"
            "Typical documents: **Discharge summaries, hospital bills, expense sheets, claim forms, lab reports, prescriptions**."
        )

    if _matches(query, ["icd", "cpt", "code", "coding", "medical code"]):
        return (
            "**Medical coding** is how the healthcare industry standardizes diagnoses and procedures:\n\n"
            "🔬 **ICD-10 codes** identify **what's wrong** (diagnoses):\n"
            "  • Example: `J06.9` = Acute upper respiratory infection\n"
            "  • Example: `E11.9` = Type 2 diabetes mellitus without complications\n"
            "  • Example: `I10` = Essential hypertension\n\n"
            "🔧 **CPT codes** identify **what was done** (procedures):\n"
            "  • Example: `99213` = Office visit (established patient)\n"
            "  • Example: `99283` = Emergency department visit\n"
            "  • Example: `71046` = Chest X-ray\n\n"
            "ClaimGPT uses **scispaCy** (medical NLP) to automatically detect conditions in your "
            "documents and map them to the correct codes. Pretty cool, right? 🤓\n\n"
            "Upload a claim to see it in action!"
        )

    if _matches(query, ["tpa", "pdf", "third party", "generate"]):
        return (
            "**TPA (Third Party Administrator)** is the intermediary that processes insurance claims.\n\n"
            "ClaimGPT generates a **TPA-readable PDF** that includes:\n"
            "  📋 Claim & policy information\n"
            "  👤 Patient details\n"
            "  🏥 Hospital & provider info\n"
            "  🔬 Diagnosis with ICD-10 codes\n"
            "  🔧 Procedures with CPT codes\n"
            "  💰 Billing breakdown\n"
            "  ⚠️ Risk assessment\n"
            "  ✅ Validation results\n\n"
            "Upload a document, let it process, and then click **\"Download TPA PDF\"** "
            "on the claim card to get the submission-ready PDF!"
        )

    if _matches(query, ["status", "track", "pipeline", "stages", "how does it work"]):
        return (
            "Here's how a claim flows through our AI pipeline:\n\n"
            "```\n"
            "📤 UPLOAD → 🔍 OCR → 📋 PARSE → 🏥 CODE → 📊 PREDICT → ✅ VALIDATE → 📄 PDF\n"
            "```\n\n"
            "1. **UPLOADED** — Document received and stored\n"
            "2. **OCR** — Text extracted from PDFs/images (even handwritten notes)\n"
            "3. **PARSED** — AI identifies key fields (patient, diagnosis, amounts, dates)\n"
            "4. **CODED** — Diagnoses mapped to ICD-10, procedures to CPT codes\n"
            "5. **PREDICTED** — ML models score rejection risk (0-1 scale)\n"
            "6. **VALIDATED** — Business rules check for completeness and accuracy\n"
            "7. **PDF READY** — Generate TPA-readable claim document\n\n"
            "The entire process runs automatically after upload! ⚡"
        )

    if _matches(query, ["reject", "denial", "risk", "predict", "approval"]):
        return (
            "Our **rejection risk prediction** uses machine learning to estimate the chance "
            "of a claim being denied:\n\n"
            "📊 **Score Range:**\n"
            "  • **0.0–0.3** (LOW) ✅ — Likely to be approved\n"
            "  • **0.3–0.6** (MODERATE) ⚠️ — Review recommended\n"
            "  • **0.6–1.0** (HIGH) 🚨 — Likely needs corrections\n\n"
            "The model considers:\n"
            "  • Coding completeness (are all required codes present?)\n"
            "  • Field validation (is all required info filled in?)\n"
            "  • Historical patterns (based on training data)\n"
            "  • Code-diagnosis consistency\n\n"
            "Upload a claim to get a risk assessment!"
        )

    if _matches(query, ["thank", "thanks", "appreciate", "great", "awesome"]):
        return "You're welcome! 😊 I'm always here to help with your claims. Don't hesitate to ask!"

    if _matches(query, ["bye", "goodbye", "later", "see you"]):
        return "See you later! 👋 Your claims data will be here whenever you're ready."

    # Smart fallback
    return (
        "That's a great question! While I'm best at helping with insurance claims, "
        "here's what I can do right now:\n\n"
        "📤 Upload a claim document (discharge summary, expense bill, claim form)\n"
        "🔬 Review diagnoses and ICD-10/CPT codes\n"
        "📊 Check rejection risk scores\n"
        "💰 View billing details\n"
        "📄 Generate TPA-ready PDFs\n\n"
        "Try uploading a document to see all of this in action, or select an existing claim "
        "from the sidebar! 🙂"
    )


def _get_fix_hint(rule_name: str, message: str) -> str:
    """Return a brief fix hint for common validation failures."""
    rn = rule_name.lower()
    msg = message.lower()
    if "missing" in msg and "field" in msg:
        return "Add the missing field value in the parsed data or re-upload with complete information."
    if "mismatch" in rn or "mismatch" in msg:
        return "Verify the codes match the documented diagnosis/procedure. Correct any mismatched codes."
    if "date" in rn or "date" in msg:
        return "Check admission/discharge/service dates for consistency and correct formatting."
    if "amount" in rn or "amount" in msg:
        return "Verify the billed amount matches the itemized charges. Check for arithmetic errors."
    if "code" in rn or "icd" in msg or "cpt" in msg:
        return "Review the assigned codes against the clinical documentation for accuracy."
    if "duplicate" in rn or "duplicate" in msg:
        return "Check for and remove any duplicate entries or submissions."
    return ""


def _risk_label(score: Any) -> str:
    if isinstance(score, (int, float)):
        if score <= 0.3:
            return "LOW ✅"
        if score <= 0.6:
            return "MODERATE ⚠️"
        return "HIGH 🚨"
    return "N/A"


def _matches(text: str, keywords: list[str]) -> bool:
    return any(re.search(r"\b" + re.escape(kw) + r"\b", text, re.I) for kw in keywords)


# ------------------------------------------------------------------ suggestions engine

def get_suggestions(
    query: str,
    claim_context: dict[str, Any] | None = None,
) -> list[str]:
    """Return contextual follow-up question suggestions based on conversation topic."""
    q = query.lower() if query else ""

    if not claim_context:
        return [
            "How does the claim pipeline work?",
            "What file types can I upload?",
            "Explain ICD-10 and CPT codes",
            "How is rejection risk calculated?",
        ]

    has_codes = bool(claim_context.get("medical_codes"))
    has_preds = bool(claim_context.get("predictions"))
    has_vals = bool(claim_context.get("validations"))
    has_fields = bool(claim_context.get("parsed_fields"))
    _ = claim_context.get("full_ocr_text")  # reserved for future use

    if _matches(q, ["diagnosis", "icd", "condition", "disease", "illness"]):
        s = []
        if has_codes:
            s.append("Are the ICD codes correct for this diagnosis?")
        s.extend(["Show the billing breakdown", "What's the rejection risk?", "Any validation issues?"])
        return s[:4]

    if _matches(q, ["billing", "amount", "cost", "charge", "bill", "expense", "money",
                     "how much", "fee", "paid", "billed"]):
        s = ["Show diagnosis and ICD codes", "What's the rejection risk?"]
        if has_vals:
            s.append("Are there any billing validation errors?")
        s.append("How do I generate the TPA PDF?")
        return s[:4]

    if _matches(q, ["coverage", "insurance", "payer", "deductible", "copay",
                     "reimbursement", "eligible", "network"]):
        s = ["Show the billing breakdown", "What's the rejection risk?",
             "Any missing fields for submission?", "Generate TPA PDF"]
        return s

    if _matches(q, ["risk", "predict", "reject", "denial", "score", "approval"]):
        s = ["Why was this claim rejected?", "What are the validation issues?"]
        if has_codes:
            s.append("Check if ICD codes are appropriate")
        s.append("How can I fix these issues?")
        return s[:4]

    if _matches(q, ["valid", "rule", "error", "issue", "problem", "fail", "compliance"]):
        s = ["Why was this claim rejected?", "What's the rejection risk?",
             "How do I fix these issues?", "Give me the full claim summary"]
        return s

    if _matches(q, ["fix", "improve", "reduce", "correct", "resolve", "better"]):
        s = ["Show the validation results", "Show diagnosis codes", "What's the rejection risk?",
             "Give me the full summary"]
        return s[:4]

    if _matches(q, ["summary", "overview", "review", "describe", "details"]):
        s = []
        if has_codes:
            s.append("Explain the ICD-10 codes")
        s.extend(["Show billing breakdown", "What's the rejection risk?", "Any issues to fix?"])
        return s[:4]

    if _matches(q, ["procedure", "cpt", "treatment", "surgery", "operation"]):
        s = ["Show diagnosis codes", "Show billing details", "What's the rejection risk?",
             "Any validation issues?"]
        return s

    if _matches(q, ["patient", "name", "provider", "doctor", "hospital"]):
        s = ["Give me a full summary", "Show the diagnosis", "Show billing details",
             "What's the rejection risk?"]
        return s

    if _matches(q, ["status", "progress", "stage", "state"]):
        s = ["Give me a full summary"]
        if has_preds:
            s.append("What's the rejection risk?")
        if has_vals:
            s.append("Any validation issues?")
        s.append("Show billing details")
        return s[:4]

    if _matches(q, ["document", "ocr", "text", "read", "page", "content"]):
        s = ["What's the primary diagnosis?", "Show billing details",
             "Extract patient information", "Give me a full summary"]
        return s

    # Default contextual suggestions
    s = ["Give me a full summary"]
    if has_codes:
        s.append("Show diagnosis codes")
    if has_preds:
        s.append("Why was this claim rejected?")
    elif has_fields:
        s.append("Show billing details")
    if has_vals:
        s.append("Any validation issues?")
    return s[:4]
