import streamlit as st
import re
import json
import requests
import pandas as pd
from typing import Dict, Any, Optional, List, Tuple, Callable
from difflib import SequenceMatcher 
import logging
import asyncio
import nest_asyncio
from os import path
from urllib.parse import urlparse

from tools.fetch_tool import fetch_html, fetch_url_data
from graph.state import AuditMap, AuditStatus
from chatbot.explanation import ExplanationAgent
from agents.dispatcher import DispatcherAgent
from agents.fallback_agent import FallbackAgent
from agents.input_analyzer import InputAnalyzer
from agents.final_output_agent import FinalOutputAgent
from agents.validator import ValidatorAgent
from tools.html_tools.crawl_tool import crawl_page_content
from utils.audit_history_manager import find_audit_in_history
from utils.memory_store import find_exact_match, store_qa, get_last_question, get_chat_history
from kb.kb_manager import get_latest_report_path, get_latest_audit_data, find_latest_audit_for_url
from utils.llm_utils import call_llm_completion
from tools.seo_length_tool import calculate_seo_length
from chatbot.hybrid_retriever import HybridRetriever

DECISION_AGENT_PROMPT = """
You are the Decision Agent powering a cognitive SEO assistant. Your job is to decide the best course of action to answer the user's question.

You are given:
1. The user's question.
2. A detailed summary of available audit data (URL-specific parameters, statuses, and VALUES).
3. A list of available tools.

**CRITICAL RULES FOR ACCURACY:**
1.  **Exact URL Match Only**: You MUST only answer from the 'Available Audit Data' context if the URL in the query matches the URL in the context EXACTLY.
2.  **Surgical Tool Call**: If the user asks about a URL that is NOT in the 'Current Session Audit' or is 'missing/failed', you MUST call `get_parameter_detail`.
3.  **Multiple Parameters**: If the user asks for multiple things (e.g., "title and description"), pass ALL of them to the `parameters` list in a single `get_parameter_detail` call.
4.  **Dual Intent (Audit + Details)**: If the user says "audit X and tell me Y", you MUST call BOTH `start_audit` and `get_parameter_detail`. This allows the background audit to start while giving the user an immediate surgical answer.
5.  **Wait for Response**: Do NOT respond saying "Audit initiated" or "I will check" - you must trigger the tools and WAIT for the response from `get_parameter_detail`.
6.  **Comparison Queries**: If the user asks for "rest of pages", "other audited pages", or "all audited URLs", you MUST first call `get_audited_urls` to see what is available, then call `compare_urls` with all those URLs for the requested parameters.
7.  **Knowledge Base Search**: If a URL is NOT in the 'Current Session Audit' but is mentioned in the question, or if you need to know what we have previously audited, use `search_knowledge_base` to find facts across all historical audits.
8.  **No Guessing lengths**: If the query mentions "length", "characters", or "how long", you MUST call `calculate_seo_length` for the actual text or use the `get_parameter_detail` tool which auto-calculates it. NEVER estimate or count yourself.
9.  **Direct Answer**: ONLY if all requested data for all requested URLs is explicitly present and 'VALIDATED' in the context, respond directly.
10. **Typo/404/Similar URL Requests**: If the user mentions a possible typo, asks for similar URLs, or asks about 404s for a specific URL, you MUST call `get_parameter_detail` (include `errors_404` if asked). Do not answer directly.
11. **Sitemap Suggestions**: If the user asks for sitemap URLs or suggestions from the sitemap, you MUST call `get_sitemap_urls`.
"""

EXPLANATION_AGENT_PROMPT = """
You are the Explanation Agent. Your role is to craft a natural, conversational response based on the provided data.

### RULES FOR SEO FACTS:
1. **SELECTIVE USE**: You are provided with "Explicit SEO Length Facts". Only mention these character counts if the user specifically asked for "lengths," "character counts," or "how long" something is, or if the length is a primary concern for SEO optimization.
2. **NATURAL INTEGRATION**: When relevant, weave the exact numbers into your response (e.g., "The title is '...' which is 40 characters"). Do not create a separate list of lengths unless asked for a summary.
3. **GROUND TRUTH ONLY**: Use ONLY the numbers provided in the "Explicit SEO Length Facts" section. Never try to count characters yourself.
4. **AVOID REPETITION**: If the user didn't ask for lengths, do not include them just for the sake of it. Focus on the content and quality of the SEO parameters.
"""

SEO_DOMAIN_CHECK_PROMPT = """
Is the following query related to Search Engine Optimization (SEO), Web Analytics, Site Audits, E-commerce UI/UX, website structure (like homepages/sitemaps), or is it a follow-up question directly relevant to a previous SEO-related topic?
Respond with 'YES' if it is, and 'NO' if it is not.

Recent Conversation History:
{history}

New Query: {query}
"""

