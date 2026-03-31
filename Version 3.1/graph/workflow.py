from typing import TypedDict, List, Optional, Any, Dict
from graph.state import AuditMap, AuditStatus
from langgraph.graph import StateGraph, END
import sys
import os
import streamlit as st 
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from graph.nodes import (
    fetch_html_node,
    dispatch_extraction_node,
    validate_node,
    fallback_check_node,
    fallback_tool_execution_node,
    report_generation_node,
    llm_chat_node 
)
from agents.input_analyzer import InputAnalyzer 
from agents.dispatcher import DispatcherAgent 
from utils.audit_history_manager import save_audit_history 
from utils.llm_utils import call_llm_for_chatbot_reasoning # Import the function

class GraphState(TypedDict):
    user_query: Optional[str]
    audit_map: AuditMap
    urls_to_process: List[str] 
    current_url: Optional[str]
    html_content: Optional[str]
    fetch_success: Optional[bool]
    fallbacks_needed: Optional[bool]
    summary_df: Optional[Any] 
    detailed_csv: Optional[Any] 
    excel_report_path: Optional[str]
    pdf_report_path: Optional[str]
    llm_decision: Optional[Dict[str, Any]] 
    chatbot_response: Optional[str] 
    audit_limit: Optional[int] 

def create_audit_single_url_workflow():
    workflow = StateGraph(GraphState)
    workflow.add_node("fetch_html", fetch_html_node)
    workflow.add_node("dispatch_extraction", dispatch_extraction_node)
    workflow.add_node("validate", validate_node)
    workflow.add_node("fallback_check", fallback_check_node)
    workflow.add_node("fallback_tool_execution", fallback_tool_execution_node)

    workflow.set_entry_point("fetch_html")
    workflow.add_edge("fetch_html", "dispatch_extraction")
    workflow.add_edge("dispatch_extraction", "validate")
    workflow.add_conditional_edges(
        "fallback_check",
        lambda state: "fallback_tool_execution" if state.get("fallbacks_needed") else END,
        {
            "fallback_tool_execution": "fallback_tool_execution",
            END: END
        }
    )
    workflow.add_edge("fallback_tool_execution", END)
    return workflow.compile()

AUDIT_SINGLE_URL_WORKFLOW = create_audit_single_url_workflow()

