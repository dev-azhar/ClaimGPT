from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from services.chat.app.schemas import ClaimContext
from services.chat.app.workflow.llm_chain import build_chain
from langgraph.config import get_stream_writer
from langchain_core.messages import RemoveMessage
from langchain_core.runnables.config import RunnableConfig
from services.chat.app.prompts import BASE_PROMPT, SUMMERIZATION_PROMPT, INTENT_CLASSIFICATION_PROMPT, RISK_ANALYSIS_PROMPT, BILLING_PROMPT, MEDICAL_CODING_PROMPT, GENERAL_DATA_RETRIEVAL_PROMPT
from services.chat.app.llm import _language_clause
from services.chat.app.workflow.state import AgentState
from services.chat.app.workflow.llm_chain import get_chat_model
from services.chat.app.config import settings
import json, logging
from typing import Any

# ------------------------------------------------------------------ logging
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("chat.workflow.node")

async def general_response(state: AgentState, config: RunnableConfig):
    messages = state["messages"]
    write = get_stream_writer()  # ✅ get the custom stream writer

    # Append a language directive to the system prompt when the user has
    # selected a non-English UI language.
    system_prompt = BASE_PROMPT.prompt + _language_clause(state.get("language"))

    # Before rendering the prompt
    session_id = state["chat_session_id"]
    session_type = "general" if session_id.startswith("general") else "claim"

    chain = build_chain(system_prompt=system_prompt)

    collected = []

    # ✅ astream instead of ainvoke — emits tokens as they arrive
    async for chunk in chain.astream({"messages": messages, 
                                      "claim_context": state["claim_context"],
                                      "general_claim_info": state["general_claim_info"],
                                      "session_id": session_id,
                                      "session_type": session_type
                                      }, 
                                     config=config):
        token = chunk.content if hasattr(chunk, "content") else str(chunk)
        if token:
            collected.append(token)
            write({"token": token})  # ✅ push token to custom stream

    full_response = "".join(collected)
    return {"messages": [AIMessage(content=full_response)]}


async def summarize(state: AgentState, config: RunnableConfig):
    if len(state["messages"]) <= 2:
        return {}

    recent_messages = state["messages"][-2:]
    messages_to_delete = state["messages"][:-2]

    # Format history as plain text to avoid any state message accumulation
    history_text = "\n".join(
        f"{m.__class__.__name__}: {m.content}"
        for m in state["messages"]
    )

    # Direct LLM call — no chain, no state interference
    llm = get_chat_model()
    response = await llm.ainvoke([
        SystemMessage(content=SUMMERIZATION_PROMPT.prompt),
        HumanMessage(content=f"Summarize this conversation history:\n\n{history_text}")
    ])

    summary_message = SystemMessage(
        content=f"This is a summary of the conversation so far:\n{response.content}"
    )

    delete_ops = [RemoveMessage(id=m.id) for m in messages_to_delete]

    return {
        "summary": response.content,
        "messages": delete_ops + [summary_message] + recent_messages
    }

async def intent_classifier(state: AgentState, config: RunnableConfig):
    user_input = state["chat_input"]

    if not user_input:
        return {"intent": "general"}
    available_documents = state["available_doc_types"] or []
    
    formated_prompt = INTENT_CLASSIFICATION_PROMPT.prompt.format(
        available_documents = available_documents
    )

    # Direct LLM call — no chain, no state message accumulation
    llm = get_chat_model()
    response = await llm.ainvoke([
        SystemMessage(content=INTENT_CLASSIFICATION_PROMPT.prompt),
        HumanMessage(content=f"user input query: {user_input}")
    ])
    raw = json.loads(response.content.strip().removeprefix("```json").removesuffix("```").strip())

    try:
        if isinstance(raw, str):
            parsed = json.loads(raw)
        elif isinstance(raw, dict):
            parsed = raw
        else:
            logger.warning(f"Unsupported type: {type(raw)}")
        
        intent = parsed.get("intent", "general")
        confidence = parsed.get("confidence", 0.0)
        if intent == "general_data_retrieval":
            general_data_retrieval_docs = parsed.get("required_documents", [])
        else:
                general_data_retrieval_docs = []

        if confidence < 0.4:
            intent = "general"

        return {"intent": intent, "general_data_retrieval_docs": general_data_retrieval_docs}

    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning(f"[intent_classifier] Failed to parse intent: {e} | Raw: {raw}")
        return {"intent": "general"}

async def medical_coding_node(state: AgentState, config: RunnableConfig):
    claim_context: ClaimContext = state["claim_context"]
    write = get_stream_writer()

    m_codes = claim_context.medical_codes
    m_entities = claim_context.medical_entities
    available_documents = state["available_doc_types"] or []
    rag_results = state.get("rag_results") or {"icd10": [], "cpt": [], "query": ""}

    chain = build_chain(system_prompt=MEDICAL_CODING_PROMPT.prompt)
    collected = []

    async for chunk in chain.astream({"messages": state["messages"], 
                                      "medical_entities": m_entities,
                                        "medical_codes": m_codes,
                                        "general_claim_info": state["general_claim_info"],
                                        "available_documents" : available_documents,
                                        "rag_results": rag_results,
                                      }, 
                                      config=config):
        token = chunk.content if hasattr(chunk, "content") else str(chunk)
        if token:
            collected.append(token)
            write({"token": token})

    full_response = "".join(collected)
    return {"messages": [AIMessage(content=full_response)]}