class QueryResolver:
    def __init__(self, dispatcher_agent, fallback_agent, input_analyzer, final_output_agent, explanation_agent):
        self.parameter_name_map = {
            "meta title": "meta_title", "title": "meta_title", "meta description": "meta_description",
            "meta desc": "meta_description", "canonical": "canonical_tag", "canonical tag": "canonical_tag",
            "og tags": "og_tags", "open graph": "og_tags", "og description": "og_tags",
            "open graph description": "og_tags", "og:description": "og_tags", "image alt": "image_alt_text",
            "image alt text": "image_alt_text", "alt text": "image_alt_text", "hidden content": "hidden_content",
            "keyword density": "keyword_density", "duplicate content": "duplicate_content",
            "thin content": "thin_content", "robots": "robots_txt", "robots txt": "robots_txt",
            "sitemap": "xml_sitemap", "schema": "schema_markup", "hreflang": "hreflang_tags",
            "heading text": "heading_text_analysis", "page speed": "page_speed", "lcp": "page_speed",
            "fid": "page_speed", "inp": "page_speed", "cls": "page_speed", "core web vitals": "page_speed",
            "broken links": "broken_links", "404": "errors_404", "redirects": "redirect_chains",
            "redirect chains": "redirect_chains", "ssl": "ssl_certificate", "mixed content": "mixed_content",
            "ga": "ga_setup", "google analytics": "ga_setup", "gsc": "gsc_setup", "search console": "gsc_setup",
            "eeat": "eeat", "geo": "geo_friendly", "faq": "faq_in_blog", "llms.txt": "llms_txt", "llms": "llms_txt",
            "ai visibility": "ai_visibility", "site hierarchy": "site_hierarchy", "internal linking": "internal_linking",
            "responsive design": "responsive_design", "intrusive interstitials": "no_intrusive_interstitials",
            "crawl traps": "crawl_traps", "server logs": "server_logs", "status code": "status_code",
            "h1": "heading_tags", "h2": "heading_tags", "h3": "heading_tags", "heading": "heading_tags",
            "headings": "heading_tags", "word count": "word_count",
        }
        self.explanation_agent = explanation_agent
        self.dispatcher_agent = dispatcher_agent
        self.input_analyzer = input_analyzer 
        self.fallback_agent = fallback_agent
        self.final_output_agent = final_output_agent
        self.validator_agent = ValidatorAgent()
        try:
            self.hybrid_retriever = HybridRetriever()
        except Exception as e:
            logging.error(f"Failed to initialize HybridRetriever: {e}")
            self.hybrid_retriever = None

    def _looks_seo_query(self, user_query: str) -> bool:
        seo_fast_pass_keywords = [
            "seo", "audit", "keyword", "density", "meta", "title", "description",
            "h1", "h2", "h3", "heading", "sitemap", "robots", "canonical", "redirect",
            "404", "crawl", "indexing", "ranking", "speed", "performance", "lighthouse",
            "homepage", "home page", "landing page", "index page", "website", "url",
            "og", "open graph", "site", "similar"
        ]
        return any(kw in user_query.lower() for kw in seo_fast_pass_keywords)

    def _is_query_seo_related(self, user_query: str) -> bool:
        if self._looks_seo_query(user_query):
            return True
        try:
            history_str = "\n".join([f"{m['role']}: {m['content']}" for m in self._build_chat_history_messages(None)[-5:]])
            messages = [{"role": "system", "content": SEO_DOMAIN_CHECK_PROMPT.format(query=user_query, history=history_str)}]
            response_content = (call_llm_completion(messages=messages, temperature=0.0).choices[0].message.content or "").strip().upper()
            return response_content == "YES"
        except Exception as exc:
            logging.error(f"Error during SEO domain check: {exc}")
            return True

    def _get_available_tools(self) -> List[Dict[str, Any]]:
        return [
            { "type": "function", "function": { "name": "get_parameter_detail", "description": "Get audit status/value for one or more specific SEO parameters on a URL.", "parameters": { "type": "object", "properties": { "url": {"type": "string"}, "parameters": {"type": "array", "items": {"type": "string"}, "description": "List of parameters to retrieve (e.g., ['meta_title', 'meta_description'])." }, "compare_field": {"type": "string", "description": "Optional: Specific field to compare for duplication (e.g., 'h1_tags', 'meta_title', 'meta_description', 'text_content'). Only valid if parameter includes 'duplicate_content'."} }, "required": ["url", "parameters"] } } },
            { "type": "function", "function": { "name": "start_audit", "description": "Start a new audit for a URL.", "parameters": { "type": "object", "properties": { "url": {"type": "string"}, "limit": {"type": "integer"} }, "required": ["url"] } } },
            { "type": "function", "function": { "name": "get_audit_summary", "description": "Summarize the current audit.", "parameters": {"type": "object", "properties": {}} } },
            { "type": "function", "function": { "name": "compare_urls", "description": "Compare SEO parameters between URLs.", "parameters": { "type": "object", "properties": { "urls": {"type": "array", "items": {"type": "string"}}, "parameters": {"type": "array", "items": {"type": "string"}} }, "required": ["urls"] } } },
            { "type": "function", "function": { "name": "get_robots_txt", "description": "Fetch robots.txt content.", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]} } },
            { "type": "function", "function": { "name": "get_sitemap_urls", "description": "Fetch sitemap URLs.", "parameters": {"type": "object", "properties": {"url": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["url"]} } },
            { "type": "function", "function": { "name": "get_latest_report_download_path", "description": "Get latest report path.", "parameters": {"type": "object", "properties": {}} } },
            { "type": "function", "function": { "name": "get_audited_urls", "description": "List audited URLs.", "parameters": {"type": "object", "properties": {}} } },
            { "type": "function", "function": { "name": "calculate_seo_length", "description": "Calculates the exact character count of a string.", "parameters": { "type": "object", "properties": { "text": { "oneOf": [ {"type": "string"}, {"type": "array", "items": {"type": "string"}} ] } }, "required": ["text"] } } },
            { "type": "function", "function": { "name": "search_knowledge_base", "description": "Search across all historical audits for relevant facts/data.", "parameters": { "type": "object", "properties": { "query": {"type": "string", "description": "The search query (e.g., 'what was the meta title for appnova.com?')" }, "target_url": {"type": "string", "description": "Optional: Filter results to a specific URL."} }, "required": ["query"] } } }
        ]

    def _extract_urls(self, text: str) -> List[str]:
        found = re.findall(r"https?://[^\s]+", text)
        bare = re.findall(r"\b(?:www\.)?[a-z0-9.-]+\.[a-z]{2,}(?:/[^\s]*)?\b", text, re.IGNORECASE)
        for u in bare:
            if not re.match(r"^https?://", u, re.IGNORECASE):
                u = "https://" + u
            if u not in found:
                found.append(u)
        return found

    def _contains_url_like(self, text: str) -> bool:
        if re.search(r"https?://", text, re.IGNORECASE):
            return True
        if re.search(r"\bwww\.", text, re.IGNORECASE):
            return True
        return bool(re.search(r"\b[a-z0-9.-]+\.[a-z]{2,}(?:/[^\s]*)?\b", text, re.IGNORECASE))

    def _infer_default_url(self, audit_map: AuditMap) -> Optional[str]:
        candidates = []
        if audit_map and audit_map.pages:
            candidates.extend(list(audit_map.pages.keys()))
        if kb_audit := self._load_latest_kb_audit_map():
            candidates.extend(list(kb_audit.pages.keys()))
        if not candidates:
            return None
        return min(candidates, key=lambda u: u.count('/'))

    def _extract_similarity_keywords(self, user_query: str) -> List[str]:
        lower = user_query.lower()
        if "similar to" in lower:
            phrase = lower.split("similar to", 1)[1]
        elif "like" in lower:
            phrase = lower.split("like", 1)[1]
        else:
            phrase = lower
        words = re.findall(r"[a-z0-9]+", phrase)
        stop = {"the", "a", "an", "to", "or", "and", "of", "for", "in", "on", "with", "site", "sites", "website", "websites", "page", "pages"}
        keywords = [w for w in words if w not in stop and len(w) >= 3]
        return list(dict.fromkeys(keywords))[:5]

    def _suggest_similar_sites_from_audit(self, keywords: List[str], audit_map: AuditMap, limit: int = 5) -> List[str]:
        if not keywords:
            return []
        candidates = set()
        if audit_map and audit_map.pages:
            candidates.update(audit_map.pages.keys())
        if kb_audit := self._load_latest_kb_audit_map():
            candidates.update(kb_audit.pages.keys())

        scored = []
        for url in candidates:
            key = self._url_key(url)
            score = sum(1 for kw in keywords if kw in key)
            if score > 0:
                scored.append((score, url))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [u for s, u in scored][:limit]

    def _build_rule_based_decision(self, user_query: str, audit_map: AuditMap) -> Optional[Dict[str, Any]]:
        lower = user_query.lower()
        urls = self._extract_urls(user_query)
        target_url = urls[0] if urls else None

        if not target_url and any(kw in lower for kw in ["homepage", "home page", "index page"]):
            inferred = self._resolve_url_alias("homepage", audit_map)
            if inferred and inferred not in ["homepage", "home page", "index page"]:
                target_url = inferred
        if not target_url:
            target_url = self._infer_default_url(audit_map)

        # Similar site keyword queries without a URL
        if "similar" in lower and not urls:
            keywords = self._extract_similarity_keywords(user_query)
            suggestions = self._suggest_similar_sites_from_audit(keywords, audit_map, limit=5)
            if suggestions:
                msg_lines = ["Here are some audited pages that look similar based on keywords:"]
                msg_lines.extend([f"- {u}" for u in suggestions])
                return {"type": "direct_response", "content": "\n".join(msg_lines)}

        decisions = []
        requested_params = []
        for key, param in self.parameter_name_map.items():
            if key in lower:
                requested_params.append(param)
        if "404" in lower or "not found" in lower:
            if "errors_404" not in requested_params:
                requested_params.append("errors_404")
        requested_params = list(dict.fromkeys(requested_params))

        if target_url and requested_params:
            decisions.append({"type": "tool_call", "tool_name": "get_parameter_detail", "tool_parameters": {"url": target_url, "parameters": requested_params}})

        if "sitemap" in lower and any(kw in lower for kw in ["suggest", "from sitemap", "sitemap urls", "sitemap pages", "sitemap links"]):
            if target_url:
                decisions.append({"type": "tool_call", "tool_name": "get_sitemap_urls", "tool_parameters": {"url": target_url, "limit": 10}})

        if not decisions:
            return None
        if len(decisions) == 1:
            return decisions[0]
        return {"type": "multi_decision", "decisions": decisions}

    def _get_param_state(self, url: str, parameter: str, audit_map: AuditMap) -> Tuple[Optional[AuditMap], Optional[Any], str, str]:
        mapped_param = self.parameter_name_map.get(parameter.lower(), parameter)
        variants = list(set([url, url.strip('/')] + ([url + '/'] if not url.endswith('/') else []) + ([url[:-1]] if url.endswith('/') else [])))
        for v in variants:
            if audit_map and audit_map.get_page_state(v):
                return audit_map, audit_map.get_page_state(v).parameters.get(mapped_param), mapped_param, "session"
        
        # RESTRICTED: Only search the latest KB audit map
        kb_audit = self._load_latest_kb_audit_map()
        if kb_audit:
            for v in variants:
                if kb_audit.get_page_state(v):
                    return kb_audit, kb_audit.get_page_state(v).parameters.get(mapped_param), mapped_param, "kb"
        
        return None, None, mapped_param, "missing"

    def _get_param_from_report(self, url: str, parameter: str) -> Optional[str]:
        df = self._load_latest_report_df()
        if df is None or "Pages" not in df.columns: return None
        label = self._report_label_for_param(parameter)
        if not label or label not in df.columns: return None
        row = df[df["Pages"] == url]
        return str(row.iloc[0][label]) if not row.empty and row.iloc[0][label] is not None else None

    def _load_latest_kb_audit_map(self) -> Optional[AuditMap]:
        """Loads the most recent audit data from the knowledge base."""
        try:
            if audit_data := get_latest_audit_data():
                return AuditMap.from_dict(audit_data)
        except Exception as e:
            logging.error(f"Error loading latest KB audit map: {e}")
        return None

    def _load_latest_report_df(self) -> Optional[pd.DataFrame]:
        """Loads the latest report file into a pandas DataFrame."""
        try:
            if report_path := get_latest_report_path():
                return pd.read_excel(report_path)
        except Exception as e:
            logging.error(f"Error loading latest report dataframe: {e}")
        return None

    def _report_label_for_param(self, parameter: str) -> Optional[str]:
        """Converts an internal parameter name (snake_case) to its expected report column label (Title Case)."""
        if not parameter:
            return None
        # Convert snake_case to Title Case (e.g., 'meta_title' -> 'Meta Title')
        return ' '.join(word.capitalize() for word in parameter.split('_'))

    def _execute_compare_urls(self, urls: List[str], parameters: List[str], audit_map: AuditMap) -> str:
        comparison_results = []
        full_report_text = []

        if not urls or len(urls) < 2:
            return "Please provide at least two URLs for comparison."
        if not parameters:
            return "Please specify parameters to compare."

        for url in urls:
            full_report_text.append(f"\n--- Audit Results for {url} ---")
            url_results = {"url": url}
            for param in parameters:
                # Ensure each parameter is audited and state is updated
                detail_result = self._handle_get_parameter_detail(params={"url": url, "parameters": [param]}, audit_map=audit_map)
                
                # Append the explanation agent's formatted text for this parameter
                full_report_text.append(detail_result.get("tool_output_text", f"Could not retrieve details for {param}."))
                
                # Store payload for structured comparison if needed later by explanation agent
                url_results[param] = detail_result.get("payload")
            comparison_results.append(url_results)
        
        # This text will be passed to the explanation agent.
        # The explanation agent will then formulate a human-readable comparison.
        return "\n".join(full_report_text)

    def _compute_detailed_similarity(self, urls: List[str], audit_map: AuditMap) -> str:
        return "Detailed similarity computation not yet implemented."

    def _execute_get_robots_txt(self, url: str) -> str:
        return f"Fetching robots.txt for {url} not yet implemented."

    def _execute_get_sitemap_urls(self, url: str, limit: Optional[int]) -> str:
        if not self.input_analyzer:
            return "Sitemap lookup is currently unavailable."
        max_urls = limit or 20
        urls, msg = self.input_analyzer.get_cached_sitemap_urls(url, max_urls_to_collect=max_urls)
        if not urls:
            return f"No sitemap URLs found for {url}. {msg}"
        lines = [f"Sitemap URLs for {url} (showing up to {max_urls}):"]
        lines.extend([f"- {u}" for u in urls[:max_urls]])
        return "\n".join(lines)

    def _execute_get_latest_report_download_path(self) -> str:
        return "Getting latest report download path not yet implemented."

    def _execute_get_audited_urls(self, audit_map: AuditMap) -> str:
        """Returns a formatted string of all URLs present in the current session's audit map and the latest knowledge base audit map."""
        audited_urls = set()
        if audit_map and audit_map.pages:
            audited_urls.update(audit_map.pages.keys())
        if kb_audit := self._load_latest_kb_audit_map():
            audited_urls.update(kb_audit.pages.keys())

        if audited_urls:
            return "URLs currently audited:\n" + "\n".join(sorted(list(audited_urls)))
        return "No URLs have been audited yet in the current session or found in the knowledge base."

    def _run_query_driven_audit(self, url: str, params: List[str], audit_map: AuditMap) -> bool:
        logging.info(f"--- Starting Resilient Query-Driven Audit for {url} ---")
        html_content = fetch_html(url)
        if not html_content or html_content.startswith("Error fetching URL"):
            logging.info(f"  Standard fetch failed for {url}. Escalating immediately.")
            html_content = None
        if not audit_map.get_page_state(url):
            audit_map.add_page(url, list(self.dispatcher_agent.criteria.keys()))
        if html_content:
            self.dispatcher_agent.dispatch_extraction(audit_map, url, html_content, allowed_params=params)
            self.validator_agent.validate_page(audit_map, url)
        
        page_state = audit_map.get_page_state(url)
        def _check_insufficient(p_state):
            if not p_state: return True
            if p_state.status in [AuditStatus.FALLBACK_NEEDED, AuditStatus.REQUIRES_FALLBACK_TOOL, AuditStatus.FAILED]:
                return True
            # If status is validated or extracted but the value is missing for a requested param, we should fallback
            if not p_state.value or p_state.value == "N/A":
                return True
            return False

        needs_fallback = html_content is None or any(_check_insufficient(page_state.parameters.get(p)) for p in params)
        
        if needs_fallback:
            logging.info(f"  Standard extraction insufficient. Triggering JS-rendered recrawl...")
            try:
                nest_asyncio.apply()
                rendered_html = asyncio.run(crawl_page_content.ainvoke({"url": url, "render_js": True}))
                if rendered_html and not rendered_html.startswith("Error"):
                    logging.info(f"  Successfully retrieved rendered HTML. Re-extracting all insufficient parameters...")
                    
                    # Identify all parameters on this page that need a re-look
                    all_params_needing_fix = [
                        p_name for p_name, p_state in page_state.parameters.items()
                        if _check_insufficient(p_state) or p_name in params
                    ]
                    
                    self.dispatcher_agent.dispatch_extraction(audit_map, url, rendered_html, allowed_params=all_params_needing_fix)
                    self.validator_agent.validate_page(audit_map, url)
                else:
                    logging.info(f"  Advanced fallback failed: {rendered_html[:100] if rendered_html else 'No content'}")
            except Exception as e:
                logging.info(f"  Error during query-driven fallback: {e}")
        logging.info(f"--- Resilient Audit completed for {url} ---")
        return True

    def _build_chat_history_messages(self, chat_history: Optional[List[Dict[str, str]]]) -> List[Dict[str, str]]:
        merged = []
        if full_chat_history_from_kb := get_chat_history():
            for msg in full_chat_history_from_kb[-5:]:
                merged.extend([{"role": "user", "content": msg["q"]}, {"role": "assistant", "content": msg["a"]}])
        if chat_history:
            merged.extend(chat_history[-10:])
        return merged

    def _build_audit_index_context(self, audit_map: AuditMap) -> str:
        lines = ["# Available Audit Data", "---"]
        def describe(label: str, source_map: Optional[AuditMap]):
            if not source_map or not source_map.pages: return
            lines.append(f"## {label}")
            for url, page_state in source_map.pages.items():
                lines.append(f"\n### URL: {url}")
                audited_params = []
                for p_name, p_state in page_state.parameters.items():
                    if p_state.status != AuditStatus.PENDING:
                        v = p_state.value
                        
                        # Enhanced display for SEO text fields (Calculate on the fly if missing)
                        extra_info = ""
                        if p_name in ["meta_title", "meta_description"]:
                            text_val = v.get("value") if isinstance(v, dict) else str(v)
                            length = v.get("character_count") if isinstance(v, dict) else len(text_val)
                            extra_info = f" [Length: {length}]"
                        elif p_name in ["heading_tags", "h1_tags"]:
                            target_data = v.get("details") if isinstance(v, dict) else v
                            h1_lengths = []
                            if isinstance(target_data, dict):
                                h1_lengths = target_data.get("h1_lengths") or [len(str(h)) for h in target_data.get("h1_content", [])]
                            elif isinstance(target_data, list):
                                h1_lengths = [len(str(h)) for h in target_data]
                            if h1_lengths:
                                extra_info = f" [H1 Lengths: {', '.join(map(str, h1_lengths))}]"
                        
                        v_str = str(v)
                        display_val = (v_str[:150] + '...') if len(v_str) > 150 else v_str
                        audited_params.append(f"- **{p_name}**: {display_val}{extra_info} (Status: {p_state.status.value})")
                
                if audited_params:
                    lines.extend(audited_params)
                else:
                    lines.append("- No parameters audited for this URL yet.")
            lines.append("\n---")
        
        describe("Current Session Audit", audit_map)
        if kb_audit := self._load_latest_kb_audit_map():
            describe("Latest Knowledge Base Audit", kb_audit)
        
        # Add summary of what else is available in KB
        audited_urls = set()
        kb_index = self._load_latest_kb_audit_map() 
        if kb_index:
            audited_urls.update(kb_index.pages.keys())
        
        if audited_urls:
            lines.append("## Historically Audited URLs in KB")
            lines.append(", ".join(list(audited_urls)[:10]) + ("..." if len(audited_urls) > 10 else ""))

        return "\n".join(lines) if len(lines) > 2 else "No audit data is currently available."

    def _call_decision_agent(self, user_query: str, chat_history_messages: List[Dict[str, str]], audit_index_context: str) -> Dict[str, Any]:
        tools_context = "\n".join([f"- {tool['function']['name']}: {tool['function']['description']}" for tool in self._get_available_tools()])
        messages = [
            {"role": "system", "content": DECISION_AGENT_PROMPT},
            {"role": "assistant", "content": f"Context:\n{audit_index_context}"},
            {"role": "assistant", "content": f"Available tools:\n{tools_context}"},
            *chat_history_messages,
            {"role": "user", "content": user_query}
        ]
        try:
            response_message = call_llm_completion(messages=messages, tools=self._get_available_tools()).choices[0].message
            logging.info(f"[Decision Agent] LLM Response: {response_message.content}")
            if response_message.tool_calls:
                decisions = [{"type": "tool_call", "tool_name": tc.function.name, "tool_parameters": json.loads(tc.function.arguments or "{}"), "raw_content": response_message.content or ""} for tc in response_message.tool_calls]
                return {"type": "multi_decision", "decisions": decisions} if len(decisions) > 1 else decisions[0]
            return {"type": "direct_response", "content": response_message.content or "I could not determine how to proceed."}
        except Exception as exc:
            logging.error("Decision agent failure: %s", exc)
            return {"type": "direct_response", "content": "I had trouble planning the next step."}

    def _execute_decision(self, decision_result: Dict[str, Any], audit_map: AuditMap) -> Dict[str, Any]:
        logging.info(f"[Execute Decision] Type: {decision_result['type']}")
        if decision_result["type"] == "direct_response":
            return {"should_explain": False, "final_text": decision_result["content"], "payload": {"message": decision_result["content"]}}
        handler = self._tool_handlers().get(decision_result["tool_name"])
        if not handler:
            return {"tool_name": decision_result["tool_name"], "tool_output_text": f"Tool {decision_result['tool_name']} not implemented.", "payload": {"error": "unknown_tool"}, "should_explain": True}
        execution_result = handler(decision_result["tool_parameters"], audit_map)
        execution_result.setdefault("tool_name", decision_result["tool_name"])
        return execution_result

    def _tool_handlers(self) -> Dict[str, Callable]:
        return {
            "get_parameter_detail": self._handle_get_parameter_detail, "start_audit": self._handle_start_audit,
            "get_audit_summary": self._handle_get_audit_summary, "compare_urls": self._handle_compare_urls,
            "get_robots_txt": self._handle_get_robots_txt, "get_sitemap_urls": self._handle_get_sitemap_urls,
            "get_latest_report_download_path": self._handle_get_latest_report_download_path,
            "get_audited_urls": self._handle_get_audited_urls, "calculate_seo_length": self._handle_calculate_seo_length,
            "search_knowledge_base": self._handle_search_knowledge_base
        }

    def _handle_search_knowledge_base(self, params: Dict[str, Any], audit_map: AuditMap) -> Dict[str, Any]:
        query = params.get("query")
        target_url = params.get("target_url")
        if not query: return {"tool_output_text": "Search query is required.", "payload": {"error": "missing_query"}, "should_explain": True}
        
        if not self.hybrid_retriever:
            return {"tool_output_text": "Knowledge Base search engine is currently unavailable.", "payload": {"error": "retriever_unavailable"}, "should_explain": True}
        
        results = self.hybrid_retriever.search(query, target_url=target_url, top_n=5)
        if not results:
            return {"tool_output_text": "No relevant historical facts found in the Knowledge Base.", "payload": {"results": []}, "should_explain": True}
        
        # Format results
        fact_lines = []
        for atom, score in results:
            fact_lines.append(f"- {atom['text']} (Relevance Score: {score:.4f})")
        
        msg = "I found the following relevant facts in the Knowledge Base:\n" + "\n".join(fact_lines)
        return {"tool_output_text": msg, "payload": {"results": [r[0] for r in results], "query": query}, "should_explain": True}

    def _handle_calculate_seo_length(self, params: Dict[str, Any], audit_map: AuditMap) -> Dict[str, Any]:
        text = params.get("text")
        if not text: return {"tool_output_text": "No text for length calculation.", "payload": {"error": "missing_text"}, "should_explain": True}
        result = calculate_seo_length(text)
        if result.get("is_batch"):
            msg = "\n".join([f"- \"{item['text']}\": **{item['character_count']}** characters" for item in result["results"]])
        else:
            msg = f"The character length of \"{text}\" is **{result['character_count']}** characters."
        return {"tool_output_text": msg, "payload": result, "should_explain": False}

    def _resolve_url_alias(self, url: str, audit_map: AuditMap) -> str:
        """Maps aliases like 'homepage' to the actual root URL found in the audit data."""
        if not url: return url
        if url.lower() in ["homepage", "home page", "index page"]:
            # Try to find the homepage URL (shortest URL or likely candidate)
            all_known_urls = list(audit_map.pages.keys())
            kb_audit = self._load_latest_kb_audit_map()
            if kb_audit: all_known_urls.extend(list(kb_audit.pages.keys()))
            
            # Find the URL with the minimum number of slashes (likely the root)
            if all_known_urls:
                return min(all_known_urls, key=lambda u: u.count('/'))
        return url

    def _normalize_url(self, url: str) -> str:
        if not url:
            return url
        cleaned = url.strip()
        if not re.match(r"^https?://", cleaned, re.IGNORECASE):
            cleaned = "https://" + cleaned
        parsed = urlparse(cleaned)
        if not parsed.netloc and parsed.path:
            return cleaned
        return parsed._replace(fragment="").geturl()

    def _url_netloc_key(self, url: str) -> str:
        if not url:
            return ""
        normalized = self._normalize_url(url)
        parsed = urlparse(normalized)
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc

    def _url_key(self, url: str) -> str:
        if not url:
            return ""
        normalized = self._normalize_url(url)
        parsed = urlparse(normalized)
        netloc = self._url_netloc_key(normalized)
        path = parsed.path or ""
        if path.endswith("/") and path != "/":
            path = path[:-1]
        return f"{netloc}{path}".lower()

    def _same_domain(self, url_a: str, url_b: str) -> bool:
        return self._url_netloc_key(url_a) == self._url_netloc_key(url_b)

    def _looks_like_typo(self, url: str) -> bool:
        if not url:
            return False
        return bool(re.search(r"(.)\1\1+", url))

    def _get_sitemap_urls(self, url: str, max_urls: int = 1000) -> List[str]:
        if not self.input_analyzer:
            return []
        urls, _ = self.input_analyzer.get_cached_sitemap_urls(url, max_urls_to_collect=max_urls)
        return urls or []

    def _find_direct_sitemap_hit(self, url: str, sitemap_urls: List[str]) -> Optional[str]:
        if not sitemap_urls:
            return None
        target_key = self._url_key(url)
        for candidate in sitemap_urls:
            if self._url_key(candidate) == target_key:
                return candidate
        return None

    def _get_similar_url_suggestions(self, url: str, audit_map: AuditMap, sitemap_urls: List[str], limit: int = 5) -> List[str]:
        candidates = set()
        if audit_map and audit_map.pages:
            candidates.update([u for u in audit_map.pages.keys() if self._same_domain(u, url)])

        kb_audit = self._load_latest_kb_audit_map()
        if kb_audit and kb_audit.pages:
            candidates.update([u for u in kb_audit.pages.keys() if self._same_domain(u, url)])

        if sitemap_urls:
            candidates.update([u for u in sitemap_urls if self._same_domain(u, url)])

        if not candidates:
            return []

        target_key = self._url_key(url)
        scored = []
        for cand in candidates:
            cand_key = self._url_key(cand)
            if not cand_key:
                continue
            if cand_key == target_key:
                continue
            score = SequenceMatcher(None, target_key, cand_key).ratio()
            scored.append((score, cand))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for s, c in scored if s > 0.35][:limit]

    def _handle_get_parameter_detail(self, params: Dict[str, Any], audit_map: AuditMap) -> Dict[str, Any]:
        raw_url, requested_parameters, compare_field = params.get("url"), params.get("parameters", []), params.get("compare_field")
        if not raw_url or not requested_parameters: return {"tool_output_text": "URL and parameters are required.", "payload": {"error": "missing_arguments"}, "should_explain": True}
        
        # Resolve alias (e.g., 'homepage' -> 'https://www.appnova.com/')
        url = self._resolve_url_alias(raw_url, audit_map)
        url = self._normalize_url(url)
        correction_note = None
        sitemap_urls: List[str] = []

        # Typo heuristic: avoid crawling obvious typos; suggest sitemap alternatives first.
        if self._looks_like_typo(url):
            sitemap_urls = self._get_sitemap_urls(url)
            direct_hit = self._find_direct_sitemap_hit(url, sitemap_urls)
            if direct_hit:
                if direct_hit != url:
                    correction_note = f"Note: I found a close match in the sitemap and will use `{direct_hit}`."
                url = direct_hit
            else:
                suggestions = self._get_similar_url_suggestions(url, audit_map, sitemap_urls, limit=5)
                if suggestions:
                    msg_lines = [
                        f"That URL looks like a typo. I could not find `{raw_url}` in the sitemap, but you might be referring to:"
                    ]
                    msg_lines.extend([f"- {s}" for s in suggestions])
                    return {"tool_output_text": "\n".join(msg_lines), "needs_audit": False, "payload": {"url": url, "suggestions": suggestions, "reason": "typo_suspected"}, "should_explain": True}
        
        # Map all requested parameters
        mapped_params = [self.parameter_name_map.get(p.lower(), p) for p in requested_parameters]
        
        # Check overall state
        page_state = audit_map.get_page_state(url)
        if not page_state:
            audit_map.add_page(url, list(self.dispatcher_agent.criteria.keys()))
            page_state = audit_map.get_page_state(url)

        def _is_insufficient(p_name):
            p_state = page_state.parameters.get(p_name)
            if not p_state: return True
            return p_state.status in [AuditStatus.PENDING, AuditStatus.FAILED, AuditStatus.FALLBACK_NEEDED, AuditStatus.REQUIRES_FALLBACK_TOOL] or not p_state.value or p_state.value == "N/A"

        params_needing_audit = [p for p in mapped_params if _is_insufficient(p)]
        
        if params_needing_audit:
            logging.info(f"--- [SURGICAL AUDIT] Starting synchronous extraction for {params_needing_audit} on {url} ---")
            
            # Step 1: Standard Fetch
            with st.spinner(f"Surgically Analyzing {url}..."):
                fetch_result = fetch_url_data(url, method="GET", timeout=15)
                html_content = fetch_result.get("text", "")
                status_code = fetch_result.get("status_code")
            
            if status_code in [404, 410]:
                if not sitemap_urls:
                    sitemap_urls = self._get_sitemap_urls(url)
                suggestions = self._get_similar_url_suggestions(url, audit_map, sitemap_urls, limit=5)
                if suggestions:
                    msg_lines = [
                        f"It looks like `{raw_url}` returned a 404.",
                        "You might be referring to one of these URLs:"
                    ]
                    msg_lines.extend([f"- {s}" for s in suggestions])
                    return {"tool_output_text": "\n".join(msg_lines), "needs_audit": False, "payload": {"url": url, "suggestions": suggestions, "reason": "404"}, "should_explain": True}
                return {"tool_output_text": f"It looks like `{raw_url}` returned a 404, and I couldn't find close matches in the sitemap or audit history.", "needs_audit": False, "payload": {"url": url, "reason": "404", "suggestions": []}, "should_explain": True}
            
            # Step 2: Extraction (Extract CORE tags + what was specifically asked for)
            core_tags = ["meta_title", "meta_description", "heading_tags"]
            extract_list = list(set(mapped_params + core_tags))
            
            extraction_successful = False
            if html_content and status_code not in [404, 410]:
                self.dispatcher_agent.dispatch_extraction(audit_map, url, html_content, allowed_params=extract_list, compare_field=compare_field)
                self.validator_agent.validate_page(audit_map, url)
                
                # Verify if requested parameters are now validated
                if all(not _is_insufficient(p) for p in mapped_params):
                    extraction_successful = True
            
            # Step 3: FALLBACK - If standard failed, use JS rendering (Crawl4AI)
            if not extraction_successful:
                logging.info(f"  Standard fetch insufficient for {url}. Triggering JS-rendered surgical fallback...")
                with st.spinner(f"Deep Crawling {url} (JS Rendering)..."):
                    try:
                        from tools.html_tools.crawl_tool import crawl_page_content
                        import asyncio
                        import nest_asyncio
                        nest_asyncio.apply()
                        
                        rendered_html = asyncio.run(crawl_page_content.ainvoke({"url": url, "render_js": True}))
                        if rendered_html and not rendered_html.startswith("Error"):
                            self.dispatcher_agent.dispatch_extraction(audit_map, url, rendered_html, allowed_params=extract_list, compare_field=compare_field)
                            self.validator_agent.validate_page(audit_map, url)
                    except Exception as e:
                        logging.error(f"  Surgical fallback failed for {url}: {e}")

        # Final Formatting of results
        output_lines = []
        payload_details = []
        if correction_note:
            output_lines.append(correction_note)
        for p_name in mapped_params:
            _, p_state, _, source = self._get_param_state(url, p_name, audit_map)
            if p_state:
                output_lines.append(self.explanation_agent.format_parameter_detail(url, p_name, p_state))
                payload_details.append({"parameter": p_name, "status": p_state.status.value, "value": p_state.value, "source": source})

        if output_lines:
            return {"tool_output_text": "\n\n".join(output_lines), "needs_audit": False, "payload": {"url": url, "details": payload_details}, "should_explain": True}
        
        return {"tool_output_text": f"Even after a live crawl, details for `{requested_parameters}` on `{url}` could not be retrieved.", "needs_audit": False, "payload": {"status": "failed"}, "should_explain": True}

    def _handle_start_audit(self, params: Dict[str, Any], audit_map: AuditMap) -> Dict[str, Any]:
        url, limit = params.get("url"), params.get("limit")
        if not url: return {"tool_output_text": "Audit requests require a URL.", "payload": {"error": "missing_url"}, "should_explain": True}
        return {"tool_output_text": f"Starting a new audit for {url}.", "payload": {"action": "start_audit", "url": url, "limit": limit}, "should_explain": True, "limit": limit}

    def _handle_get_audit_summary(self, params: Dict[str, Any], audit_map: AuditMap) -> Dict[str, Any]:
        if audit_map and audit_map.pages: summary = "Current audit summary: " + " ".join([f"{len(audit_map.pages)} pages audited."])
        elif kb_audit := self._load_latest_kb_audit_map(): summary = "Latest KB audit summary: " + " ".join([f"{len(kb_audit.pages)} pages audited."])
        else: summary = "No audit data available."
        return {"tool_output_text": summary, "payload": {"summary": summary}, "should_explain": True}

    def _handle_compare_urls(self, params: Dict[str, Any], audit_map: AuditMap) -> Dict[str, Any]:
        urls, parameters = params.get("urls", []), params.get("parameters", [])
        if not urls: return {"tool_output_text": "Comparison requests require at least one URL.", "payload": {"error": "missing_urls"}, "should_explain": True}
        
        # Always call _execute_compare_urls for now.
        # The logic for duplicate_content/similarity can be re-introduced once _compute_detailed_similarity is fully implemented.
        text = self._execute_compare_urls(urls, parameters, audit_map)
        
        return {"tool_output_text": text, "payload": {"urls": urls, "parameters": parameters, "result": text}, "should_explain": True}

    def _handle_get_robots_txt(self, params: Dict[str, Any], audit_map: AuditMap) -> Dict[str, Any]:
        url = params.get("url")
        if not url: return {"tool_output_text": "Please provide a URL.", "payload": {"error": "missing_url"}, "should_explain": True}
        text = self._execute_get_robots_txt(url)
        return {"tool_output_text": text, "payload": {"url": url, "robots": text}, "should_explain": True}

    def _handle_get_sitemap_urls(self, params: Dict[str, Any], audit_map: AuditMap) -> Dict[str, Any]:
        url, limit = params.get("url"), params.get("limit")
        if not url: return {"tool_output_text": "Please provide a URL.", "payload": {"error": "missing_url"}, "should_explain": True}
        text = self._execute_get_sitemap_urls(url, limit)
        return {"tool_output_text": text, "payload": {"url": url, "limit": limit, "sitemap_result": text}, "should_explain": True}

    def _handle_get_latest_report_download_path(self, params: Dict[str, Any], audit_map: AuditMap) -> Dict[str, Any]:
        text = self._execute_get_latest_report_download_path()
        return {"tool_output_text": text, "payload": {"report_path": text}, "should_explain": True}

    def _handle_get_audited_urls(self, params: Dict[str, Any], audit_map: AuditMap) -> Dict[str, Any]:
        text = self._execute_get_audited_urls(audit_map)
        return {"tool_output_text": text, "payload": {"audited_urls": text}, "should_explain": True}

    def _call_explanation_agent(self, user_query: str, decision_result: Dict[str, Any], execution_result: Dict[str, Any], chat_history_messages: List[Dict[str, str]], audit_index_context: str, audit_map: AuditMap) -> str:
        payload = execution_result.get("payload", {})
        decision_summary = {"type": decision_result.get("type"), "tool": decision_result.get("tool_name"), "parameters": decision_result.get("tool_parameters")}
        
        # --- PRE-EXTRACT VERIFIED FACTS (Ground Truth for the AI) ---
        verified_facts = []
        relevant_urls = self._extract_urls(user_query)
        
        # Homepage alias detection
        if any(kw in user_query.lower() for kw in ["homepage", "home page", "index page"]):
            found_homepage = None
            all_known_urls = list(audit_map.pages.keys())
            kb_audit = self._load_latest_kb_audit_map()
            if kb_audit: all_known_urls.extend(list(kb_audit.pages.keys()))
            
            for u in all_known_urls:
                if u.count('/') <= 3:
                    found_homepage = u
                    break
            if found_homepage and found_homepage not in relevant_urls:
                relevant_urls.append(found_homepage)

        if not relevant_urls:
            relevant_urls = list(audit_map.pages.keys())
            kb_audit = self._load_latest_kb_audit_map()
            if kb_audit: relevant_urls.extend(list(kb_audit.pages.keys()))
        
        relevant_urls = list(dict.fromkeys(relevant_urls))
        kb_audit = self._load_latest_kb_audit_map()
        
        for url in relevant_urls:
            page_state = audit_map.get_page_state(url) or (kb_audit.get_page_state(url) if kb_audit else None)
            if not page_state: continue
            
            # Title
            title_state = page_state.parameters.get("meta_title")
            if title_state and title_state.value:
                val = title_state.value
                text_val = val.get("value") if isinstance(val, dict) else str(val)
                length = val.get("character_count") if isinstance(val, dict) else len(text_val)
                verified_facts.append(f"Meta Title length on {url}: {length} chars")
            
            # Description
            desc_state = page_state.parameters.get("meta_description")
            if desc_state and desc_state.value:
                val = desc_state.value
                text_val = val.get("value") if isinstance(val, dict) else str(val)
                length = val.get("character_count") if isinstance(val, dict) else len(text_val)
                verified_facts.append(f"Meta Description length on {url}: {length} chars")
            
            # H1s
            h1_state = page_state.parameters.get("heading_tags") or page_state.parameters.get("h1_tags")
            if h1_state and h1_state.value:
                val = h1_state.value
                h1_lengths = []
                target_data = val.get("details") if isinstance(val, dict) and "details" in val else val
                
                if isinstance(target_data, dict):
                    h1_lengths = target_data.get("h1_lengths") or [len(str(h)) for h in target_data.get("h1_content", [])]
                elif isinstance(target_data, list):
                    h1_lengths = [len(str(h)) for h in target_data]
                elif isinstance(target_data, str):
                     h1_lengths = [len(target_data)]
                
                if h1_lengths:
                    verified_facts.append(f"H1 lengths on {url}: {', '.join(map(str, h1_lengths))} chars")

        verified_facts_str = "\n".join(list(dict.fromkeys(verified_facts)))
        
        messages = [
            {"role": "system", "content": EXPLANATION_AGENT_PROMPT},
            {"role": "system", "content": f"Audit index (Ground Truth Data):\n{audit_index_context}"},
            {"role": "system", "content": f"Decision Summary (Ground Truth Data):\n{json.dumps(decision_summary, indent=2, default=str)}"},
            {"role": "system", "content": f"Structured tool output (Ground Truth Data):\n{json.dumps(payload, indent=2, default=str)}"},
            *([{"role": "system", "content": f"Tool output text (Ground Truth Data):\n{execution_result['tool_output_text']}"}] if execution_result.get("tool_output_text") else []),
            {"role": "system", "content": f"Explicit SEO Length Facts (Ground Truth - USE THESE EXACTLY):\n{verified_facts_str}"},
            *chat_history_messages,
            {"role": "user", "content": user_query}
        ]
        
        try:
            final_response = (call_llm_completion(messages=messages).choices[0].message.content or "").strip()
            return final_response
        except Exception as exc:
            logging.error(f"Explanation agent failure: {exc}")
            return execution_result.get("tool_output_text") or decision_result.get("content") or "An error occurred."

    def resolve(self, user_query: str, audit_map: AuditMap, chat_history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        if not self._contains_url_like(user_query) and not self._looks_seo_query(user_query):
            if cached_answer := find_exact_match(user_query):
                return {"llm_decision": {"action": "RESPOND_TEXT", "content": cached_answer}, "chatbot_response": cached_answer, "audit_limit": None}
        if "last question" in user_query.lower() and (reply := get_last_question() or "I don't have any previous questions stored."):
            return {"llm_decision": {"action": "RESPOND_TEXT", "content": reply}, "chatbot_response": reply, "audit_limit": None}
        if not self._is_query_seo_related(user_query):
            return {"llm_decision": {"action": "RESPOND_TEXT", "content": "I specialize in SEO. Please ask an SEO-related question."}, "chatbot_response": "I specialize in SEO. Please ask an SEO-related question.", "audit_limit": None}

        if rule_decision := self._build_rule_based_decision(user_query, audit_map):
            decision_result = rule_decision
        else:
            merged_chat_history = self._build_chat_history_messages(chat_history)
            decision_result = self._call_decision_agent(user_query, merged_chat_history, self._build_audit_index_context(audit_map))
        
        final_text, execution_result = "", {}
        merged_chat_history = self._build_chat_history_messages(chat_history)
        if decision_result.get("type") == "multi_decision":
            exec_results = [self._execute_decision(sub_decision, audit_map) for sub_decision in decision_result["decisions"]]
            synthesized_payloads = [{"tool": sub.get("tool_name"), "params": sub.get("tool_parameters"), "output": res.get("payload")} for sub, res in zip(decision_result["decisions"], exec_results)]
            
            triggered_audit_payload = next((res.get("payload") for res in exec_results if res.get("payload", {}).get("action") == "start_audit"), None)
            
            updated_audit_index_context = self._build_audit_index_context(audit_map)
            combined_exec_result = {
                "payload": {"multi_tool_results": synthesized_payloads}, 
                "tool_output_text": "\n\n".join(r.get("tool_output_text", "") for r in exec_results)
            }
            final_text = self._call_explanation_agent(user_query, decision_result, combined_exec_result, merged_chat_history, updated_audit_index_context, audit_map)
            
            if triggered_audit_payload:
                execution_result = {"payload": triggered_audit_payload}
            else:
                execution_result = exec_results[0]
        elif decision_result.get("type") == "direct_response":
            final_text, execution_result = decision_result["content"], {}
        else:
            execution_result = self._execute_decision(decision_result, audit_map)
            updated_audit_index_context = self._build_audit_index_context(audit_map)
            if not execution_result.get("should_explain", True):
                final_text = execution_result.get("tool_output_text")
            else:
                final_text = self._call_explanation_agent(user_query, decision_result, execution_result, merged_chat_history, updated_audit_index_context, audit_map)

        store_qa(user_query, final_text)
        llm_decision = {"action": "RESPOND_TEXT", "content": final_text}
        if execution_result.get("payload", {}).get("action") == "start_audit":
            llm_decision = execution_result["payload"]
        
        return {"llm_decision": llm_decision, "chatbot_response": final_text, "audit_limit": execution_result.get("limit")}
