import json
import os
from typing import Dict, List, Callable, Any, Optional
import importlib
import inspect
import asyncio
import nest_asyncio

from graph.state import AuditMap, AuditStatus
from tools.html_tools.html_parser_tool import parse_html_and_extract_tags
from chatbot.hybrid_retriever import HybridRetriever
from tools.fetch_tool import fetch_urls_batch

_SITE_CACHE: Dict[str, Dict[str, Any]] = {}
_PAGE_FINGERPRINT_CACHE: Dict[str, Dict[str, Any]] = {}  # Global cache for storing page content fingerprints
_PAGE_HTML_CACHE: Dict[str, str] = {} # Global cache for storing raw HTML content

class DispatcherAgent:

    def __init__(self, kb_path=None):
        if kb_path is None:
            base_dir = os.path.dirname(os.path.abspath(__file__)) 
            kb_path = os.path.join(base_dir, '..', 'kb', 'criteria.json') 
        self.kb_path = kb_path
        self.criteria = self._load_criteria()
        self.parameter_tools = self._load_parameter_tools() 
        self.retriever = HybridRetriever()
        self.BM25_THRESHOLD = 0.2

    async def pre_crawl_and_extract_batch(self, urls: List[str], audit_map: AuditMap):
        """
        Fetches all URLs in parallel, caches HTML, and performs initial tag extraction
        to populate the fingerprint cache for duplicate detection.
        """
        print(f"\n[PRE-CRAWL] Starting batch fetch and extract for {len(urls)} URLs...")
        
        # 1. Parallel Fetch
        html_results = await fetch_urls_batch(urls)
        _PAGE_HTML_CACHE.update(html_results)
        
        # 2. Parallel Extraction (Fingerprinting)
        for url, html in html_results.items():
            if not html or html.startswith("Error fetching"):
                continue
            
            # Populate fingerprint cache for each page
            try:
                # We use the same extraction logic used in regular dispatch
                page_context = self._call_tool_flex(parse_html_and_extract_tags, url, html, audit_map, {}, {})
                if page_context.get("clean_text_content"):
                    _PAGE_FINGERPRINT_CACHE[url] = {
                        "text_content": page_context.get("clean_text_content"),
                        "meta_title": page_context.get("title"),
                        "meta_description": page_context.get("meta_description"),
                        "h1_tags": page_context.get("h1_tags"),
                        "images": page_context.get("image_alt_texts")
                    }
            except Exception as e:
                print(f"[PRE-CRAWL] Error fingerprinting {url}: {e}")
        
        print(f"[PRE-CRAWL] Batch processing complete. {len(_PAGE_HTML_CACHE)} pages in cache.\n")

    def get_cached_html(self, url: str) -> Optional[str]:
        return _PAGE_HTML_CACHE.get(url)

    def _load_criteria(self):
        with open(self.kb_path, 'r') as f:
            return json.load(f)

    def _load_parameter_tools(self) -> Dict[str, Callable]:
        """
        Dynamically loads parameter-specific tools from tools/seo_parameters.
        """
        tools_map: Dict[str, Callable] = {}
        base_dir = os.path.dirname(os.path.abspath(__file__))
        tool_dirs = [
            ("tools.seo_parameters", os.path.join(base_dir, "..", "tools", "seo_parameters")),
        ]
        module_param_map = {
            "robots_txt_tool": "robots_txt", "xml_sitemap_tool": "xml_sitemap",
            "canonical_tag_tool": "canonical_tag", "og_tags_tool": "og_tags",
            "hreflang_tool": "hreflang_tags", "heading_tags_tool": "heading_tags",
            "heading_text_analysis_tool": "heading_text_analysis", "meta_title_tool": "meta_title",
            "analyze_meta_title_tool": "meta_title", "meta_description_tool": "meta_description",
            "image_alt_text_tool": "image_alt_text", "hidden_content_tool": "hidden_content",
            "keyword_density_tool": "keyword_density", "duplicate_content_tool": "duplicate_content",
            "thin_content_tool": "thin_content", "server_logs_tool": "server_logs",
            "crawl_traps_tool": "crawl_traps", "four_o_four_errors_tool": "errors_404",
            "broken_links_tool": "broken_links", "redirect_chains_tool": "redirect_chains",
            "schema_markup_tool": "schema_markup", "ga_setup_tool": "ga_setup",
            "gsc_setup_tool": "gsc_setup", "eeat_tool": "eeat", "geo_friendly_tool": "geo_friendly",
            "faq_in_blog_tool": "faq_in_blog", "llmstext_file_tool": "llms_txt",
            "ai_visibility_tool": "ai_visibility", "site_hierarchy": "site_hierarchy",
            "url_structure_tool": "site_hierarchy", "breadcrumb_tool": "breadcrumbs",
            "internal_linking_tool": "internal_linking", "responsive_design_tool": "responsive_design",
            "intrusive_interstitials_tool": "no_intrusive_interstitials",
            "ssl_tool": "ssl_certificate", "mixed_content_tool": "mixed_content",
            "page_speed_tool": "page_speed",
        }
        for module_prefix, tools_dir in tool_dirs:
            if not os.path.isdir(tools_dir): continue
            for filename in os.listdir(tools_dir):
                if not filename.endswith(".py") or filename == "__init__.py": continue
                module_name = filename[:-3]
                try:
                    module = importlib.import_module(f"{module_prefix}.{module_name}")
                    class_name = "".join(word.capitalize() for word in module_name.split("_"))
                    if hasattr(module, class_name):
                        tool_class = getattr(module, class_name)
                        if hasattr(tool_class, "PARAM_NAME") and hasattr(tool_class, "check"):
                            tools_map[tool_class.PARAM_NAME] = tool_class.check
                            continue
                    param_key = getattr(module, "PARAM_NAME", None) or module_param_map.get(module_name)
                    candidate_funcs = []
                    preferred_names = [ "analyze_meta_title_tool", "analyze_meta_description_tool", "analyze_robots_txt", "analyze_xml_sitemap", "analyze_canonical_tag_tool", "analyze_og_tags_tool", "analyze_hreflang_tags_tool", "analyze_internal_linking_tool", "analyze_breadcrumb_tool", "check_responsive_design_tool", "check_intrusive_interstitials_tool", "check_ssl_certificate_tool", "check_mixed_content_tool", "analyze_heading_tags_tool", "analyze_heading_text_tool", "analyze_image_alt_text_tool", "check_hidden_content_tool", "analyze_keyword_density_tool", "analyze_duplicate_content_tool", "check_thin_content_tool", "analyze_server_logs_tool", "find_crawl_traps_tool", "check_404_errors_tool", "check_broken_links_tool", "check_redirect_chains_tool", "analyze_schema_markup_tool", "check_ga_setup_tool", "check_gsc_setup_tool", "analyze_eeat_tool", "analyze_geo_friendly_tool", "analyze_faq_in_blog_tool", "check_llmstext_file_tool", "analyze_ai_visibility_tool", "analyze_page_speed_tool", "analyze_url_structure_tool", ]
                    for name in preferred_names:
                        if hasattr(module, name):
                            obj = getattr(module, name)
                            if callable(obj) or hasattr(obj, "invoke"):
                                candidate_funcs.append(obj)
                                break
                    if not candidate_funcs:
                        candidate_funcs = [ getattr(module, name) for name in dir(module) if not name.startswith("_") and (name.startswith("analyze_") or name.startswith("check_") or name.endswith("_tool")) and (callable(getattr(module, name)) or hasattr(getattr(module, name), "invoke")) ]
                    if param_key and candidate_funcs:
                        tools_map[param_key] = candidate_funcs[0]
                    elif param_key and not candidate_funcs:
                        print(f"Warning: No callable tool function found in module {module_name} for param '{param_key}'.")
                except Exception as e:
                    print(f"Error loading tool {filename}: {e}")
        if "duplicate_content" in tools_map and "similar_urls" not in tools_map:
            tools_map["similar_urls"] = tools_map["duplicate_content"]
        return tools_map

    def _normalize_tool_result(self, result: Any) -> Dict[str, Any]:
        if isinstance(result, dict):
            if "status" not in result or result.get("status") is None:
                if "overall_status" in result: result["status"] = result.get("overall_status")
                elif "h1_status" in result:
                    h1_status = result.get("h1_status")
                    if h1_status == "success": result["status"] = "success"
                    elif h1_status == "warning": result["status"] = "warning"
                    else: result["status"] = "error"
                else: result["status"] = "info"
            if str(result.get("status")).lower() == "pass": result["status"] = "success"
            result.setdefault("message", ""); result.setdefault("details", {}); result.setdefault("remediation", ""); result.setdefault("reason", "")
            if (result.get("details") == {} or result.get("details") == []) and result.get("message"):
                result["details"] = {"note": result.get("message")}
            return result
        if isinstance(result, list): return {"status": "success", "message": "Tool returned list output.", "details": result}
        if isinstance(result, str): return {"status": "info", "message": result, "details": {}}
        return {"status": "info", "message": "Tool returned an unsupported type.", "details": {}}

    def _status_value(self, status: Any) -> str:
        if hasattr(status, "value"):
            return str(status.value)
        return str(status)

    def _run_async(self, coro):
        try: loop = asyncio.get_running_loop()
        except RuntimeError: loop = None
        if loop and loop.is_running():
            nest_asyncio.apply()
            return asyncio.get_event_loop().run_until_complete(coro)
        return asyncio.run(coro)

    def _summarize_details(self, details: Any, max_len: int = 300) -> str:
        if details is None: return ""
        try:
            if isinstance(details, (dict, list)): text = json.dumps(details, ensure_ascii=True)
            else: text = str(details)
        except Exception: text = str(details)
        if len(text) > max_len: return text[:max_len] + "..."
        return text

    def _compose_reason(self, tool_result: Dict[str, Any]) -> str:
        parts = []
        message = tool_result.get("message") or ""; remediation = tool_result.get("remediation") or ""; reason = tool_result.get("reason") or ""
        details = self._summarize_details(tool_result.get("details"))
        if message: parts.append(message)
        if reason and reason not in message: parts.append(reason)
        if remediation and remediation not in message and remediation not in reason: parts.append(f"Remediation: {remediation}")
        if details: parts.append(f"Details: {details}")
        return " ".join(p.strip() for p in parts if p.strip())

    def _call_tool_flex(self, tool_func: Callable, url: str, html_content: str, audit_map: AuditMap, criteria_for_param: Dict[str, Any], page_context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        if page_context is None: page_context = {}
        if hasattr(tool_func, "invoke"):
            kwargs = { "url": url, "base_url": url, "html_content": html_content, "criteria": criteria_for_param.get("validation_params", criteria_for_param), "audit_map": audit_map, }
            kwargs.update({ "page_url": url, "canonical_url": page_context.get("canonical_url"), "og_tags": page_context.get("og_tags"), "hreflang_tags": page_context.get("hreflang_tags"), "h1_tags": page_context.get("h1_tags", []), "h2_tags": page_context.get("h2_tags", []), "h3_tags": page_context.get("h3_tags", []), "h1_content": page_context.get("h1_tags", []), "h2_content": page_context.get("h2_tags", []), "h3_content": page_context.get("h3_tags", []), "image_alt_texts": page_context.get("image_alt_texts", []), "schema_markup": page_context.get("schema_markup", []), "text_content": page_context.get("clean_text_content", ""), "page_text_content": page_context.get("clean_text_content", ""), "urls_to_check": page_context.get("all_links", []), "robots_txt_content": page_context.get("robots_txt_content"), "sources": page_context.get("sources"), })
            if hasattr(tool_func, "ainvoke"): return self._normalize_tool_result(self._run_async(tool_func.ainvoke(kwargs)))
            result = tool_func.invoke(kwargs)
            if inspect.isawaitable(result): return self._normalize_tool_result(self._run_async(result))
            return self._normalize_tool_result(result)
        sig = inspect.signature(tool_func); kwargs = {}
        for name in sig.parameters.keys():
            if name in ["url", "page_url"]: kwargs[name] = url
            elif name in ["base_url"]: kwargs[name] = url
            elif name in ["html_content", "page_html"]: kwargs[name] = html_content
            elif name in ["canonical_url"]: kwargs[name] = page_context.get("canonical_url")
            elif name in ["og_tags"]: kwargs[name] = page_context.get("og_tags")
            elif name in ["hreflang_tags"]: kwargs[name] = page_context.get("hreflang_tags")
            elif name in ["h1_tags"]: kwargs[name] = page_context.get("h1_tags", [])
            elif name in ["h2_tags"]: kwargs[name] = page_context.get("h2_tags", [])
            elif name in ["h3_tags"]: kwargs[name] = page_context.get("h3_tags", [])
            elif name in ["h1_content"]: kwargs[name] = page_context.get("h1_tags", [])
            elif name in ["h2_content"]: kwargs[name] = page_context.get("h2_tags", [])
            elif name in ["h3_content"]: kwargs[name] = page_context.get("h3_tags", [])
            elif name in ["image_alt_texts"]: kwargs[name] = page_context.get("image_alt_texts", [])
            elif name in ["schema_markup"]: kwargs[name] = page_context.get("schema_markup", [])
            elif name in ["text_content", "page_text_content"]: kwargs[name] = page_context.get("clean_text_content", "")
            elif name in ["urls_to_check", "all_links"]: kwargs[name] = page_context.get("all_links", [])
            elif name in ["robots_txt_content"]: kwargs[name] = page_context.get("robots_txt_content")
            elif name in ["sources"]: kwargs[name] = page_context.get("sources")
            elif name in ["criteria", "criteria_for_param", "rule"]: kwargs[name] = criteria_for_param.get("validation_params", criteria_for_param)
            elif name in ["audit_map"]: kwargs[name] = audit_map
        result = tool_func(**kwargs)
        if inspect.isawaitable(result): result = self._run_async(result)
        return self._normalize_tool_result(result)

    def dispatch_extraction(self, audit_map: AuditMap, url: str, html_content: str, allowed_params: List[str] | None = None, compare_field: str | None = None, is_post_crawl: bool = False):
        """
        Dispatches extraction and validation tasks. It first checks the KB using the
        HybridRetriever. If a high-confidence and relevant match is found, it uses the cached data.
        Otherwise, it proceeds with live tool execution.
        """
        page_state = audit_map.get_page_state(url)
        if not page_state:
            print(f"Warning: Page state not found for URL: {url}. Initializing with all criteria.")
            audit_map.add_page(url, list(self.criteria.keys()))
            page_state = audit_map.get_page_state(url)

        page_context = {}
        if html_content:
            page_context = self._call_tool_flex(parse_html_and_extract_tags, url, html_content, audit_map, {}, {})
        
            if page_context.get("clean_text_content"):
                _PAGE_FINGERPRINT_CACHE[url] = {
                    "text_content": page_context.get("clean_text_content"),
                    "meta_title": page_context.get("title"),
                    "meta_description": page_context.get("meta_description"),
                    "h1_tags": page_context.get("h1_tags"),
                    "images": page_context.get("image_alt_texts")
                }
            
        elif url in _PAGE_FINGERPRINT_CACHE:
            # Reconstruct page_context from cache for post-crawl or targeted runs
            fingerprint = _PAGE_FINGERPRINT_CACHE[url]
            page_context = {
                "clean_text_content": fingerprint.get("text_content"),
                "title": fingerprint.get("meta_title"),
                "meta_description": fingerprint.get("meta_description"),
                "h1_tags": fingerprint.get("h1_tags"),
                "image_alt_texts": fingerprint.get("images"),
            }
        
        from urllib.parse import urlparse
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        if base_url not in _SITE_CACHE: _SITE_CACHE[base_url] = {}

        for param_name, param_state in page_state.parameters.items():
            if allowed_params is not None and param_name not in allowed_params: continue
            
            # --- REAL-TIME AUDIT LOGGING ---
            # --- END LOGGING ---

            # IMPORTANT: During a targeted re-extraction (allowed_params is not None), 
            # we ignore the PENDING status to allow re-running tools that previously failed.
            if self._status_value(param_state.status) == AuditStatus.PENDING.value or allowed_params is not None:
                retriever_query = param_name.replace('_', ' ')
                # Only check KB if this is the first PENDING attempt, not a targeted fallback
                if self._status_value(param_state.status) == AuditStatus.PENDING.value and allowed_params is None:
                    # ... (KB logic remains same) ...
                    kb_results = self.retriever.search(retriever_query, target_url=url, top_n=1)
                    
                    if kb_results and kb_results[0][1] > self.BM25_THRESHOLD:
                        atom, score = kb_results[0]
                        if atom['metadata'].get('type') == param_name:
                            print(f"KB HIT for '{param_name}' on {url} with score {score:.2f}. Bypassing live tool.")
                            
                            try:
                                parts = {p.split(': ', 1)[0]: p.split(': ', 1)[1] for p in atom['text'].split(' | ')}
                                value_str = parts.get('Value', '')
                                reasoning = parts.get('Reasoning', 'Data sourced from Knowledge Base.')
                                parsed_value = json.loads(value_str)
                                value_to_store = parsed_value if not (isinstance(parsed_value, dict) and ('value' in parsed_value or 'character_count' in parsed_value)) else parsed_value
                            except Exception: value_to_store = value_str

                            audit_map.update_parameter_state(url, param_name, status=AuditStatus.VALIDATED, value=value_to_store, llm_reasoning=reasoning, remediation_suggestion="Data sourced from Knowledge Base.")
                            continue

                if param_name in self.parameter_tools:
                    # --- REAL-TIME AUDIT LOGIC ---
                    print(f"  [AUDIT] Processing '{param_name}' for {url}...")
                    # ---------------------------

                    tool_check_func = self.parameter_tools[param_name]
                    criteria_for_param = self.criteria.get(param_name, {})
                    try:
                        if param_name in ["robots_txt", "xml_sitemap"]:
                            cached = _SITE_CACHE[base_url].get(param_name)
                            if cached is not None: tool_result = cached
                            else:
                                if param_name == "xml_sitemap": page_context["robots_txt_content"] = _SITE_CACHE[base_url].get("robots_txt_content")
                                tool_result = self._call_tool_flex(tool_check_func, base_url, html_content, audit_map, criteria_for_param, page_context)
                                _SITE_CACHE[base_url][param_name] = tool_result
                                if param_name == "robots_txt" and isinstance(tool_result, dict):
                                    details = tool_result.get("details") or {}; _SITE_CACHE[base_url]["robots_txt_content"] = details.get("content")
                        else: tool_result = None

                        if param_name in ["duplicate_content", "similar_urls"]:
                            active_compare_field = compare_field or "text_content"
                            if not compare_field and isinstance(criteria_for_param, dict): 
                                active_compare_field = ( criteria_for_param.get("validation_params", {}).get("compare_field") or criteria_for_param.get("compare_field") or active_compare_field )
                            
                            # --- COMPREHENSIVE SOURCE PREPARATION FROM CACHE ---
                            sources = []
                            for u, fingerprint in _PAGE_FINGERPRINT_CACHE.items():
                                sources.append({
                                    "name": u,
                                    "type": "text",
                                    "value": fingerprint.get("text_content", ""),
                                    "fields": fingerprint
                                })
                            # --------------------------------------------------
                            page_context = {**page_context, "sources": sources}

                        if tool_result is None:
                            tool_result = self._call_tool_flex(tool_check_func, url, html_content, audit_map, criteria_for_param, page_context)
                        
                        status_val = tool_result.get("status", "info")
                        if isinstance(status_val, AuditStatus): status = status_val
                        else:
                            status_str = str(status_val).lower()
                            if status_str in ["success", "pass", "validated"]: status = AuditStatus.VALIDATED
                            elif status_str in ["warning", "needs_improvement", "info", "extracted"]: status = AuditStatus.EXTRACTED
                            else: status = AuditStatus.FAILED

                        composed_reason = self._compose_reason(tool_result)
                        val = tool_result.get("raw_data") or tool_result.get("details") or tool_result.get("value")
                        if not val: val = {k: v for k, v in tool_result.items() if k not in ["status", "message", "remediation", "reason", "overall_status", "assessment"]}
                        
                        final_value = val.get("value") if isinstance(val, dict) and "value" in val else val

                        if param_name in ["meta_title", "meta_description"] and isinstance(final_value, str):
                            final_value = {"value": final_value, "character_count": len(final_value)}
                        elif param_name == "heading_tags" and isinstance(final_value, dict):
                            target_dict = final_value.get("details", final_value)
                            for h_key in ["h1_content", "h2_content", "h3_content"]:
                                if h_key in target_dict and isinstance(target_dict[h_key], list):
                                    count_key = h_key.replace("_content", "_lengths")
                                    target_dict[count_key] = [len(str(h)) for h in target_dict[h_key]]

                        audit_map.update_parameter_state(url, param_name, status=status, value=final_value, remediation_suggestion=composed_reason or "No specific remediation suggestion.", llm_reasoning=composed_reason or "No specific reasoning.")
                    except Exception as e:
                        print(f"Error processing {param_name} for {url}: {e}")
                        audit_map.update_parameter_state( url, param_name, status=AuditStatus.FAILED, remediation_suggestion=str(e), llm_reasoning=str(e) )

