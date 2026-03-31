from utils.url_404_handler import process_404_fallbacks, _is_404_like_issue, _build_deterministic_404_summary
import json
import streamlit as st
import asyncio
import io
from difflib import SequenceMatcher
from pathlib import Path
import re
from urllib.parse import urlparse, urlsplit, urlunsplit
import aiohttp
import xml.etree.ElementTree as ET
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from utils.excel_handler import read_excel_urls, write_excel_output
from graph.workflow import create_workflow
from graph.state import AuditState
from tools.knowledge_base import KnowledgeBase, set_knowledge_base
from tools.postcrawl_duplicates import (
    detect_title_duplicates,
    detect_description_duplicates,
    detect_image_duplicates,
    _build_merged_summary,
)
from agents.writer_agent import WriterAgent
from config.settings import (
    WRITER_MAX_RAW_CHARS,
    URL_BATCH_SIZE,
    WRITER_BATCH_SIZE,
    OPENAI_API_KEY,
    WRITER_MODEL,
    LLM_TIMEOUT,
)
from utils.logging_config import get_logger

logger = get_logger("StreamlitApp")
_TYPO_FALLBACK_LLM: ChatOpenAI | None = None


# ── Helpers (module-level so they are importable) ──

def _truncate_raw_metrics(raw_data: dict, max_chars: int) -> dict:
    """Truncate raw metrics to avoid writer LLM context overflow."""
    cleaned = {}
    for k, v in raw_data.items():
        if isinstance(v, str) and len(v) > 2000:
            cleaned[k] = v[:2000] + "... [truncated]"
        elif isinstance(v, dict):
            cleaned[k] = _truncate_raw_metrics(v, max_chars)
        elif isinstance(v, list) and len(v) > 20:
            cleaned[k] = v[:20]
        else:
            cleaned[k] = v

    serialized = json.dumps(cleaned, default=str)
    if len(serialized) > max_chars:
        cleaned["_note"] = f"Data truncated from {len(serialized)} to {max_chars} chars"
        important_keys = [
            "status", "valid", "details", "errors", "fallback_status",
            "raw_data", "summary", "reason", "tags_found",
        ]
        trimmed = {
            k: v for k, v in cleaned.items()
            if k in important_keys or not isinstance(v, (str, list, dict))
        }
        if trimmed:
            cleaned = trimmed
    return cleaned


async def run_audit_for_url(workflow, url: str, headers: list,
                            page_context: dict) -> dict:
    """Run per-URL graph with pre-crawled page context from Knowledge Base."""
    initial_state = AuditState(
        url=url,
        page_context=page_context,
        column_headers=headers,
        current_column=None,
        intermediate_vars={},
        execution_plans={},
        raw_metrics={},
        summaries={},
        faiss_results={},
        current_node="ingestion",
        errors=[],
    )

    try:
        final_state = await workflow.ainvoke(initial_state)
        return {
            "url": url,
            "raw_metrics": final_state.get("raw_metrics", {}),
            "page_context": final_state.get("page_context", {}),
            "errors": final_state.get("errors", []),
        }
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"Error auditing {url}: {e}\n{tb}")
        return {
            "url": url,
            "raw_metrics": {},
            "page_context": {},
            "errors": [str(e)],
        }


