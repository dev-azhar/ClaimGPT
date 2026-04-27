from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from services.chat.app.schemas import ClaimContext
from services.chat.app.workflow.llm_chain import build_chain
from langgraph.config import get_stream_writer
from langchain_core.messages import RemoveMessage
from langchain_core.runnables.config import RunnableConfig
from services.chat.app.prompts import BASE_PROMPT, SUMMERIZATION_PROMPT, INTENT_CLASSIFICATION_PROMPT, RISK_ANALYSIS_PROMPT, BILLING_PROMPT, MEDICAL_CODING_PROMPT
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

async def generate_response(state: AgentState, config: RunnableConfig):
    messages = state["messages"]
    write = get_stream_writer()  # ✅ get the custom stream writer

    chain = build_chain(system_prompt=BASE_PROMPT.prompt)

    collected = []

    # ✅ astream instead of ainvoke — emits tokens as they arrive
    async for chunk in chain.astream({"messages": messages, 
                                      "claim_context": state["claim_context"],
                                      "general_claim_info": state["general_claim_info"],
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

        if confidence < 0.4:
            intent = "general"

        return {"intent": intent}

    except (json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"[intent_classifier] Failed to parse intent: {e} | Raw: {raw}")
        return {"intent": "general"}

async def medical_coding_node(state: AgentState, config: RunnableConfig):
    claim_context: ClaimContext = state["claim_context"]
    write = get_stream_writer()

    m_codes = claim_context.medical_codes
    m_entities = claim_context.medical_entities

    chain = build_chain(system_prompt=MEDICAL_CODING_PROMPT.prompt)
    collected = []

    async for chunk in chain.astream({"messages": state["messages"], 
                                      "medical_entities": m_entities,
                                        "medical_codes": m_codes,
                                        "general_claim_info": state["general_claim_info"]
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


    chain = build_chain(system_prompt=RISK_ANALYSIS_PROMPT.prompt)
    collected = []

    async for chunk in chain.astream({"messages": state["messages"], 
                                      "claim_context": claim_context,
                                      "general_claim_info": state["general_claim_info"]
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

    parsed_feilds = claim_context.parsed_fields
    relevant = claim_context.relevant_text or " "
    relevant = " "


    chain = build_chain(system_prompt=BILLING_PROMPT.prompt)
    collected = []

    async for chunk in chain.astream({"messages": state["messages"], 
                                      "parsed_fields": parsed_feilds, 
                                      "document_text": relevant,
                                      "general_claim_info": state["general_claim_info"]
                                      }, 
                                      config=config):
        token = chunk.content if hasattr(chunk, "content") else str(chunk)
        if token:
            collected.append(token)
            write({"token": token})

    full_response = "".join(collected)
    return {"messages": [AIMessage(content=full_response)]}


async def rag_node(state: AgentState, config: RunnableConfig):
    # Placeholder for RAG logic
    # Implement this function to perform retrieval-augmented generation based on the user's intent and conversation context
    return {}