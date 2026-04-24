from langgraph.graph import END, START, StateGraph

from services.chat.app.workflow.state import AgentState
from services.chat.app.workflow.node import generate_response, summarize


def create_workflow_graph():
    graph_builder = StateGraph(AgentState)
    graph_builder.add_node("generate_response", generate_response)
    graph_builder.add_node("summarize_history", summarize)

    
    graph_builder.add_edge(START, "summarize_history")
    graph_builder.add_edge("summarize_history", "generate_response")
    graph_builder.add_edge("generate_response", END)

    return graph_builder

# Compiled without a checkpointer. Used for LangGraph Studio
graph = create_workflow_graph().compile()