async def run_all_audits(urls, headers):
    """
    Full 5-phase audit pipeline matching the Dynamic SEO Audit workflow.

    Phase 1: Knowledge Base Construction  (crawl all URLs -> TF-IDF -> FAISS)
    Phase 2: Per-URL Audit Loop           (orchestrator -> worker -> state_updater)
    Phase 3: Post-Crawl Reconciler        (global FAISS similarity matrix + exact match)
    Phase 4: Synthesis Writer             (LLM summaries for ALL URLs, AFTER postcrawl)
    Phase 5: Return results for Export
    """
    progress_bar = st.progress(0)
    status_text = st.empty()

    # Phase 1: Knowledge Base Construction
    status_text.text("Phase 1: Building Knowledge Base (crawling all URLs)...")
    logger.info(f"Phase 1: Knowledge Base Construction ({len(urls)} URLs)")

    kb = KnowledgeBase()
    await kb.crawl_all(urls)
    progress_bar.progress(0.10)

    status_text.text("Phase 1: Building FAISS index (TF-IDF embeddings)...")
    kb.build_faiss_index()
    set_knowledge_base(kb)
    progress_bar.progress(0.15)
    logger.info("Phase 1 complete: FAISS Central Truth ready")
    # Phase 2: Per-URL Audit Loop (parallel batches)
    workflow = create_workflow()
    all_results = []

    for batch_start in range(0, len(urls), URL_BATCH_SIZE):
        batch_urls = urls[batch_start:batch_start + URL_BATCH_SIZE]
        status_text.text(
            f"Phase 2: Auditing batch {batch_start // URL_BATCH_SIZE + 1} "
            f"({batch_start + 1}-{batch_start + len(batch_urls)}/{len(urls)})"
        )
        logger.info(
            f"Phase 2: Parallel batch {batch_start // URL_BATCH_SIZE + 1}: "
            f"{len(batch_urls)} URLs"
        )

        # Build page contexts from KB for all URLs in the batch
        batch_tasks = []
        for url in batch_urls:
            pd = kb.get_page_data(url)
            page_context = {
                "html": pd.get("html", ""),
                "status_code": pd.get("status_code"),
                "final_url": pd.get("final_url", url),
                "redirect_chain": pd.get("redirect_chain", []),
                "error": pd.get("error"),
            }
            batch_tasks.append(
                run_audit_for_url(workflow, url, headers, page_context)
            )

        # Run batch in parallel
        batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
        for url, result in zip(batch_urls, batch_results):
            if isinstance(result, Exception):
                logger.error(f"Error auditing {url}: {result}")
                all_results.append({
                    "url": url,
                    "raw_metrics": {},
                    "page_context": {},
                    "errors": [str(result)],
                })
            else:
                all_results.append(result)
                logger.info(f"Completed audit for: {url}")

        progress_bar.progress(
            0.15 + 0.45 * min(batch_start + len(batch_urls), len(urls)) / len(urls)
        )

    # Phase 3: Post-Crawl Reconciler
    status_text.text("Phase 3: Post-crawl duplicate detection (FAISS similarity matrix)...")
    logger.info("Phase 3: Post-Crawl Reconciler")

    # 3a. Text similarity from KB's pre-built FAISS (same Central Truth)
    text_results = kb.compute_similarity_matrix()

    # 3b. Exact-match checks on meta title, description, images
    page_data_list = kb.get_all_page_data()
    title_results = detect_title_duplicates(page_data_list)
    desc_results = detect_description_duplicates(page_data_list)
    image_results = detect_image_duplicates(page_data_list)

    # 3c. Merge duplicate results into each URL's raw_metrics
    DUPLICATE_COLUMN = "Duplicate content check"
    for result in all_results:
        url = result["url"]
        text_dup = text_results.get(url, {"duplicate_content": "No", "similar_urls": ""})
        title_dup = title_results.get(url, {"has_duplicate": False, "duplicate_urls": []})
        desc_dup = desc_results.get(url, {"has_duplicate": False, "duplicate_urls": []})
        img_dup = image_results.get(url, {"duplicate_count": 0, "details": []})

        summary_text = _build_merged_summary(text_dup, title_dup, desc_dup, img_dup)
        has_any = (
            text_dup.get("duplicate_content", "No").startswith("Yes")
            or title_dup.get("has_duplicate", False)
            or desc_dup.get("has_duplicate", False)
            or img_dup.get("duplicate_count", 0) > 0
        )

        result["raw_metrics"][DUPLICATE_COLUMN] = {
            "status": "Completed",
            "raw_data": {
                "text_similarity": text_dup,
                "title_duplicates": title_dup,
                "desc_duplicates": desc_dup,
                "image_duplicates": img_dup,
                "merged_summary": summary_text,
            },
            "fallback_status": "No" if has_any else "Yes",
        }

    progress_bar.progress(0.65)
    logger.info("Phase 3 complete: Duplicate detection merged")

    # Enrich 404 results automatically
    status_text.text("Phase 3: Checking broken URLs and resolving fallbacks...")
    await process_404_fallbacks(all_results, urls)

    # Phase 4: Synthesis Writer (parallel across URLs)
    status_text.text("Phase 4: Generating expert summaries...")
    logger.info("Phase 4: Synthesis Writer (all URLs, all columns)")

    writer = WriterAgent()

    async def _write_summaries_for_url(result, writer):
        """Generate all summaries for a single URL."""
        url = result["url"]
        raw_metrics = result.get("raw_metrics", {})
        summaries = {}

        # Categorise columns
        columns_to_write = []
        for column, raw_data in raw_metrics.items():
            if raw_data.get("status") == "Not Audited":
                summaries[column] = f"Not Audited: {raw_data.get('reason', '')}"
            elif raw_data.get("status") == "N/A":
                summaries[column] = f"N/A: {raw_data.get('reason', '')}"
            elif (
                raw_data.get("fallback_status") == "Pending post-crawl check"
                and column != DUPLICATE_COLUMN
            ):
                summaries[column] = "Pending post-crawl check"
            elif "error" in raw_data and not raw_data.get("raw_data"):
                summaries[column] = f"Error: {raw_data['error']}"
            elif "404" in column and _is_404_like_issue(raw_data.get("raw_data", {})):
                summaries[column] = _build_deterministic_404_summary(
                    url=url,
                    raw_404=raw_data.get("raw_data", {}),
                )
            else:
                columns_to_write.append((column, raw_data))

        # Write summaries in parallel batches of WRITER_BATCH_SIZE
        for batch_start in range(0, len(columns_to_write), WRITER_BATCH_SIZE):
            batch = columns_to_write[batch_start:batch_start + WRITER_BATCH_SIZE]
            tasks = [
                writer.generate_summary(
                    column_name=col,
                    raw_metrics=_truncate_raw_metrics(raw, WRITER_MAX_RAW_CHARS),
                    url=url,
                )
                for col, raw in batch
            ]
            results_batch = await asyncio.gather(*tasks, return_exceptions=True)
            for (col, _), summary_result in zip(batch, results_batch):
                if isinstance(summary_result, Exception):
                    logger.error(f"Writer error for {col}: {summary_result}")
                    summaries[col] = f"Error generating summary: {summary_result}"
                else:
                    summaries[col] = summary_result

        result["summaries"] = summaries

    # Process URLs in parallel batches for writer too
    for batch_start in range(0, len(all_results), URL_BATCH_SIZE):
        batch = all_results[batch_start:batch_start + URL_BATCH_SIZE]
        writer_tasks = [
            _write_summaries_for_url(result, writer) for result in batch
        ]
        await asyncio.gather(*writer_tasks, return_exceptions=True)

        status_text.text(
            f"Phase 4: Summaries {min(batch_start + len(batch), len(all_results))}/{len(all_results)}"
        )
        progress_bar.progress(
            0.65 + 0.30 * min(batch_start + len(batch), len(all_results)) / len(all_results)
        )

    # Phase 5: Done — return for export
    progress_bar.progress(1.0)
    status_text.text("All 5 phases complete!")
    logger.info("Phase 5: All phases complete, ready for export")
    return all_results


