from langgraph.graph import END, START, StateGraph

from services.chat.app.workflow.state import AgentState
from services.chat.app.workflow.node import generate_response


def create_workflow_graph():
    graph_builder = StateGraph(AgentState)
    graph_builder.add_node("generate_response", generate_response)


    graph_builder.add_edge(START, "generate_response")
    graph_builder.add_edge("generate_response", END)

    return graph_builder

# Compiled without a checkpointer. Used for LangGraph Studio
graph = create_workflow_graph().compile()
