import streamlit as st
import sys
import os
import json
import pandas as pd
from dotenv import load_dotenv
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)


from sentence_transformers import SentenceTransformer
import faiss  # or wherever faiss is used
model = SentenceTransformer('all-MiniLM-L6-v2')


load_dotenv() 

# Add the CURRENT directory ('Version 3') to the path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from graph.state import AuditMap # Still need AuditMap for global state
from agents.dispatcher import DispatcherAgent # Needed to get criteria names for report generation

# Import Langgraph components
from graph.workflow import create_chatbot_workflow, GraphState, manage_multi_url_audit_node # Import the new chatbot workflow
from graph.nodes import create_summary_dataframe, create_detailed_csv # Import helper functions from nodes

# --- UI Rendering Functions ---

def _render_chatbot_interface():
    st.header("Chatbot Interface")
    # Display chat messages
    for message in st.session_state.chatbot_messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])

    # User input
    user_query = st.chat_input("Your message:")
    return user_query

def _render_audit_results():
    st.subheader("Run Audit")
    url_input = st.text_input("Website URL", "https://www.example.com")
    audit_all = st.checkbox("Audit all discovered URLs", value=True)
    limit_value = None
    if not audit_all:
        limit_value = st.number_input("Max URLs to audit", min_value=1, max_value=500, value=10, step=1)
    run_audit = st.button("Run Audit")

    if run_audit and url_input:
        st.info(f"Starting audit for: {url_input}")
        initial_graph_state: GraphState = {
            "user_query": f"audit {url_input}",
            "audit_map": st.session_state.audit_map_global,
            "urls_to_process": [],
            "current_url": None,
            "html_content": None,
            "fetch_success": None,
            "fallbacks_needed": None,
            "summary_df": None,
            "detailed_csv": None,
            "excel_report_path": None,
            "pdf_report_path": None,
            "llm_decision": {"action": "START_AUDIT", "url": url_input, "limit": None if audit_all else int(limit_value)},
            "chatbot_response": None,
        }
        with st.spinner("Running audit..."):
            final_graph_state = manage_multi_url_audit_node(initial_graph_state)
        if final_graph_state.get("summary_df") is not None:
            st.session_state.summary_df = final_graph_state["summary_df"]
        if final_graph_state.get("detailed_csv") is not None:
            st.session_state.detailed_csv = final_graph_state["detailed_csv"]
        if final_graph_state.get("excel_report_path") is not None:
            st.session_state.excel_report_path = final_graph_state["excel_report_path"]
        if final_graph_state.get("pdf_report_path") is not None:
            st.session_state.pdf_report_path = final_graph_state["pdf_report_path"]

    # Display Aggregate Results as a Table if available
    if st.session_state.summary_df is not None:
        st.subheader("Audit Summary Table")
        st.dataframe(st.session_state.summary_df)

    if st.session_state.excel_report_path and not st.session_state.chatbot_enabled:
        if st.button("Enable Chatbot"):
            st.session_state.chatbot_enabled = True
            st.rerun() # Rerun to update the sidebar navigation

    if st.session_state.excel_report_path and os.path.exists(st.session_state.excel_report_path):
        st.subheader("Download Audit Report")
        with open(st.session_state.excel_report_path, "rb") as f:
            st.download_button(
                label="Download Excel Report",
                data=f.read(),
                file_name=os.path.basename(st.session_state.excel_report_path),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        if st.session_state.pdf_report_path and os.path.exists(st.session_state.pdf_report_path):
            with open(st.session_state.pdf_report_path, "rb") as f:
                st.download_button(
                    label="Download PDF Report",
                    data=f.read(),
                    file_name=os.path.basename(st.session_state.pdf_report_path),
                    mime="application/pdf",
                )

    if st.session_state.audit_events:
        st.subheader("Workflow Node Activations")
        for evt in st.session_state.audit_events[-100:]:
            st.write(f"{evt['url']} -> {evt['node']}")

# --- Streamlit App ---

st.set_page_config(page_title="SEO Audit Tool", layout="wide")
st.title("SEO Audit Tool")
st.markdown("Ask me to audit a URL (e.g., 'audit https://www.example.com') or about the status of a previous audit.")

# Initialize the Langgraph chatbot workflow once
chatbot_workflow = create_chatbot_workflow()

# Initialize session state variables if not already present
if "audit_map_global" not in st.session_state:
    st.session_state.audit_map_global = AuditMap()
if "chatbot_messages" not in st.session_state:
    st.session_state.chatbot_messages = [{"role": "assistant", "content": "Hello! How can I assist you with SEO auditing today?"}]
if "summary_df" not in st.session_state:
    st.session_state.summary_df = None
if "detailed_csv" not in st.session_state:
    st.session_state.detailed_csv = None
if "excel_report_path" not in st.session_state:
    st.session_state.excel_report_path = None
if "pdf_report_path" not in st.session_state:
    st.session_state.pdf_report_path = None
if "audit_events" not in st.session_state:
    st.session_state.audit_events = []
if "chatbot_enabled" not in st.session_state:
    st.session_state.chatbot_enabled = False

# --- Sidebar Navigation ---
with st.sidebar:
    st.title("Navigation")
    
    # Always include the "Audit" option
    navigation_options = ["Audit"]

    # Only include "Chatbot" if it has been explicitly enabled
    if st.session_state.chatbot_enabled:
        navigation_options.append("Chatbot")

    selected_view = st.radio("Go to", navigation_options)

# --- Main Content Area ---
user_query = None # Initialize user_query outside conditional rendering

if selected_view == "Chatbot":
    user_query = _render_chatbot_interface()
elif selected_view == "Audit":
    _render_audit_results()

# Process user query only if a query was made in the Chatbot interface
if user_query:
    st.session_state.chatbot_messages.append({"role": "user", "content": user_query})
    with st.chat_message("user"):
        st.write(user_query)

    # Prepare initial state for the chatbot workflow
    # Pass the global audit_map to the workflow
    initial_graph_state: GraphState = {
        "user_query": user_query,
        "audit_map": st.session_state.audit_map_global,
        "urls_to_process": [], 
        "current_url": None,
        "html_content": None,
        "fetch_success": None,
        "fallbacks_needed": None,
        "summary_df": None, 
        "detailed_csv": None, 
        "excel_report_path": None,
        "pdf_report_path": None,
        "llm_decision": None,
        "chatbot_response": None,
    }

    # Invoke the chatbot workflow
    # The workflow will update audit_map_global in place if an audit runs
    final_graph_state = chatbot_workflow.invoke(initial_graph_state)

    # Retrieve chatbot's response from the final state
    chatbot_response = final_graph_state.get("chatbot_response", "I'm sorry, I couldn't process that request.")
    
    # Append chatbot's response to messages
    st.session_state.chatbot_messages.append({"role": "assistant", "content": chatbot_response})
    with st.chat_message("assistant"):
        st.write(chatbot_response)

    # Check if reports were generated by the audit process
    if final_graph_state.get("summary_df") is not None:
        st.session_state.summary_df = final_graph_state["summary_df"]
    if final_graph_state.get("detailed_csv") is not None:
        st.session_state.detailed_csv = final_graph_state["detailed_csv"]
    if final_graph_state.get("excel_report_path") is not None:
        st.session_state.excel_report_path = final_graph_state["excel_report_path"]
    if final_graph_state.get("pdf_report_path") is not None:
        st.session_state.pdf_report_path = final_graph_state["pdf_report_path"]
