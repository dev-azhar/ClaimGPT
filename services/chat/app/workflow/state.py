from typing import TypedDict, Literal, Any, Optional, Annotated

from langgraph.graph import add_messages


class InputState(TypedDict):
    chat_input: str

class OutputState(TypedDict):
    chat_response: str

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    chat_input: str 
    claim_context:dict[str, Any]
    chat_response: str
    chat_response_stream: Optional[str]
    chat_session_id: Optional[str]

def state_to_str(state: AgentState) -> str:
    return f"""
AgentState(
    messages={state["messages"]},
    chat_input={state["chat_input"]},
    claim_context={state["claim_context"]},
    chat_response={state["chat_response"]},
    chat_response_stream={state.get("chat_response_stream")},
    chat_session_id={state["chat_session_id"]},
)
    """