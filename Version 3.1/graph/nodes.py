from typing import Dict, Any, List, Optional
from graph.state import AuditMap, AuditStatus

from tools.fetch_tool import fetch_html
from agents.dispatcher import DispatcherAgent
from agents.validator import ValidatorAgent
from agents.fallback_agent import FallbackAgent
from agents.query_resolver import QueryResolver
from agents.final_output_agent import FinalOutputAgent
from chatbot.explanation import ExplanationAgent
from agents.input_analyzer import InputAnalyzer
import json
import pandas as pd
import os
import re


def create_summary_dataframe(audit_map: AuditMap, criteria: dict) -> pd.DataFrame:
    """Transforms the audit map into a wide-format DataFrame for display."""
    records = []
    param_names = list(criteria.keys())

    for url, page_state in audit_map.pages.items():
        row = {"URL": url}
        for param_name in param_names:
            param_state = page_state.parameters.get(param_name)
            column_name = param_name.replace("_", " ").title()
            if param_state:
                if param_state.status.value == "validated":
                    row[column_name] = "PASSED"
                elif param_state.status.value == "failed":
                    llm_reason = param_state.llm_reasoning or param_state.remediation_suggestion or "No failure details available."
                    row[column_name] = f"FAILED\nReason: {llm_reason}"
                elif param_state.status.value == "extracted":
                    row[column_name] = "NEEDS_IMPROVEMENT"
                else:
                    row[column_name] = param_state.status.value.upper()
            else:
                row[column_name] = "NOT RUN"
        records.append(row)
    
    df = pd.DataFrame(records)
    if "URL" in df.columns:
        df = df.set_index("URL")
    return df

def create_detailed_csv(audit_map: AuditMap) -> bytes:
    """Creates a detailed report in a long-format string suitable for CSV."""
    records = []
    for url, page_state in audit_map.pages.items():
        for param_name, param_state in page_state.parameters.items():
            records.append({
                "URL": url,
                "Check": param_name,
                "Status": param_state.status.value,
                "Value": param_state.value if isinstance(param_state.value, str) else json.dumps(param_state.value),
                "Remediation": param_state.remediation_suggestion,
                "LLM Reasoning": param_state.llm_reasoning if param_state.llm_reasoning else ""
            })
    
    df = pd.DataFrame(records)
    return df.to_csv(index=False).encode('utf-8')

import re
import logging

def fetch_html_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fetches the HTML content for the current URL, checking the cache first.
    """
    current_url = state.get("current_url")
    audit_map: AuditMap = state["audit_map"] 

    dispatcher_agent = DispatcherAgent()
    cached_html = dispatcher_agent.get_cached_html(current_url)

    if cached_html:
        logging.info(f"Using cached HTML for {current_url}")
        html_content = cached_html
    else:
        logging.info(f"Cache miss for {current_url}. Fetching live...")
        html_content = fetch_html(current_url)

    if not html_content or html_content.startswith("Error fetching URL"):
        logging.info(f"Error fetching {current_url}: {html_content}")
        page_state = audit_map.get_page_state(current_url)
        if page_state:
            for param_name in page_state.parameters:
                audit_map.update_parameter_state(
                    current_url, param_name,
                    status=AuditStatus.FAILED,
                    remediation_suggestion=f"Failed to fetch HTML: {html_content}"
                )
        return {**state, "audit_map": audit_map, "html_content": None, "fetch_success": False}

    logging.info(f"Fetched HTML for {current_url}")
    return {**state, "audit_map": audit_map, "html_content": html_content, "fetch_success": True}

async def pre_crawl_batch_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Performs a batch fetch and extraction for all discovered URLs to populate the cache.
    """
    urls_to_process = state.get("urls_to_process", [])
    audit_map = state["audit_map"]

    if not urls_to_process:
        return state

    dispatcher_agent = DispatcherAgent()
    await dispatcher_agent.pre_crawl_and_extract_batch(urls_to_process, audit_map)

    return state

