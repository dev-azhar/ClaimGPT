from langgraph.graph import END, START, StateGraph

from services.chat.app.workflow.state import AgentState
from services.chat.app.workflow.node import generate_response, summarize, intent_classifier, rag_node, risk_analysis, billing_node, medical_coding_node


def create_workflow_graph():
    graph_builder = StateGraph(AgentState)

    graph_builder.add_node("summarize_history", summarize)
    graph_builder.add_node("intent_classification", intent_classifier)

    graph_builder.add_node("medical_coding", medical_coding_node)
    graph_builder.add_node("billing_handler", billing_node)  
    graph_builder.add_node("document_rag", rag_node)
    graph_builder.add_node("risk_analysis", risk_analysis)

    graph_builder.add_node("generate_response", generate_response)

    # 1. parallel start
    graph_builder.add_edge(START, "summarize_history")
    graph_builder.add_edge(START, "intent_classification")

    # 2. conditional routing from intent
    def route_intent(state):
        intent = state["intent"]

        if intent == "general":
            return "generate_response"
        elif intent == "medical_coding":
            return "medical_coding"
        elif intent == "risk_analysis":
            return "risk_analysis"
        elif intent == "billing":
            return "billing_handler"

    graph_builder.add_conditional_edges(
        "intent_classification",
        route_intent,
        {
            "generate_response": "generate_response",
            "medical_coding": "medical_coding",
            "risk_analysis": "risk_analysis",
            "billing_handler": "billing_handler",

        },
    )

    # 3. all routes → generate_response
    graph_builder.add_edge("medical_coding", END)
    graph_builder.add_edge("billing_handler", END)
    graph_builder.add_edge("risk_analysis", END)
    graph_builder.add_edge("document_rag", END)

    graph_builder.add_edge("generate_response", END)

    return graph_builder

# Compiled without a checkpointer. Used for LangGraph Studio
graph = create_workflow_graph().compile()
