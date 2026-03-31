import streamlit as st
import sys
import os
import json
import pandas as pd
import asyncio
import io
import nest_asyncio
import subprocess
import time
import signal
import atexit
import argparse
from pathlib import Path
from dotenv import load_dotenv
import importlib

import warnings
warnings.filterwarnings("ignore", category=FutureWarning)


from sentence_transformers import SentenceTransformer
import faiss  # or wherever faiss is used
model = SentenceTransformer('all-MiniLM-L6-v2')

# Set page config at the very beginning
st.set_page_config(page_title="SEO Audit Suite Hub", layout="wide")

# --- COMPLETE CSS (For Worker Apps) ---
def apply_worker_styles():
    st.markdown(
        """
        <style>
        /* Base background for main content area only */
        [data-testid="stAppViewContainer"] {
            background-color: #ffffff !important;
        }
        
        /* Main content block */
        .main .block-container {
            background-color: #ffffff !important;
        }

        /* Sidebar Styling - Force Blue Background */
        [data-testid="stSidebar"], [data-testid="stSidebarContent"] {
            background-color: #335c81 !important;
            color: #ffffff !important;
        }
        
        /* Ensure all sidebar text is WHITE for visibility on blue */
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3,
        [data-testid="stSidebar"] .stRadio label,
        [data-testid="stSidebar"] span {
            color: #ffffff !important;
        }

        /* Style radio buttons in sidebar */
        [data-testid="stSidebar"] .stRadio div[role="radiogroup"] {
            color: #ffffff !important;
        }
        
        /* Input and Button styling in main area */
        h1, h2, h3, p, span, label, div, .stMarkdown {
            color: #335c81 !important;
        }
        
        .stButton>button {
            background-color: #335c81 !important;
            color: #ffffff !important;
            border: 1px solid #335c81 !important;
            font-weight: bold;
            border-radius: 8px;
            padding: 0.5rem 2rem;
        }

        /* Force white text for all internal button elements */
        .stButton>button * {
            color: #ffffff !important;
        }
        
        .stButton>button:hover {
            background-color: #2b4f6e !important;
            border-color: #2b4f6e !important;
        }
        
        .stTextInput input, .stNumberInput input {
            color: #335c81 !important;
            border-color: #335c81 !important;
            background-color: #E6F0FF !important;
        }

        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        .block-container {padding-top: 1rem !important;}
        </style>
        """,
        unsafe_allow_html=True
    )

# --- HUB CSS (For Landing Page) ---
def apply_hub_styles():
    st.markdown(
        """
        <style>
        .stApp {
            background-color: #f8fafc !important;
        }
        .hub-container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 2rem;
        }
        .hub-title {
            color: #1e3a8a;
            font-size: 3.5rem;
            font-weight: 800;
            text-align: center;
            margin-bottom: 0.5rem;
        }
        .hub-subtitle {
            color: #64748b;
            font-size: 1.25rem;
            text-align: center;
            margin-bottom: 4rem;
        }
        .version-card {
            background-color: #ffffff;
            border-radius: 20px;
            padding: 2.5rem;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.05);
            border: 1px solid #e2e8f0;
            height: 100%;
            transition: all 0.3s ease;
            display: flex;
            flex-direction: column;
            text-align: center;
        }
        .version-card:hover {
            transform: translateY(-8px);
            box-shadow: 0 20px 35px -10px rgba(0, 0, 0, 0.1);
            border-color: #3b82f6;
        }
        .version-icon {
            font-size: 3rem;
            margin-bottom: 1.5rem;
        }
        .version-title {
            color: #1e3a8a;
            font-size: 1.75rem;
            font-weight: 700;
            margin-bottom: 1rem;
        }
        .version-tag {
            display: inline-block;
            background-color: #dbeafe;
            color: #1e40af;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.875rem;
            font-weight: 600;
            margin-bottom: 1.5rem;
        }
        .version-desc {
            color: #475569;
            font-size: 1.05rem;
            line-height: 1.6;
            margin-bottom: 2rem;
            flex-grow: 1;
            text-align: left;
        }
        .launch-btn {
            display: block;
            background-color: #2563eb;
            color: white !important;
            padding: 1rem 2rem;
            border-radius: 12px;
            text-decoration: none;
            font-weight: 700;
            font-size: 1.1rem;
            transition: background-color 0.2s;
            border: none;
            cursor: pointer;
        }
        .launch-btn:hover {
            background-color: #1d4ed8;
            text-decoration: none;
        }
        [data-testid="stHeader"] {
            background: rgba(0,0,0,0);
        }
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        </style>
        """,
        unsafe_allow_html=True
    )

