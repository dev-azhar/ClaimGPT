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
    


    chain = build_chain(system_prompt=RISK_ANALYSIS_PROMPT.prompt)
    collected = []

    async for chunk in chain.astream({"messages": state["messages"], 
                                      "claim_context": claim_context,
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
    indices using the latest user query, then stores the retrieved codes in
    ``state['rag_results']`` so downstream specialist nodes (e.g.
    ``medical_coding_node``) can ground their answers in real codes rather
    than hallucinating.
    """
    user_input = (state.get("chat_input") or "").strip()
    if not user_input:
        return {"rag_results": None}

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

    icd10_hits = search_icd10_rag(user_input, max_results=5)
    cpt_hits = search_cpt_rag(user_input, max_results=5)

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
    }
    logger.info(
        "rag_node retrieved %d ICD-10 + %d CPT codes for query=%r",
        len(rag_results["icd10"]), len(rag_results["cpt"]), user_input[:80],
    )
    return {"rag_results": rag_results}