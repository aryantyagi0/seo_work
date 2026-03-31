"""
LangGraph node implementations for V4 orchestrator
"""
import json
import asyncio
from typing import Dict, Any
from graph.state import AuditState
from utils.logging_config import get_logger
from utils.crawler_config import build_page_context
from agents.planner_agent import PlannerAgent
from agents.writer_agent import WriterAgent
from tools.primitives_executor import execute_primitive_chain
from tools.fallback_checks import DEDICATED_CHECKS
from config.settings import (
    LIGHTHOUSE_COLUMNS, SERVER_LOG_COLUMNS,
    FALLBACK_ENABLED, WRITER_MAX_RAW_CHARS,
    PLANNER_BATCH_SIZE, WORKER_BATCH_SIZE,
)

logger = get_logger("Nodes")

# Singleton agents - created once, reused across all URLs
_planner_instance: PlannerAgent = None
_writer_instance: WriterAgent = None


def _get_planner() -> PlannerAgent:
    global _planner_instance
    if _planner_instance is None:
        _planner_instance = PlannerAgent()
    return _planner_instance


def _get_writer() -> WriterAgent:
    global _writer_instance
    if _writer_instance is None:
        _writer_instance = WriterAgent()
    return _writer_instance


async def ingestion_node(state: AuditState) -> AuditState:
    """Initialize page context from Knowledge Base. Falls back to live crawl if needed."""
    url = state["url"]
    logger.info(f"Setting up context for: {url}")

    # Check for pre-crawled HTML from Knowledge Base (set by app.py Phase 1)
    pre = state.get("page_context", {})
    html = pre.get("html", "")
    status_code = pre.get("status_code")

    if not html:
        # Fallback: live crawl if Knowledge Base didn't provide HTML
        logger.warning(f"No pre-crawled HTML for {url}, fetching live")
        page_context = await build_page_context(url)
        state["page_context"] = {
            "url": url,
            "html": page_context.get("html", ""),
            "status_code": page_context.get("status_code"),
            "error": page_context.get("error"),
            "redirect_chain": page_context.get("redirect_chain", []),
            "final_url": page_context.get("final_url"),
        }
        html = page_context.get("html", "")
        status_code = page_context.get("status_code")
    else:
        logger.info(f"  Using pre-crawled HTML ({len(html)} chars)")

    state["intermediate_vars"] = {
        "page_html": html,
        "current_url": url,
        "status_code": status_code,
        "redirect_chain": pre.get("redirect_chain", []),
    }
    state["current_node"] = "orchestrator"

    return state


