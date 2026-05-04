"""Routing tests for the chat LangGraph workflow.

We don't execute the LLM-backed nodes here — instead we inspect the
compiled graph's edges to confirm:
  * intent="medical_coding" routes through rag_retrieval first
  * intent="risk_analysis"  ALSO routes through rag_retrieval first
  * rag_retrieval fans out to medical_coding OR risk_analysis based on intent
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
for _k in [k for k in list(sys.modules) if k == "app" or k.startswith("app.")]:
    del sys.modules[_k]

import pytest

from services.chat.app.workflow.graph import create_workflow_graph


@pytest.fixture(scope="module")
def graph():
    return create_workflow_graph()


def test_required_nodes_present(graph):
    nodes = set(graph.nodes.keys())
    for required in {
        "summarize_history",
        "intent_classification",
        "rag_retrieval",
        "medical_coding",
        "risk_analysis",
        "billing_handler",
        "general_data_retrieval",
        "general_response",
    }:
        assert required in nodes, f"Missing node: {required}"


def _get_router(graph, node_name: str):
    """Return a callable that runs the conditional branch attached to ``node_name``.

    LangGraph wraps the routing function in a ``RunnableCallable`` since
    upgrading; ``.invoke(state)`` is the supported way to evaluate it.
    """
    branches = graph.branches.get(node_name) or {}
    assert branches, f"{node_name} has no conditional branches"
    branch = next(iter(branches.values()))
    return lambda state: branch.path.invoke(state)


def test_route_intent_medical_coding_goes_through_rag(graph):
    """intent='medical_coding' must hit rag_retrieval before the specialist."""
    route = _get_router(graph, "intent_classification")
    assert route({"intent": "medical_coding"}) == "rag_retrieval"


def test_route_intent_risk_analysis_goes_through_rag(graph):
    """intent='risk_analysis' must also flow through rag_retrieval."""
    route = _get_router(graph, "intent_classification")
    assert route({"intent": "risk_analysis"}) == "rag_retrieval"


def test_route_intent_billing_skips_rag(graph):
    route = _get_router(graph, "intent_classification")
    assert route({"intent": "billing"}) == "billing_handler"


def test_route_intent_general_skips_rag(graph):
    route = _get_router(graph, "intent_classification")
    assert route({"intent": "general"}) == "general_response"
    assert route({"intent": "unknown_xyz"}) == "general_response"


def test_rag_retrieval_branches_to_correct_specialist(graph):
    """After RAG, route by intent to the correct downstream node."""
    route = _get_router(graph, "rag_retrieval")
    assert route({"intent": "medical_coding"}) == "medical_coding"
    assert route({"intent": "risk_analysis"}) == "risk_analysis"
    # Default: medical_coding (covers any unforeseen routing through rag).
    assert route({"intent": "anything_else"}) == "medical_coding"