# ── Streamlit UI (callable from unified app or standalone) ──

def run_v4_app():
    """
    Streamlit UI for V2 LLM Orchestrator.
    Callable from both standalone and unified app.
    """
    # Apply consistent styling matching the unified hub
    st.markdown(
        """
        <style>
        [data-testid="stAppViewContainer"] {
            background-color: #ffffff !important;
        }
        .main .block-container {
            background-color: #ffffff !important;
        }
        [data-testid="stSidebar"], [data-testid="stSidebarContent"] {
            background-color: #335c81 !important;
            color: #ffffff !important;
        }
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3,
        [data-testid="stSidebar"] .stRadio label,
        [data-testid="stSidebar"] span {
            color: #ffffff !important;
        }
        [data-testid="stSidebar"] .stRadio div[role="radiogroup"] {
            color: #ffffff !important;
        }
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
        unsafe_allow_html=True,
    )

    st.title("SEO Audit Tool V2 - LLM Orchestrator")
    st.markdown("**LangGraph + 10 Atomic Primitives**")

    # File upload
    uploaded_file = st.file_uploader(
        "Upload Excel file with URLs and column headers",
        type=["xlsx", "xls"]
    )

    if uploaded_file:
        try:
            file_bytes = io.BytesIO(uploaded_file.getbuffer())
            all_urls, headers = read_excel_urls(file_bytes)

            st.success(f"Found {len(all_urls)} URLs and {len(headers)} column headers")

            # URL Limit Slider
            st.markdown("---")
            st.subheader("Audit Settings")

            col1, col2 = st.columns([3, 1])

            with col1:
                url_limit = st.slider(
                    "Number of URLs to audit",
                    min_value=1,
                    max_value=len(all_urls),
                    value=min(10, len(all_urls)),
                    help="Limit the number of URLs to process (useful for testing or rate limiting)"
                )

            with col2:
                st.metric("Total Available", len(all_urls))
                st.metric("Will Audit", url_limit)

            # Slice URLs based on limit
            urls = all_urls[:url_limit]

            if url_limit < len(all_urls):
                st.info(f"Auditing first {url_limit} of {len(all_urls)} URLs")

            # Display preview
            with st.expander("Preview URLs and Headers"):
                st.write("**URLs to be audited:**")
                for i, url in enumerate(urls[:10], 1):
                    st.write(f"{i}. {url}")
                if len(urls) > 10:
                    st.write(f"... and {len(urls) - 10} more")

                st.write("**Column Headers:**", ", ".join(headers[:5]))
                if len(headers) > 5:
                    st.write(f"... and {len(headers) - 5} more")

            # Start audit button
            if st.button("Start Audit", type="primary"):
                st.info("Starting audit workflow...")

                try:
                    import nest_asyncio
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_closed():
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)

                    nest_asyncio.apply(loop)
                    all_results = loop.run_until_complete(run_all_audits(urls, headers))
                except Exception as e:
                    logger.error(f"Event loop error: {e}, trying asyncio.run()")
                    all_results = asyncio.run(run_all_audits(urls, headers))

                # Write to Excel
                st.info("Generating Excel report...")
                output_path = write_excel_output(all_results, headers)

                # Success
                st.success(f"Audit complete! Report saved to: {output_path}")

                # Download button
                with open(output_path, "rb") as f:
                    st.download_button(
                        label="Download Audit Report",
                        data=f,
                        file_name=Path(output_path).name,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )

                # Show summary
                st.markdown("---")
                st.markdown("### Audit Summary")
                success_count = sum(1 for r in all_results if not r["errors"])
                error_count = len(all_results) - success_count

                col1, col2, col3 = st.columns(3)
                col1.metric("Total Audited", len(urls))
                col2.metric("Successful", success_count)
                col3.metric("Errors", error_count)

                if error_count > 0:
                    with st.expander("View Errors", expanded=True):
                        for result in all_results:
                            if result["errors"]:
                                st.error(f"**{result['url']}**")
                                for error in result["errors"]:
                                    st.write(f"  - {error}")

        except Exception as e:
            st.error(f"Error reading Excel file: {e}")
            logger.error(f"Excel read error: {e}")

    else:
        st.info("Upload an Excel file to begin")

        st.markdown("---")
        st.markdown("### Instructions")
        st.markdown("""
        1. **Prepare and upload your Excel file:**

        2. **Upload and click "Start Audit"** to begin processing.

        3. **Use the slider** to limit the number of URLs (useful for testing with a small sample).
        """)

    # Footer
    st.markdown("---")


# ── Standalone entry point ──
# When run directly via `streamlit run app.py`, set page config and launch UI.
# When imported by unified app, only run_v4_app() is called (no auto-execution).

import sys as _sys

_main_file = getattr(_sys.modules.get("__main__"), "__file__", "") or ""
_is_standalone = "unified_app" not in _main_file

if _is_standalone:
    try:
        st.set_page_config(
            page_title="SEO Audit V2 - LLM Orchestrator",
            layout="wide"
        )
    except st.errors.StreamlitAPIException:
        pass  # Page config already set

    run_v4_app()
