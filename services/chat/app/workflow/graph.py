from langgraph.graph import END, START, StateGraph

from services.chat.app.workflow.state import AgentState
from services.chat.app.workflow.node import general_response, summarize, intent_classifier, rag_node, risk_analysis, billing_node, medical_coding_node, general_data_retrieval_node


def create_workflow_graph():
    graph_builder = StateGraph(AgentState)

    graph_builder.add_node("summarize_history", summarize)
    graph_builder.add_node("intent_classification", intent_classifier)

    graph_builder.add_node("medical_coding", medical_coding_node)
    graph_builder.add_node("billing_handler", billing_node)
    graph_builder.add_node("risk_analysis", risk_analysis)
    graph_builder.add_node("general_data_retrieval", general_data_retrieval_node)
    graph_builder.add_node("general_response", general_response)

    # ── 1. START → summarize (always) ────────────────────────────────────────
    graph_builder.add_edge(START, "summarize_history")

    # ── 2. START → session-id gate ───────────────────────────────────────────
    def route_by_session(state: AgentState):
        session_id = state.get("chat_session_id", "")
        if session_id.startswith("general"):
            return "general_response"
        return "intent_classification"

    graph_builder.add_conditional_edges(
        START,
        route_by_session,
        {
            "general_response": "general_response",
            "intent_classification": "intent_classification",
        },
    )

    # ── 3. intent → specialist nodes ─────────────────────────────────────────
    def route_intent(state: AgentState):
        intent = state["intent"]
        if intent == "general":
            return "general_response"
        elif intent == "general_data_retrieval":
            return "general_data_retrieval"
        elif intent == "medical_coding":
            return "medical_coding"
        elif intent == "risk_analysis":
            return "risk_analysis"
        elif intent == "billing":
            return "billing_handler"
        # fallback
        return "general_response"

    graph_builder.add_conditional_edges(
        "intent_classification",
        route_intent,
        {
            "general_response": "general_response",
            "medical_coding": "medical_coding",
            "risk_analysis": "risk_analysis",
            "billing_handler": "billing_handler",
            "general_data_retrieval": "general_data_retrieval",
        },
    )

    # ── 4. all terminal edges → END ───────────────────────────────────────────
    graph_builder.add_edge("summarize_history", END)
    graph_builder.add_edge("general_response", END)
    graph_builder.add_edge("medical_coding", END)
    graph_builder.add_edge("billing_handler", END)
    graph_builder.add_edge("risk_analysis", END)
    graph_builder.add_edge("general_data_retrieval", END)

    return graph_builder


# Compiled without a checkpointer. Used for LangGraph Studio
graph = create_workflow_graph().compile()