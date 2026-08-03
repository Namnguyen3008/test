from langgraph.graph import END, StateGraph

from src.agents.nodes.example_node import (
    emergency_node,
    generate_node,
    normalize_node,
    retrieve_node,
    validate_node,
)
from src.agents.state import AgentState


def route_after_emergency(state: AgentState) -> str:
    return END if state.get("emergency") else "retrieve"


def route_after_retrieval(state: AgentState) -> str:
    return END if state.get("response") else "generate"


def route_after_generation(state: AgentState) -> str:
    return END if state.get("response") else "validate"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("normalize", normalize_node)
    graph.add_node("emergency", emergency_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("generate", generate_node)
    graph.add_node("validate", validate_node)
    graph.set_entry_point("normalize")
    graph.add_edge("normalize", "emergency")
    graph.add_conditional_edges("emergency", route_after_emergency)
    graph.add_conditional_edges("retrieve", route_after_retrieval)
    graph.add_conditional_edges("generate", route_after_generation)
    graph.add_edge("validate", END)
    return graph.compile()


agent = build_graph()