def dispatch_extraction_node(state: Dict[str, Any]) -> Dict[str, Any]:

    """
    Dispatches HTML extraction tasks using the DispatcherAgent.
    """
    current_url = state.get("current_url")
    html_content = state.get("html_content")
    audit_map: AuditMap = state["audit_map"] 
    
    if html_content is None:
        logging.info(f"Skipping extraction for {current_url} due to no HTML content.")
        return {**state, "audit_map": audit_map}

    dispatcher_agent = DispatcherAgent()
    if not audit_map.get_page_state(current_url):
        audit_map.add_page(current_url, list(dispatcher_agent.criteria.keys()))

    dispatcher_agent.dispatch_extraction(audit_map, current_url, html_content)
    
    logging.info(f"Dispatched extraction for {current_url}")
    return {**state, "audit_map": audit_map}

def validate_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validates extracted data using the ValidatorAgent.
    """
    current_url = state.get("current_url")
    audit_map: AuditMap = state["audit_map"] 
    
    validator_agent = ValidatorAgent()
    validator_agent.validate_page(audit_map, current_url)
    
    logging.info(f"Validated page for {current_url}")
    return {**state, "audit_map": audit_map}

def fallback_check_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Checks if any parameters require fallback action.
    """
    current_url = state.get("current_url")
    audit_map: AuditMap = state["audit_map"] 
    
    fallback_agent = FallbackAgent()
    fallback_agent.check_for_fallback(audit_map)
    
    page_state = audit_map.get_page_state(current_url)
    fallbacks_needed = False
    if page_state:
        for param_name, param_state in page_state.parameters.items():
            status_value = param_state.status.value if hasattr(param_state.status, "value") else str(param_state.status)
            if status_value == AuditStatus.REQUIRES_FALLBACK_TOOL.value:
                fallbacks_needed = True
                break
    
    logging.info(f"Fallback check for {current_url}. Fallbacks needed: {fallbacks_needed}")
    return {**state, "audit_map": audit_map, "fallbacks_needed": fallbacks_needed}