async def risk_analysis(state: AgentState, config: RunnableConfig):
    claim_context: ClaimContext = state["claim_context"]
    write = get_stream_writer()
    available_documents = state["available_doc_types"] or []
    rag_results = state.get("rag_results") or {
        "icd10": [], "cpt": [], "entity_lookups": [], "coding_consistency": {}
    }

    chain = build_chain(system_prompt=RISK_ANALYSIS_PROMPT.prompt)
    collected = []

    async for chunk in chain.astream({"messages": state["messages"], 
                                      "claim_context": claim_context,
                                      "general_claim_info": state["general_claim_info"],
                                      "available_documents" : available_documents,
                                      "rag_results": rag_results,
                                      }, 
                                      config=config):
        token = chunk.content if hasattr(chunk, "content") else str(chunk)
        if token:
            collected.append(token)
            write({"token": token})

    full_response = "".join(collected)
    return {"messages": [AIMessage(content=full_response)]}


async def billing_node(state: AgentState, config: RunnableConfig):
    claim_context: ClaimContext = state["claim_context"]
    write = get_stream_writer()

    required_docs = ["BILL_INVOICE","DISCHARGE_SUMMARY","LAB_REPORT","RADIOLOGY_REPORT","PRESCRIPTION"]
    parsed_fields = {
    doc_type: fields
    for doc_type, fields in claim_context.parsed_fields_by_document_type.items()
    if doc_type in required_docs
    }
    relevant = claim_context.relevant_text or " "
    relevant = " "
    available_documents = state["available_doc_types"] or []
    


    chain = build_chain(system_prompt=BILLING_PROMPT.prompt)
    collected = []

    async for chunk in chain.astream({"messages": state["messages"], 
                                      "parsed_fields": parsed_fields, 
                                      "document_text": relevant,
                                      "general_claim_info": state["general_claim_info"],
                                      "available_documents" : available_documents
                                      }, 
                                      config=config):
        token = chunk.content if hasattr(chunk, "content") else str(chunk)
        if token:
            collected.append(token)
            write({"token": token})

    full_response = "".join(collected)
    return {"messages": [AIMessage(content=full_response)]}

async def general_data_retrieval_node(state: AgentState, config: RunnableConfig):
    claim_context: ClaimContext = state["claim_context"]
    write = get_stream_writer()
    required_docs = state.get("general_data_retrieval_docs", [])

    #doc type wise parsed fields
    parsed_fields_by_doc = claim_context.parsed_fields_by_document_type or {}
    if parsed_fields_by_doc:
        document_data = "\n".join(
        f"Document Type: {doc_type}\nFields:\n" +
        "\n".join(f"- {k}: {v}" for k, v in fields.items())
        for doc_type, fields in parsed_fields_by_doc.items()
        if doc_type in required_docs
        )
    else:
        document_data = "No document data available."


    chain = build_chain(system_prompt=GENERAL_DATA_RETRIEVAL_PROMPT.prompt)
    collected = []

    async for chunk in chain.astream({"messages": state["messages"], 
                                      "claim_context": claim_context,
                                      "general_claim_info": state["general_claim_info"],
                                      "document_data": document_data
                                      }, 
                                      config=config):
        token = chunk.content if hasattr(chunk, "content") else str(chunk)
        if token:
            collected.append(token)
            write({"token": token})

    full_response = "".join(collected)
    return {"messages": [AIMessage(content=full_response)]}