APP_ROOT = os.path.dirname(os.path.abspath(__file__))

def setup_version_environment(version_name):
    v3_path = os.path.normpath(os.path.join(APP_ROOT, "Version 3.1"))
    v4_path = os.path.normpath(os.path.join(APP_ROOT, "Version 4 (LLM Orchestrator)"))
    v5_path = os.path.normpath(os.path.join(APP_ROOT, "keyword_rank"))
    target_path = v3_path if version_name == "v3" else (v4_path if version_name == "v4" else v5_path)
    if target_path not in sys.path:
        sys.path.insert(0, target_path)
    env_path = os.path.join(target_path, ".env")
    load_dotenv(env_path, override=True) if os.path.exists(env_path) else load_dotenv()

# --- SHARED COMPONENTS ---
# (render_api_key_management removed)

# --- VERSION 1 LOGIC (V3.1) ---
def run_v3_1():
    setup_version_environment("v3")
    import importlib
    if "audit_map_global" not in st.session_state:
        st.session_state.audit_map_global = importlib.import_module("graph.state").AuditMap()
    if "chatbot_workflow_v3" not in st.session_state:
        st.session_state.chatbot_workflow_v3 = importlib.import_module("graph.workflow").create_chatbot_workflow()
    if "v3_graph_state" not in st.session_state:
        st.session_state.v3_graph_state = {"user_query": None, "audit_map": st.session_state.audit_map_global, "urls_to_process": [], "current_url": None, "html_content": None, "fetch_success": None, "fallbacks_needed": None, "summary_df": None, "detailed_csv": None, "excel_report_path": None, "pdf_report_path": None, "llm_decision": None, "chatbot_response": None}
    if "chatbot_messages" not in st.session_state:
        st.session_state.chatbot_messages = [{"role": "assistant", "content": "Hello! How can I assist you with SEO auditing today?"}]
    if "chatbot_enabled" not in st.session_state: st.session_state.chatbot_enabled = False
    if "v3_view" not in st.session_state: st.session_state.v3_view = "Audit"
    
    st.sidebar.title("V1: Agentic Assistant")
    v3_options = ["Audit"]
    if st.session_state.chatbot_enabled: v3_options.append("Chatbot")
    st.session_state.v3_view = st.sidebar.radio("Navigation", v3_options, index=v3_options.index(st.session_state.v3_view) if st.session_state.v3_view in v3_options else 0)


    st.title("SEO Audit Tool V1")
    st.caption("Agentic Workflow with Multi-URL Support")
    manage_multi_url_audit_node = importlib.import_module("graph.workflow").manage_multi_url_audit_node

    if st.session_state.v3_view == "Chatbot":
        for msg in st.session_state.chatbot_messages:
            with st.chat_message(msg["role"]): st.write(msg["content"])
        user_query = st.chat_input("Your message:")
        if user_query:
            st.session_state.chatbot_messages.append({"role": "user", "content": user_query})
            st.session_state.v3_graph_state.update({"user_query": user_query, "chatbot_response": None})
            with st.spinner("Thinking..."):
                st.session_state.v3_graph_state.update(st.session_state.chatbot_workflow_v3.invoke(st.session_state.v3_graph_state))
            st.session_state.chatbot_messages.append({"role": "assistant", "content": st.session_state.v3_graph_state.get("chatbot_response", "Error")})
            if st.session_state.v3_graph_state.get("llm_decision", {}).get("action") == "START_AUDIT":
                st.session_state.v3_view = "Audit"
            st.rerun()
    else:
        st.subheader("Run Audit")
        url_input = st.text_input("Website URL", "https://www.example.com")
        audit_all = st.checkbox("Audit all discovered URLs", value=True)
        limit_val = None if audit_all else st.number_input("Max URLs", 1, 500, 10)
        if st.button("Run Audit") and url_input:
            st.info(f"Starting audit for: {url_input}")
            st.session_state.v3_graph_state.update({"user_query": f"audit {url_input}", "llm_decision": {"action": "START_AUDIT", "url": url_input, "limit": limit_val}, "urls_to_process": [], "current_url": None, "html_content": None, "fetch_success": None, "fallbacks_needed": None, "chatbot_response": None})
            with st.spinner("Running audit..."):
                st.session_state.v3_graph_state.update(manage_multi_url_audit_node(st.session_state.v3_graph_state))

        if st.session_state.v3_graph_state.get("summary_df") is not None:
            st.subheader("Audit Summary Table")
            st.dataframe(st.session_state.v3_graph_state["summary_df"])
            if not st.session_state.chatbot_enabled and st.session_state.v3_graph_state.get("excel_report_path"):
                if st.button("Enable Chatbot"):
                    st.session_state.chatbot_enabled = True; st.session_state.v3_view = "Chatbot"; st.rerun()

        if st.session_state.v3_graph_state.get("excel_report_path") and os.path.exists(st.session_state.v3_graph_state["excel_report_path"]):
            st.subheader("Download Audit Report")
            c1, c2 = st.columns(2)
            with open(st.session_state.v3_graph_state["excel_report_path"], "rb") as f:
                c1.download_button("Download Excel Report", f.read(), os.path.basename(st.session_state.v3_graph_state["excel_report_path"]), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            if st.session_state.v3_graph_state.get("pdf_report_path") and os.path.exists(st.session_state.v3_graph_state["pdf_report_path"]):
                with open(st.session_state.v3_graph_state["pdf_report_path"], "rb") as f:
                    c2.download_button("Download PDF Report", f.read(), os.path.basename(st.session_state.v3_graph_state["pdf_report_path"]), "application/pdf")

# --- VERSION 2 LOGIC (V4) ---
def run_v4():
    setup_version_environment("v4")
    import importlib
    if "app" in sys.modules:
        del sys.modules["app"]
    run_v4_app = importlib.import_module("app").run_v4_app
    st.sidebar.title("V2: LLM Orchestrator")
    run_v4_app()

# --- VERSION 3 LOGIC (Keyword Rank) ---
def run_v5():
    setup_version_environment("v5")

    import requests
    import pandas as pd
    import importlib

    db_module = importlib.import_module("database")
    init_db = db_module.init_db
    save_result = db_module.save_result
    get_daily_rank_range = db_module.get_daily_rank_range

    init_db()

    st.sidebar.title("V3: Rank Tracker")
    st.title("Local SEO Rank Tracker")

    # ---------------- SIDEBAR SETTINGS ---------------- #
    with st.sidebar:
        st.header("Settings")

        cities = {
            "Ahmedabad": (23.02, 72.57),
            "Bangalore": (12.97, 77.59),
            "Chennai": (13.08, 80.27),
            "Delhi": (28.61, 77.20),
            "Gurugram": (28.45, 77.02),
            "Hyderabad": (17.38, 78.48),
            "Jaipur": (26.91, 75.78),
            "Kolkata": (22.57, 88.36),
            "Lucknow": (26.84, 80.94),
            "Mumbai": (19.07, 72.87),
            "Noida": (28.53, 77.39),
            "Pune": (18.52, 73.85)
        }

        city = st.selectbox("Select City", sorted(list(cities.keys())))

        # predefined areas
        predefined_areas = [
            "Sector 18",
            "Sector 62",
            "Sector 75",
            "Sector 137",
            "Sector 135"
        ]

        selected_areas = st.multiselect(
            "Select Areas",
            predefined_areas
        )

        custom_areas = st.text_input(
            "Custom Areas (comma separated)",
            "",
            help="Example: Sector 142, Sector 150"
        )

        brand = st.text_input("Brand", "Anytime Fitness")
        domain = st.text_input("Domain", "anytimefitness.co.in")
        method = st.radio("Search Engine", ["playwright", "serpapi"])
        serp_key = st.text_input("SerpApi Key", type="password") if method == "serpapi" else None

    # ---------------- MERGE AREAS ---------------- #

    custom_area_list = [a.strip() for a in custom_areas.split(",") if a.strip()]

    areas = list(set(selected_areas + custom_area_list))

    if not areas:
        areas = [""]

    # ---------------- BULK UPLOAD ---------------- #
    st.subheader("📂 Bulk Keyword Upload")

    uploaded_file = st.file_uploader(
        "Upload Excel File (Must contain 'keyword' column)",
        type=["xlsx"]
    )

    if uploaded_file:

        df_input = pd.read_excel(uploaded_file)

        required_cols = {"keyword"}

        if not required_cols.issubset(df_input.columns):
            st.error("Excel must contain the 'keyword' column")
            return

        st.success(f"{len(df_input)} rows loaded")

        if st.button("🚀 Run Bulk Rank Check", type="primary"):

            summary_rows = []
            organic_rows = []
            local_rows = []

            lat, lng = cities[city]

            total_jobs = len(df_input) * len(areas)
            job_done = 0

            progress = st.progress(0)

            for idx, row in df_input.iterrows():

                keyword = str(row["keyword"]).strip()

                for area in areas:

                    area = area.strip()

                    area_str = f"{area} " if area else ""
                    final_k = f"{keyword} in {area_str}{city}"

                    payload = {
                        "keyword": final_k,
                        "brand": brand,
                        "domain": domain,
                        "method": method,
                        "latitude": lat,
                        "longitude": lng,
                        "city": city,
                        "area": area,
                        "api_key": serp_key,
                    }

                    try:
                        res = requests.post(
                            "http://127.0.0.1:8001/rank",
                            json=payload,
                            timeout=60
                        ).json()

                        if "error" not in res:

                            save_result(res, city, area, lat, lng, brand, domain)

                            summary_rows.append({
                                "Keyword": keyword,
                                "Area": area,
                                "City": city,
                                "Final_Search_Query": final_k,
                                "Organic_Rank": res.get("organic_rank"),
                                "Local_Rank": res.get("local_rank"),
                                "Raw_Organic_Count": res.get("raw_organic_count"),
                                "Raw_Local_Count": res.get("raw_local_count")
                            })

                            for pos, link in enumerate(res.get("all_organic", []), start=1):
                                organic_rows.append({
                                    "Keyword": keyword,
                                    "Area": area,
                                    "Position": pos,
                                    "Link": link
                                })

                            for pos, name in enumerate(res.get("all_local", []), start=1):
                                local_rows.append({
                                    "Keyword": keyword,
                                    "Area": area,
                                    "Position": pos,
                                    "Business_Name": name
                                })

                    except Exception:
                        st.warning(f"Failed for keyword: {keyword} | Area: {area}")

                    job_done += 1
                    progress.progress(job_done / total_jobs)

            # -------- CREATE EXCEL -------- #
            df_summary = pd.DataFrame(summary_rows)
            df_organic = pd.DataFrame(organic_rows)
            df_local = pd.DataFrame(local_rows)

            output = io.BytesIO()

            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                df_summary.to_excel(writer, sheet_name="Summary", index=False)
                df_organic.to_excel(writer, sheet_name="Organic_Details", index=False)
                df_local.to_excel(writer, sheet_name="Local_Details", index=False)

            output.seek(0)

            st.success("✅ Bulk Rank Check Complete")

            st.download_button(
                "📥 Download Detailed Rank Report",
                data=output,
                file_name="bulk_rank_multi_area_report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        # ---------------- HISTORY ---------------- #
        st.divider()
        st.subheader("📈 View Keyword History")

        history_options = [
            f"{k} | {a}" for k in df_input["keyword"] for a in areas
        ]

        selected_row = st.selectbox(
            "Select Keyword + Area",
            history_options
        )

        if selected_row:
            selected_keyword, selected_area = selected_row.split(" | ")
            final_k = f"{selected_keyword} in {selected_area} {city}"

            hist, cols = get_daily_rank_range(final_k, city)

            if hist:
                df = pd.DataFrame(hist, columns=cols)
                df["date"] = pd.to_datetime(df["date"], errors="coerce")
                df = df.dropna(subset=["date"])

                st.line_chart(
                    df.set_index("date")[[
                        "min_organic_rank",
                        "max_organic_rank",
                        "min_local_rank",
                        "max_local_rank"
                    ]]
                )
            else:
                st.info("No ranking history found.")

# --- ORCHESTRATOR ---
@st.cache_resource
def launch_processes():
    procs = {}
    # 1. Start Streamlit Workers
    for mode, port in {"V1": 8502, "V2": 8503, "V3": 8504}.items():
        cmd = [sys.executable, "-m", "streamlit", "run", __file__, "--server.port", str(port), "--server.headless", "true", "--", "--mode", mode]
        procs[mode] = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
    
    # 2. Start V3 Backend API
    keyword_path = os.path.join(APP_ROOT, "keyword_rank")
    backend_cmd = [sys.executable, "-m", "uvicorn", "backend.api:app", "--port", "8001"]
    procs["V3_BACKEND"] = subprocess.Popen(backend_cmd, cwd=keyword_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    return procs

def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--mode", choices=["V1", "V2", "V3"]); args, _ = parser.parse_known_args()
    
    if args.mode:
        apply_worker_styles()
        if args.mode == "V1": run_v3_1()
        elif args.mode == "V2": run_v4()
        elif args.mode == "V3": run_v5()
    else:
        apply_hub_styles()
        procs = launch_processes()
        atexit.register(lambda: [p.terminate() for p in procs.values()])

        st.markdown('<div class="hub-container">', unsafe_allow_html=True)
        st.markdown('<div class="hub-title">SEO Audit Suite Hub</div>', unsafe_allow_html=True)
        st.markdown('<div class="hub-subtitle">Professional SEO Audit & Tracking Ecosystem</div>', unsafe_allow_html=True)

        col1, col2, col3 = st.columns(3)

        with col1:
            st.markdown(f"""
                <div class="version-card">
                    <div class="version-title">Agentic Assistant</div>
                    <div class="version-tag">Version 3.1</div>
                    <div class="version-desc">
                        Experience an interactive SEO audit powered by a conversational agent. 
                        Crawl entire websites, discuss findings in real-time, and generate 
                        professional PDF/Excel reports instantly.
                        <br><br>
                        <b>Features:</b>
                        <ul>
                            <li>AI Chatbot Interface</li>
                            <li>Automated Multi-URL Crawling</li>
                            <li>Excel & PDF Export</li>
                        </ul>
                    </div>
                    <a href="http://localhost:8502" target="_blank" class="launch-btn">Launch V1</a>
                </div>
            """, unsafe_allow_html=True)

        with col2:
            st.markdown(f"""
                <div class="version-card">
                    <div class="version-title">LLM Orchestrator</div>
                    <div class="version-tag">Version 4</div>
                    <div class="version-desc">
                        Enterprise-grade bulk analysis using LangGraph. Orchestrates 10+ 
                        atomic SEO primitives to perform deep technical audits on large sets of URLs 
                        uploaded via Excel.
                        <br><br>
                        <b>Features:</b>
                        <ul>
                            <li>Excel-driven Workflow</li>
                            <li>Duplicate Content Detection</li>
                            <li>AI Executive Summaries</li>
                        </ul>
                    </div>
                    <a href="http://localhost:8503" target="_blank" class="launch-btn">Launch V2</a>
                </div>
            """, unsafe_allow_html=True)

        with col3:
            st.markdown(f"""
                <div class="version-card">
                    <div class="version-title">Rank Tracker</div>
                    <div class="version-tag">Keyword Rank</div>
                    <div class="version-desc">
                        Hyper-local SEO monitoring tool. Track your brand's visibility 
                        in Google Search and Map Packs for specific locations. 
                        Visualize ranking history and monitor competition.
                        <br><br>
                        <b>Features:</b>
                        <ul>
                            <li>Map Pack Rank Tracking</li>
                            <li>City/Area Specific Search</li>
                            <li>Historical Performance Data</li>
                        </ul>
                    </div>
                    <a href="http://localhost:8504" target="_blank" class="launch-btn">Launch V3</a>
                </div>
            """, unsafe_allow_html=True)
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        with st.sidebar:
            st.title("Hub Controls")
            st.info("The Hub manages background processes for all versions. Keep this tab open while using the suite.")
            if st.button("Reset All Processes"):
                st.cache_resource.clear()
                st.rerun()

if __name__ == "__main__":
    main()
