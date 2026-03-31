"""
LangGraph workflow definition — per-URL audit graph
Nodes 2-4 in the workflow: orchestrator → worker → state_updater
Synthesis and Export run in app.py AFTER postcrawl.
"""
from langgraph.graph import StateGraph, END
from graph.state import AuditState
from graph.nodes import (
    ingestion_node,
    orchestrator_node,
    worker_node,
    state_updater_node,
)


def create_workflow() -> StateGraph:
    """Build the per-URL LangGraph workflow (synthesis and export run post-crawl)"""
    
    workflow = StateGraph(AuditState)
    
    # Add per-URL processing nodes
    workflow.add_node("ingestion", ingestion_node)
    workflow.add_node("orchestrator", orchestrator_node)
    workflow.add_node("worker", worker_node)
    workflow.add_node("state_updater", state_updater_node)
    
    # Define entry point
    workflow.set_entry_point("ingestion")
    
    # Linear flow: ingest pre-crawled HTML -> plan -> execute -> collect metrics -> end
    workflow.add_edge("ingestion", "orchestrator")
    workflow.add_edge("orchestrator", "worker")
    workflow.add_edge("worker", "state_updater")
    workflow.add_edge("state_updater", END)
    
    return workflow.compile()