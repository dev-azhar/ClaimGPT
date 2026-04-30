from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from services.chat.app.workflow.llm_chain import build_chain
from langgraph.config import get_stream_writer
from langchain_core.messages import RemoveMessage
from langchain_core.runnables.config import RunnableConfig
from services.chat.app.prompts import BASE_PROMPT, SUMMERIZATION_PROMPT
from services.chat.app.llm import _language_clause
from services.chat.app.workflow.state import AgentState
import json


async def generate_response(state: AgentState, config: RunnableConfig):
    messages = state["messages"]
    write = get_stream_writer()  # ✅ get the custom stream writer

    # Append a language directive to the system prompt when the user has
    # selected a non-English UI language.
    system_prompt = BASE_PROMPT.prompt + _language_clause(state.get("language"))
    chain = build_chain(system_prompt=system_prompt)

    collected = []

    # ✅ astream instead of ainvoke — emits tokens as they arrive
    async for chunk in chain.astream({"messages": messages, "claim_context": state["claim_context"]}, config=config):
        token = chunk.content if hasattr(chunk, "content") else str(chunk)
        if token:
            collected.append(token)
            write({"token": token})  # ✅ push token to custom stream

    full_response = "".join(collected)
    return {"messages": [AIMessage(content=full_response)]}

async def summarize(state: AgentState, config: RunnableConfig):
    if len(state["messages"]) <= 2:
        return state

    recent_messages = state["messages"][-2:]
    messages_to_delete = state["messages"][:-2]

    llm = build_chain(system_prompt=SUMMERIZATION_PROMPT.prompt)
    summarized_messages = await llm.ainvoke(
        input={
            "history": state["messages"],
            "messages": state["messages"] + [HumanMessage(content="summarize the conversation")],
        }
    )

    # ✅ Use SystemMessage so it sits naturally before the human turn
    summary_message = SystemMessage(
        content=f"This is a summary of the conversation so far:\n{summarized_messages.content}"
    )

    delete_ops = [RemoveMessage(id=m.id) for m in messages_to_delete]

    # ✅ Order: [deletes, summary_system_msg, last_human, last_ai]
    return {
        "summary": summarized_messages.content,
        "messages": delete_ops + [summary_message] + recent_messages
    }