def fallback_tool_execution_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executes fallback tools for parameters marked as REQUIRES_FALLBACK_TOOL.
    Performs a single advanced JS-rendered recrawl as a 'Plan B'.
    If successful, re-runs extraction and validation.
    """
    current_url = state.get("current_url")
    audit_map: AuditMap = state["audit_map"] 
    
    explanation_agent = ExplanationAgent()
    dispatcher_agent = DispatcherAgent()
    validator_agent = ValidatorAgent()

    page_state = audit_map.get_page_state(current_url)
    if not page_state:
        return {**state, "audit_map": audit_map}

    params_needing_fallback = [
        param_name for param_name, param_state in page_state.parameters.items()
        if (param_state.status.value if hasattr(param_state.status, "value") else str(param_state.status)) == AuditStatus.REQUIRES_FALLBACK_TOOL.value
    ]

    if not params_needing_fallback:
        return {**state, "audit_map": audit_map}

    logging.info(f" \nStarting Advanced Fallback for {current_url}" )
    logging.info(f"  Target parameters: {', '.join(params_needing_fallback)}")

    # Level 1: Advanced Recrawl with JS Rendering
    logging.info(f"  Attempting JS-rendered recrawl via Crawl4AI...")
    try:
        from tools.html_tools.crawl_tool import crawl_page_content
        import asyncio
        import nest_asyncio
        nest_asyncio.apply()
        
        new_html = asyncio.run(crawl_page_content.ainvoke({"url": current_url, "render_js": True}))
        
        if new_html and not new_html.startswith("Error crawling") and not "did not return HTML content" in new_html:
            logging.info(f"  Successfully retrieved rendered HTML ({len(new_html)} chars). Re-dispatching extraction...")
            
            # Level 2: Re-dispatch extraction for only the failed parameters
            dispatcher_agent.dispatch_extraction(audit_map, current_url, new_html, allowed_params=params_needing_fallback)
            
            # Level 3: Re-validate the newly extracted data
            validator_agent.validate_page(audit_map, current_url)
            logging.info(f"  Extraction and validation re-run complete.")
        else:
            logging.info(f"  Advanced recrawl failed or returned no content: {new_html[:100]}...")
            
    except Exception as e:
        logging.info(f"  Error during advanced fallback execution: {e}")

    # Final Check: If any parameters are still in a fallback state or failed, generate explanations
    page_state = audit_map.get_page_state(current_url)
    for param_name in params_needing_fallback:
        param_state = page_state.parameters.get(param_name)
        if param_state:
            status_value = param_state.status.value if hasattr(param_state.status, "value") else str(param_state.status)
            if status_value in [AuditStatus.REQUIRES_FALLBACK_TOOL.value, AuditStatus.FALLBACK_NEEDED.value]:
                logging.info(f"  Advanced fallback unsuccessful for '{param_name}'. Generating LLM explanation...")
                
                original_rule = dispatcher_agent.criteria.get(param_name, {})
                llm_explanation = explanation_agent.generate_explanation(
                    url=current_url,
                    param_name=param_name,
                    value=param_state.value,
                    rule={
                        "validation_type": "Critical Failure",
                        "validation_params": original_rule.get("validation_params", {}),
                        "remediation": f"Standard and Advanced (JS-rendered) extraction failed. "
                                      f"Possible causes: Bot protection, cloaking, or non-indexable content. "
                                      f"Original error: {param_state.remediation_suggestion}"
                    }
                )

                audit_map.update_parameter_state(
                    current_url, param_name,
                    status=AuditStatus.FAILED,
                    remediation_suggestion=llm_explanation,
                    llm_reasoning=llm_explanation
                )

    logging.info(f" Advanced Fallback completed for {current_url} \n")
    return {**state, "audit_map": audit_map}

import logging
def report_generation_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generates summary and detailed reports from the final AuditMap state.
    """
    audit_map: AuditMap = state["audit_map"] 
    final_output_agent = FinalOutputAgent()
    excel_result = final_output_agent.generate_excel_report(audit_map.to_dict())
    report_path = excel_result.get("report_path")
    audit_id = excel_result.get("audit_id")
    pdf_report_path = None
    try:
        pdf_result = final_output_agent.generate_pdf_report(audit_map.to_dict(), audit_id=audit_id)
        if pdf_result:
            pdf_report_path = pdf_result.get("report_path")
    except Exception as e:
        logging.error(f"PDF generation failed: {e}", exc_info=True)
    summary_df = final_output_agent.build_report_dataframe(audit_map.to_dict(), use_multiindex=True)
    detailed_csv = create_detailed_csv(audit_map)

    logging.info("Reports generated.")
    return {
        **state,
        "audit_map": audit_map,
        "summary_df": summary_df,
        "detailed_csv": detailed_csv,
        "excel_report_path": report_path,
        "pdf_report_path": pdf_report_path,
    }


def llm_chat_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Interacts with GPT-4o-mini to interpret user queries and decide on actions.
    Delegates to ChatbotAgent for core logic.
    """
    user_query = state.get("user_query")
    audit_map: AuditMap = state["audit_map"]

    # Instantiate the required agents
    dispatcher_agent = DispatcherAgent()
    fallback_agent = FallbackAgent()
    input_analyzer = InputAnalyzer() # Instantiate InputAnalyzer
    final_output_agent = FinalOutputAgent()
    explanation_agent = ExplanationAgent()

    # Pass the instantiated agents to the QueryResolver constructor
    query_resolver = QueryResolver(
        dispatcher_agent=dispatcher_agent,
        fallback_agent=fallback_agent,
        input_analyzer=input_analyzer,
        final_output_agent=final_output_agent,
        explanation_agent=explanation_agent
    )
    result = query_resolver.resolve(user_query, audit_map)
    
    # Update the state with the results from the ChatbotAgent
    return {
        **state,
        "llm_decision": result["llm_decision"],
        "chatbot_response": result["chatbot_response"],
        "audit_limit": result["audit_limit"]
    }