async def orchestrator_node(state: AuditState) -> AuditState:
    """Generate execution plans for each column. Plans columns in parallel."""
    logger.info(f"Planning execution for {len(state['column_headers'])} columns")
    
    planner = _get_planner()
    execution_plans = {}
    columns_to_plan = []
    
    for column in state["column_headers"]:
        # Check bypass conditions
        if any(kw in column for kw in LIGHTHOUSE_COLUMNS):
            execution_plans[column] = {
                "bypass": True,
                "status": "Not Audited",
                "reason": "Lighthouse functionality disabled"
            }
            logger.info(f"Bypassing column: {column} (Lighthouse)")
            continue
        
        if any(kw in column for kw in SERVER_LOG_COLUMNS):
            execution_plans[column] = {
                "bypass": True,
                "status": "Not Audited",
                "reason": "Requires backend server access"
            }
            logger.info(f"Bypassing column: {column} (Server logs)")
            continue
        
        # EEAT assessment only applicable to blog/article pages
        if "EEAT" in column.upper() or "E-E-A-T" in column.upper():
            url_path = state["url"].lower()
            blog_indicators = ["/blog", "/post", "/article", "/news", "/insights", "/resources", "/guides", "/learn"]
            is_blog = any(indicator in url_path for indicator in blog_indicators)
            if not is_blog:
                execution_plans[column] = {
                    "bypass": True,
                    "status": "N/A",
                    "reason": "EEAT is only applicable to blog/article pages"
                }
                logger.info(f"Bypassing column: {column} (Non-blog page)")
                continue
        
        # FAQ schema only applicable to blog pages
        if "FAQ" in column.upper() and "BLOG" in column.upper():
            url_path = state["url"].lower()
            blog_indicators = ["/blog", "/post", "/article", "/news", "/insights", "/resources", "/guides", "/learn"]
            is_blog = any(indicator in url_path for indicator in blog_indicators)
            if not is_blog:
                execution_plans[column] = {
                    "bypass": True,
                    "status": "N/A",
                    "reason": "FAQ In Blog check is only applicable to blog/article pages"
                }
                logger.info(f"Bypassing column: {column} (Non-blog page)")
                continue
        
        columns_to_plan.append(column)
    
    # Plan columns in batches for efficiency (larger batches = more parallel LLM calls)
    BATCH_SIZE = PLANNER_BATCH_SIZE
    for i in range(0, len(columns_to_plan), BATCH_SIZE):
        batch = columns_to_plan[i:i + BATCH_SIZE]
        logger.info(f"Planning batch {i // BATCH_SIZE + 1}: {len(batch)} columns")
        
        tasks = [
            planner.generate_plan(
                column_name=col,
                intermediate_vars=state["intermediate_vars"]
            )
            for col in batch
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for col, result in zip(batch, results):
            if isinstance(result, Exception):
                logger.error(f"Plan failed for {col}: {result}")
                execution_plans[col] = {"column": col, "operations": [], "error": str(result)}
            else:
                execution_plans[col] = result
    
    state["execution_plans"] = execution_plans
    state["current_node"] = "worker"
    
    return state


def _is_result_valid(result: Dict[str, Any]) -> bool:
    """Check if primitive chain result is valid and not empty or erroneous."""
    if not result:
        return False
    if "error" in result:
        return False
    raw = result.get("raw_data", {})
    if not raw:
        return False

    # Check if raw_data contains non-empty values
    non_empty = [v for v in raw.values() if v is not None and v != "" and v != [] and v != {}]
    if len(non_empty) == 0:
        return False

    # Deep validation: check for error indicators in raw_data values
    for key, val in raw.items():
        # Detect VALIDATE error results
        if isinstance(val, dict):
            errors = val.get("errors", [])
            if errors and isinstance(errors, list) and len(errors) > 0:
                # Error messages present → invalid
                return False
            # Check for invalid status
            if val.get("valid") is False and not val.get("details"):
                return False

        # Detect string error markers
        if isinstance(val, str) and any(marker in val.lower() for marker in [
            "slice(", "error", "traceback", "exception", "not implemented"
        ]):
            return False

        # Detect slice objects
        if isinstance(val, slice):
            return False

    return True


async def worker_node(state: AuditState) -> AuditState:
    """Execute primitive chains for each column in parallel. Falls back to deterministic checks on failure."""
    logger.info(f"Executing primitive chains for {len(state['execution_plans'])} columns")
    
    raw_metrics = {}
    url = state["url"]
    html = state.get("intermediate_vars", {}).get("page_html", "")
    
    # Process columns in parallel batches
    columns_to_process = []
    for column, plan in state["execution_plans"].items():
        if plan.get("bypass"):
            raw_metrics[column] = {
                "status": plan["status"],
                "reason": plan["reason"]
            }
        else:
            columns_to_process.append(column)
    
    BATCH_SIZE = WORKER_BATCH_SIZE
    for batch_idx in range(0, len(columns_to_process), BATCH_SIZE):
        batch = columns_to_process[batch_idx:batch_idx + BATCH_SIZE]
        logger.info(f"Processing batch {batch_idx // BATCH_SIZE + 1}: {len(batch)} columns")
        
        # Process batch in parallel
        tasks = [
            _process_column(
                column=col,
                plan=state["execution_plans"][col],
                url=url,
                html=html,
                intermediate_vars=state["intermediate_vars"],
                faiss_results=state.get("faiss_results", {})
            )
            for col in batch
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Collect results
        for col, result in zip(batch, results):
            if isinstance(result, Exception):
                logger.error(f"Error processing {col}: {result}")
                raw_metrics[col] = {"error": str(result)}
            else:
                raw_metrics[col] = result
                # Update intermediate vars if result contains new variables
                if result and result.get("new_vars"):
                    state["intermediate_vars"].update(result["new_vars"])
    
    state["raw_metrics"] = raw_metrics
    state["current_node"] = "state_updater"
    
    return state


async def _process_column(column: str, plan: Dict, url: str, html: str, 
                         intermediate_vars: Dict, faiss_results: Dict) -> Dict[str, Any]:
    """Process a single column using dedicated check or primitive chain."""
    result = None

    # Try dedicated check first (most reliable, deterministic logic)
    if FALLBACK_ENABLED:
        fallback_fn = DEDICATED_CHECKS.get(column)
        if fallback_fn:
            try:
                # For 404 and redirect checks, use pre-crawled data instead of re-fetching
                if column == "404 Errors":
                    status_code = intermediate_vars.get("status_code")
                    if status_code is not None:
                        is_404 = status_code == 404
                        fb_result = {
                            "status": "No" if is_404 else "Yes",
                            "raw_data": {
                                "status_code": status_code,
                                "is_404": is_404,
                                "reason": f"Page returned HTTP {status_code}" if is_404
                                          else f"Page returned HTTP {status_code} (not a 404)",
                                "source": "pre-crawled",
                            },
                        }
                        result = {
                            "status": "Completed",
                            "raw_data": fb_result["raw_data"],
                            "new_vars": {},
                            "fallback_status": fb_result["status"],
                        }
                        logger.info(f"Dedicated check for: {column} → {fb_result['status']} (pre-crawled)")
                        return result

                elif column in ("Avoid redirect chains/loops", "Avoid Redirect Chains/Loops"):
                    redirect_chain = intermediate_vars.get("redirect_chain", [])
                    if redirect_chain is not None:
                        has_chain = len(redirect_chain) > 1
                        final_url_val = intermediate_vars.get("current_url", url)
                        has_loop = final_url_val.rstrip("/") == url.rstrip("/") and len(redirect_chain) > 0
                        if has_chain or has_loop:
                            fb_status = "No"
                            reason = (
                                f"Redirect chain detected with {len(redirect_chain)} hop(s): "
                                f"{' → '.join(redirect_chain[:5])} → {final_url_val}"
                            )
                        else:
                            fb_status = "Yes"
                            reason = "No redirect chains or loops detected."
                        fb_result = {
                            "status": fb_status,
                            "raw_data": {
                                "redirect_count": len(redirect_chain),
                                "redirect_chain": redirect_chain[:10],
                                "final_url": final_url_val,
                                "has_chain": has_chain,
                                "has_loop": has_loop,
                                "reason": reason,
                                "source": "pre-crawled",
                            },
                        }
                        result = {
                            "status": "Completed",
                            "raw_data": fb_result["raw_data"],
                            "new_vars": {},
                            "fallback_status": fb_result["status"],
                        }
                        logger.info(f"Dedicated check for: {column} → {fb_result['status']} (pre-crawled)")
                        return result

                fb_result = await fallback_fn(url, html)
                if fb_result and fb_result.get("raw_data"):
                    result = {
                        "status": "Completed",
                        "raw_data": fb_result.get("raw_data", fb_result),
                        "new_vars": {},
                        "fallback_status": fb_result.get("status", "Unknown"),
                    }
                    logger.info(f"Dedicated check for: {column} → {fb_result.get('status')}")
                    return result
            except Exception as e:
                logger.warning(f"Dedicated check failed for {column}: {e}, trying primitives")

    # Fall back to LLM-planned primitive chain
    try:
        operations = plan.get("operations", [])
        if operations:
            result = await execute_primitive_chain(
                operations=operations,
                intermediate_vars=intermediate_vars,
                faiss_results=faiss_results
            )
    except Exception as e:
        logger.error(f"Primitive chain error for {column}: {e}")
        result = {"error": str(e)}

    if not _is_result_valid(result):
        result = {"error": f"No valid result for {column}"}
    
    return result


async def state_updater_node(state: AuditState) -> AuditState:
    """Complete per-URL processing and prepare for synthesis phase."""
    logger.info(f"Per-URL processing complete with {len(state['raw_metrics'])} results")
    
    # All columns processed — graph ends, synthesis runs in app.py after postcrawl
    state["current_node"] = "complete"
    
    return state


def _truncate_raw_metrics(raw_data: Dict[str, Any], max_chars: int) -> Dict[str, Any]:
    """Truncate large strings and collections to prevent writer LLM context overflow."""
    # Remove huge HTML strings from raw data
    cleaned = {}
    for k, v in raw_data.items():
        if isinstance(v, str) and len(v) > 2000:
            cleaned[k] = v[:2000] + "... [truncated]"
        elif isinstance(v, dict):
            cleaned[k] = _truncate_raw_metrics(v, max_chars)
        elif isinstance(v, list) and len(v) > 20:
            cleaned[k] = v[:20]  # Cap lists at 20 items
        else:
            cleaned[k] = v
    
    # Final check on total size
    serialized = json.dumps(cleaned, default=str)
    if len(serialized) > max_chars:
        cleaned["_note"] = f"Data truncated from {len(serialized)} to {max_chars} chars"
        # Keep only the most important keys
        important_keys = ["status", "valid", "details", "errors", "fallback_status",
                          "raw_data", "summary", "reason", "tags_found"]
        trimmed = {k: v for k, v in cleaned.items() if k in important_keys or not isinstance(v, (str, list, dict))}
        if trimmed:
            cleaned = trimmed
    
    return cleaned


async def synthesis_node(state: AuditState) -> AuditState:
    """Generate human-readable summaries from raw metrics in parallel."""
    logger.info(f"Generating summaries for {len(state['raw_metrics'])} columns")
    
    writer = _get_writer()
    summaries = {}
    
    # Separate simple vs. complex columns
    complex_columns = []
    
    for column, raw_data in state["raw_metrics"].items():
        if raw_data.get("status") == "Not Audited":
            summaries[column] = f"Not Audited: {raw_data.get('reason', '')}"
        elif raw_data.get("fallback_status") == "Pending post-crawl check":
            # Duplicate content check will be updated after post-crawl analysis
            summaries[column] = "Pending post-crawl duplicate detection (TF-IDF + FAISS)"
        elif "error" in raw_data and not raw_data.get("raw_data"):
            summaries[column] = f"Error: {raw_data['error']}"
        else:
            complex_columns.append((column, raw_data))
    
    # Process complex columns in parallel batches of 5
    BATCH_SIZE = 5
    for batch_idx in range(0, len(complex_columns), BATCH_SIZE):
        batch = complex_columns[batch_idx:batch_idx + BATCH_SIZE]
        logger.info(f"Writing batch {batch_idx // BATCH_SIZE + 1}: {len(batch)} summaries")
        
        tasks = [
            writer.generate_summary(
                column_name=col,
                raw_metrics=_truncate_raw_metrics(raw, WRITER_MAX_RAW_CHARS),
                url=state["url"]
            )
            for col, raw in batch
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for (col, _), result in zip(batch, results):
            if isinstance(result, Exception):
                logger.error(f"Writer error for {col}: {result}")
                summaries[col] = f"Error generating summary: {result}"
            else:
                summaries[col] = result
    
    state["summaries"] = summaries
    state["current_node"] = "export"
    
    return state


def export_node(state: AuditState) -> AuditState:
    """Prepare final results for export."""
    logger.info(f"Ready for export with {len(state['summaries'])} summaries")
    state["current_node"] = "complete"
    return state