def manage_multi_url_audit_node(state: GraphState) -> GraphState:
    audit_map: AuditMap = state["audit_map"]
    initial_url = state["llm_decision"]["url"] 
    audit_limit = state.get("llm_decision", {}).get("limit", state.get("audit_limit", 10))

    if "chatbot_messages" not in st.session_state:
        st.session_state.chatbot_messages = []

    st.session_state.chatbot_messages.append({"role": "assistant", "content": f"Discovering pages from {initial_url}..."})

    input_analyzer = InputAnalyzer() # Instantiate InputAnalyzer
    crawler_result = input_analyzer.get_urls_to_audit(initial_url, limit=audit_limit)
    urls_to_audit = crawler_result.get("urls", [])
    crawler_status = crawler_result.get("status", "failed")
    crawler_reason = crawler_result.get("reason", "Unknown reason.")

    if not urls_to_audit:
        st.session_state.chatbot_messages.append({"role": "assistant", "content": f"Could not find URLs to audit. Status: {crawler_status}. Reason: {crawler_reason}. Auditing the initial URL only."})
        urls_to_audit = [initial_url]
    else:
        st.session_state.chatbot_messages.append({"role": "assistant", "content": f"Found {len(urls_to_audit)} URLs to audit. Status: {crawler_status}. Reason: {crawler_reason}"})

    # Prepare for audit
    dispatcher_agent = DispatcherAgent() 
    all_criteria_names = list(dispatcher_agent.criteria.keys())

    state["urls_to_process"] = urls_to_audit

    for url in urls_to_audit:
        audit_map.add_page(url, all_criteria_names)

    # --- NEW: PRE-CRAWL BATCH ---
    st.session_state.chatbot_messages.append({"role": "assistant", "content": f"Starting parallel pre-crawl of {len(urls_to_audit)} URLs..."})
    try:
        # Use the agent's internal async runner which handles nest_asyncio safely
        dispatcher_agent._run_async(dispatcher_agent.pre_crawl_and_extract_batch(urls_to_audit, audit_map))
    except Exception as e:
        import logging
        logging.error(f"Pre-crawl batch failed: {e}", exc_info=True)
        st.session_state.chatbot_messages.append({"role": "assistant", "content": f"Warning: Pre-crawl batch failed: {e}. Falling back to sequential fetch."})
    # ----------------------------

    if "audit_events" not in st.session_state:
        st.session_state.audit_events = []

    progress_bar = st.progress(0)
    for i, url in enumerate(urls_to_audit):
        st.session_state.chatbot_messages.append({"role": "assistant", "content": f"Auditing ({i+1}/{len(urls_to_audit)}): {url}"})

        current_url_state: GraphState = {
            "audit_map": audit_map,
            "urls_to_process": [], 
            "current_url": url,
            "html_content": None,
            "fetch_success": None,
            "fallbacks_needed": None,
            "summary_df": None,
            "detailed_csv": None,
            "excel_report_path": None,
            "pdf_report_path": None,
            "user_query": None, 
            "llm_decision": None,
            "chatbot_response": None, 
        }

        try:
            # Stream node activations for visualization
            for update in AUDIT_SINGLE_URL_WORKFLOW.stream(current_url_state, stream_mode="updates"):
                for node_name, state_delta in update.items():
                    st.session_state.audit_events.append(
                        {"url": url, "node": node_name, "delta": state_delta}
                    )
            progress_bar.progress(min((i + 1) / len(urls_to_audit), 1.0))
        except Exception as e:
            st.session_state.chatbot_messages.append({"role": "assistant", "content": f"Error auditing {url}: {e}"})
            page_state = audit_map.get_page_state(url)
            if page_state:
                for param_name in page_state.parameters:
                    audit_map.update_parameter_state(
                        url, param_name,
                        status=AuditStatus.FAILED,
                        remediation_suggestion=f"Overall audit failed for this URL: {e}"
                    )
    
    st.session_state.chatbot_messages.append({"role": "assistant", "content": "Full audit complete!"})

    final_state_with_reports = report_generation_node({"audit_map": audit_map}) 
    
    state["audit_map"] = final_state_with_reports["audit_map"]
    state["summary_df"] = final_state_with_reports["summary_df"]
    state["detailed_csv"] = final_state_with_reports["detailed_csv"]
    state["excel_report_path"] = final_state_with_reports["excel_report_path"]
    state["pdf_report_path"] = final_state_with_reports.get("pdf_report_path")
    # Only call LLM summary if explicitly enabled
    if os.getenv("ENABLE_LLM_SUMMARY", "").strip() == "1":
        summary_df_string = state["summary_df"].to_markdown() # Convert DataFrame to markdown string for LLM
        llm_audit_summary = call_llm_for_chatbot_reasoning(summary_df_string, state.get("user_query", ""))
        state["chatbot_response"] = llm_audit_summary
    
    # Save the audit map to persistent history
    save_audit_history(state["audit_map"])
    
    return state


def create_chatbot_workflow():
    workflow = StateGraph(GraphState)

    # Add nodes
    workflow.add_node("llm_chat_processor", llm_chat_node)
    workflow.add_node("manage_multi_url_audit", manage_multi_url_audit_node)

    # Set entry point for the chatbot interaction
    workflow.set_entry_point("llm_chat_processor")

    # Define conditional routing based on LLM's decision
    def route_llm_decision(state: GraphState) -> str:
        llm_decision = state.get("llm_decision")
        if llm_decision and llm_decision.get("action") == "START_AUDIT":
            return "manage_multi_url_audit"
       
        else: 
            return END

    workflow.add_conditional_edges(
        "llm_chat_processor",
        route_llm_decision,
        {
            "manage_multi_url_audit": "manage_multi_url_audit",
            END: END 
        }
    )

    # After managing the audit, the workflow ends (response is in chatbot_response, reports in state)
    workflow.add_edge("manage_multi_url_audit", END)

    return workflow.compile()
