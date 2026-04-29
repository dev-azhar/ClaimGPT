from typing import TypedDict, Literal, Any, Optional, Annotated

from langgraph.graph import add_messages

from services.chat.app.schemas import ClaimContext


class InputState(TypedDict):
    chat_input: str

class OutputState(TypedDict):
    chat_response: str

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    chat_input: str 
    general_claim_info: dict[str, Any] | None
    available_doc_types: list[str] | None
    claim_context:ClaimContext | None
    summary: str | None
    history: list | None
    intent: str 
    chat_response: str
    chat_response_stream: Optional[str]
    chat_session_id: Optional[str]

def state_to_str(state: AgentState) -> str:
    return f"""
AgentState(
    messages={state["messages"]},
    summary={state["summary"]},
    history={state["history"]},
    intent={state["intent"]},
    chat_input={state["chat_input"]},
    claim_context={state["claim_context"]},
    chat_response={state["chat_response"]},
    chat_response_stream={state.get("chat_response_stream")},
    chat_session_id={state["chat_session_id"]},
)
    """