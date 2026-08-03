from langgraph.graph import END, StateGraph

from src.agents.nodes.example_node import emergency_node, normalize_node, respond_node
from src.agents.state import AgentState


def route_after_emergency(state: AgentState) -> str:
    return END if state.get("emergency") else "respond"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("normalize", normalize_node)
    graph.add_node("emergency", emergency_node)
    graph.add_node("respond", respond_node)
    graph.set_entry_point("normalize")
    graph.add_edge("normalize", "emergency")
    graph.add_conditional_edges("emergency", route_after_emergency)
    graph.add_edge("respond", END)
    return graph.compile()


agent = build_graph()