async def rag_node(state: AgentState, config: RunnableConfig):
    """
    Retrieval-Augmented Generation node.

    Performs semantic search over the ICD-10-CM (~74.7k codes) and CPT FAISS
    indices, then stores the retrieved codes in ``state['rag_results']`` so
    downstream specialist nodes (e.g. ``medical_coding_node``) can ground
    their answers in real codes rather than hallucinating.

    Two retrieval passes are run:

    1. **Query-based** — uses the latest user message to surface candidate
       ICD-10 / CPT codes relevant to the question being asked.
    2. **Entity-based** — for each NER medical entity already extracted on
       the active claim (DIAGNOSIS / PROCEDURE / SYMPTOM types), retrieves
       the top ICD-10 candidate. This gives the LLM an authoritative
       entity → code lookup table to verify the existing mapped codes
       against.
    """
    user_input = (state.get("chat_input") or "").strip()

    # Lazy-import to avoid loading sentence-transformers + FAISS at module
    # import time (~2-3s + ~120MB of indices).
    try:
        from services.coding.app.icd10_rag import (
            is_rag_available,
            search_cpt_rag,
            search_icd10_rag,
        )
    except Exception:  # pragma: no cover — defensive
        logger.warning("RAG module unavailable", exc_info=True)
        return {"rag_results": None}

    if not is_rag_available():
        logger.info("RAG indices not loaded — skipping retrieval")
        return {"rag_results": None}

    # ── 1. Query-based retrieval ──────────────────────────────────────────
    icd10_hits: list = []
    cpt_hits: list = []
    if user_input:
        icd10_hits = search_icd10_rag(user_input, max_results=5)
        cpt_hits = search_cpt_rag(user_input, max_results=5)

    # ── 2. Entity-based retrieval ─────────────────────────────────────────
    # Pull DIAGNOSIS/SYMPTOM/PROCEDURE entities from the active claim and
    # look up the single best candidate code for each. We dedupe on entity
    # text (case-insensitive) so we don't waste embeddings on duplicates.
    entity_lookups: list[dict[str, Any]] = []
    claim_context: ClaimContext | None = state.get("claim_context")
    if claim_context is not None:
        seen: set[str] = set()
        diag_types = {"DIAGNOSIS", "DISEASE", "SYMPTOM", "FINDING", "CONDITION"}
        proc_types = {"PROCEDURE", "TREATMENT", "SURGERY"}
        for ent in (claim_context.medical_entities or []):
            text = (getattr(ent, "text", "") or "").strip()
            etype = (getattr(ent, "type", "") or "").upper()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            if etype in diag_types:
                hits = search_icd10_rag(text, max_results=1)
                if hits:
                    code, desc, cat, score = hits[0]
                    entity_lookups.append({
                        "entity_text": text,
                        "entity_type": etype,
                        "code_system": "ICD-10",
                        "code": code,
                        "description": desc,
                        "category": cat,
                        "score": round(score, 3),
                    })
            elif etype in proc_types:
                hits = search_cpt_rag(text, max_results=1)
                if hits:
                    code, desc, cat, score = hits[0]
                    entity_lookups.append({
                        "entity_text": text,
                        "entity_type": etype,
                        "code_system": "CPT",
                        "code": code,
                        "description": desc,
                        "category": cat,
                        "score": round(score, 3),
                    })

    rag_results = {
        "query": user_input,
        "icd10": [
            {"code": code, "description": desc, "category": cat, "score": round(score, 3)}
            for code, desc, cat, score in icd10_hits
        ],
        "cpt": [
            {"code": code, "description": desc, "category": cat, "score": round(score, 3)}
            for code, desc, cat, score in cpt_hits
        ],
        "entity_lookups": entity_lookups,
    }

    # ── 3. Coding-consistency check ───────────────────────────────────────
    # Compare the codes submitted on the claim against everything retrieval
    # surfaced (top-K query hits + per-entity top-1). Codes the model
    # surfaced but the claim is missing → "missing_from_claim". Codes the
    # claim has but retrieval never surfaced → "unsupported_by_retrieval".
    # Used by the risk_analysis node as an additional risk signal.
    submitted_icd10: set[str] = set()
    submitted_cpt: set[str] = set()
    if claim_context is not None:
        for mc in (claim_context.medical_codes or []):
            code = (getattr(mc, "code", "") or "").strip().upper()
            ctype = (getattr(mc, "code_type", "") or "").upper()
            if not code:
                continue
            if "ICD" in ctype:
                submitted_icd10.add(code)
            elif "CPT" in ctype or "HCPCS" in ctype:
                submitted_cpt.add(code)

    rag_icd10_codes = {h["code"].upper() for h in rag_results["icd10"]}
    rag_icd10_codes |= {
        e["code"].upper() for e in entity_lookups if e["code_system"] == "ICD-10"
    }
    rag_cpt_codes = {h["code"].upper() for h in rag_results["cpt"]}
    rag_cpt_codes |= {
        e["code"].upper() for e in entity_lookups if e["code_system"] == "CPT"
    }

    rag_results["coding_consistency"] = {
        "submitted_icd10": sorted(submitted_icd10),
        "submitted_cpt": sorted(submitted_cpt),
        "icd10_unsupported_by_retrieval": sorted(submitted_icd10 - rag_icd10_codes),
        "cpt_unsupported_by_retrieval": sorted(submitted_cpt - rag_cpt_codes),
        "icd10_missing_from_claim": sorted(rag_icd10_codes - submitted_icd10),
        "cpt_missing_from_claim": sorted(rag_cpt_codes - submitted_cpt),
    }

    logger.info(
        "rag_node: %d ICD-10 + %d CPT for query=%r, %d entity lookups, "
        "%d unsupported ICD-10 / %d unsupported CPT",
        len(rag_results["icd10"]), len(rag_results["cpt"]),
        user_input[:80], len(entity_lookups),
        len(rag_results["coding_consistency"]["icd10_unsupported_by_retrieval"]),
        len(rag_results["coding_consistency"]["cpt_unsupported_by_retrieval"]),
    )
    return {"rag_results": rag_results}