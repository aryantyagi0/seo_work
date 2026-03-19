from typing import Dict, Any, List, Tuple, Optional
import os
import json
from datetime import datetime
import io
import re
import logging
import textwrap
from urllib.parse import urlparse
import pandas as pd
from kb.kb_manager import save_audit_results, save_report_file
from utils.llm_utils import call_llm_completion

class FinalOutputAgent:
    def __init__(self):
        pass

    def _report_columns(self) -> List[Tuple[str, str, str]]:
        return [
            ("Pages", "pages_category", "Pages Category"),
            ("Pages", "pages", "Pages"),
            ("Crawlability & Indexing", "robots_txt", "Robots.txt configured correctly"),
            ("Crawlability & Indexing", "xml_sitemap", "XML Sitemap updated & submitted"),
            ("Crawlability & Indexing", "canonical_tag", "Canonical tags implemented"),
            ("Site Architecture", "site_hierarchy", "Logical site hierarchy"),
            ("Site Architecture", "internal_linking", "Internal linking optimization"),
            ("Site Architecture", "breadcrumbs", "Breadcrumb navigation"),
            ("Mobile-Friendliness", "responsive_design", "Responsive design"),
            ("Mobile-Friendliness", "no_intrusive_interstitials", "No intrusive interstitials"),
            ("HTTPS & Security", "ssl_certificate", "SSL certificate active"),
            ("HTTPS & Security", "mixed_content", "No mixed content warnings"),
            ("On-Page Technical Elements", "meta_title", "Meta Title <60 Characters Including Space>"),
            ("On-Page Technical Elements", "meta_description", "Meta Description <160 Characters Including Space>"),
            ("On-Page Technical Elements", "heading_tags", "Heading Tags(H1/H2/H3)"),
            ("On-Page Technical Elements", "heading_text_analysis", "Heading Tags Text(H1/H2/H3)"),
            ("On-Page Technical Elements", "image_alt_text", "Image Alt Text & Tag"),
            ("On-Page Technical Elements", "hidden_content", "Hidden Content"),
            ("Content Quality & Duplication", "keyword_density", "Keyword Density"),
            ("Content Quality & Duplication", "duplicate_content", "Duplicate content check"),
            ("Content Quality & Duplication", "similar_urls", "Similar URLs (Similarity Score)"),
            ("Content Quality & Duplication", "thin_content", "Thin content audit"),
            ("Logs & Crawl Budget Optimization", "server_logs", "Analyze server logs"),
            ("Logs & Crawl Budget Optimization", "crawl_traps", "Avoid crawl traps"),
            ("Redirects & Broken Links", "errors_404", "404 Errors"),
            ("Redirects & Broken Links", "broken_links", "Broken Links"),
            ("Redirects & Broken Links", "redirect_chains", "Avoid redirect chains/loops"),
            ("Structured Data & Rich Results", "schema_markup", "Schema markup implemented"),
            ("Structured Data & Rich Results", "og_tags", "Open Graph & Twitter cards"),
            ("International SEO", "hreflang_tags", "Hreflang tags implemented"),
            ("International SEO", "consistent_language_targeting", "Consistent language targeting"),
            ("Analytics & Tracking", "ga_setup", "Google Analytics/GA4 setup"),
            ("Analytics & Tracking", "gsc_setup", "Google Search Console setup"),
            ("GEO perspective/AI SEO Parameters", "eeat", "EEAT (Experience, Expertise, Authority, Trust)"),
            ("GEO perspective/AI SEO Parameters", "geo_friendly", "GEO Friendly (readiness for AI search engines)"),
            ("GEO perspective/AI SEO Parameters", "faq_in_blog", "FAQ In Blog"),
            ("GEO perspective/AI SEO Parameters", "llms_txt", "LLMS.txt File"),
            ("GEO perspective/AI SEO Parameters", "ai_visibility", "AI Visibility"),
            ("Page Speed & Core Web Vitals", "lcp", "Largest Contentful Paint (LCP)"),
            ("Page Speed & Core Web Vitals", "fid_inp", "First Input Delay (FID/INP)"),
            ("Page Speed & Core Web Vitals", "cls", "Cumulative Layout Shift (CLS)"),
            ("Page Speed & Core Web Vitals", "mobile_speed", "Mobile page speed performance"),
        ]

    def format_response(self, query_resolution_output: Dict[str, Any]) -> str:
        """
        Formats the output from the QueryResolver into a user-friendly string.
        """
        action = query_resolution_output.get("action")
        response_message = query_resolution_output.get("response")

        if action == "respond":
            return response_message
        elif action == "request_url":
            return response_message
        elif action == "start_audit":
            return f"Starting an audit for {query_resolution_output.get('url')}..."
        else:
            return "Sorry, something went wrong with processing your request."

    def build_report_dataframe(self, audit_map_dict: Dict[str, Any], use_multiindex: bool = False) -> pd.DataFrame:
        columns = self._report_columns()

        def _page_category(url: str) -> str:
            parsed = urlparse(url)
            path = parsed.path.strip("/")
            if not path:
                return "Homepage"
            if "blog" in path.lower().split("/"):
                return "Blog"
            return "Internal Page"

        def _status_to_text(status: str) -> str:
            if not status:
                return "not_audited"
            if status == "validated":
                return "pass"
            if status == "failed":
                return "fail"
            if status in ["skipped", "pending"]:
                return "not_audited"
            return "needs_improvement"

        def _explain(param_key: str, param_state: Dict[str, Any]) -> str:
            if not param_state or not isinstance(param_state, dict):
                return "Not audited."
            status = _status_to_text(param_state.get("status"))
            message = param_state.get("llm_reasoning") or param_state.get("remediation_suggestion") or ""

            value_preview = ""
            value = param_state.get("value")
            if value:
                try:
                    if isinstance(value, (dict, list)):
                        value_preview = json.dumps(value, ensure_ascii=True)
                    else:
                        value_preview = str(value)
                except Exception:
                    value_preview = str(value)
                if len(value_preview) > 200:
                    value_preview = value_preview[:200] + "..."

            parts = []
            if status == "pass":
                parts.append("Pass.")
            elif status == "fail":
                parts.append("Fail.")
            elif status == "not_audited":
                return "Not audited."
            else:
                parts.append("Needs improvement.")

            if message:
                parts.append(message)
            return " ".join(p.strip() for p in parts if p.strip())

        records = []
        pages = audit_map_dict.get("pages", {})
        for url, page_data in pages.items():
            params = page_data.get("parameters", {})
            record = {}
            for group, key, label in columns:
                if key == "pages_category":
                    record[label] = _page_category(url)
                elif key == "pages":
                    record[label] = url
                elif key == "consistent_language_targeting":
                    # Derive from hreflang tags if available
                    hreflang = params.get("hreflang_tags", {})
                    record[label] = _explain("hreflang_tags", hreflang)
                elif key in ["lcp", "fid_inp", "cls", "mobile_speed"]:
                    ps = params.get("page_speed") # Get the value, which could be None or not a dict
                    if not isinstance(ps, dict):
                        # If page_speed data is missing or not a dictionary, fill with N/A
                        record[label] = "N/A"
                        continue

                    details = ps.get("value") # The value might be None or not a dict
                    
                    # Prepare reasoning text, which might be at the top level
                    reasoning = ps.get('llm_reasoning','') or ""

                    if isinstance(details, str):
                        record[label] = details
                    elif not isinstance(details, dict):
                        # If details isn't a dict, we can't get scores from it.
                        # Use the top-level reasoning or status as a fallback.
                        record[label] = reasoning or ps.get('status', 'not audited')
                    else:
                        # Now we know details is a dict, we can safely .get()
                        if key == "lcp":
                            record[label] = f"LCP: {details.get('lcp_score', 'N/A')}s. {reasoning}".strip()
                        elif key == "fid_inp":
                            record[label] = f"INP/FID: {details.get('fid_inp_score', 'N/A')}ms. {reasoning}".strip()
                        elif key == "cls":
                            record[label] = f"CLS: {details.get('cls_score', 'N/A')}. {reasoning}".strip()
                        else:
                            record[label] = f"Mobile performance score: {details.get('mobile_page_speed_performance', 'N/A')}. {reasoning}".strip()
                else:
                    record[label] = _explain(key, params.get(key, {}))
            records.append(record)

        df = pd.DataFrame(records)
        if use_multiindex:
            multi_cols = [(group, label) for group, _, label in columns]
            df.columns = pd.MultiIndex.from_tuples(multi_cols)
        return df

    def generate_excel_report(self, audit_map_dict: Dict[str, Any], output_dir: str = "reports") -> Dict[str, Any]:
        """
        Generates an Excel report from AuditMap.to_dict() style data.
        Saves audit JSON and report into KB.
        """
        os.makedirs(output_dir, exist_ok=True)

        columns = self._report_columns()
        df = self.build_report_dataframe(audit_map_dict, use_multiindex=False)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_filename = os.path.join(output_dir, f"audit_report_{timestamp}.xlsx")

        with pd.ExcelWriter(report_filename, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Audit", startrow=1, header=False)
            ws = writer.sheets["Audit"]

            group_headers = [group for group, _, _ in columns]
            for col_idx, group_name in enumerate(group_headers, start=1):
                ws.cell(row=1, column=col_idx, value=group_name)
            for col_idx, (_, _, label) in enumerate(columns, start=1):
                ws.cell(row=2, column=col_idx, value=label)

            start = 0
            while start < len(group_headers):
                end = start
                while end + 1 < len(group_headers) and group_headers[end + 1] == group_headers[start]:
                    end += 1
                if end > start:
                    ws.merge_cells(start_row=1, start_column=start + 1, end_row=1, end_column=end + 1)
                start = end + 1

        audit_id = save_audit_results(None, audit_map_dict)
        kb_report_path = save_report_file(report_filename, audit_id=audit_id)

        return {"report_path": report_filename, "kb_report_path": kb_report_path, "audit_id": audit_id, "report_df": df}

    def _load_criteria_map(self) -> Dict[str, Any]:
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            kb_path = os.path.join(base_dir, "..", "kb", "criteria.json")
            with open(kb_path, "r", encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception:
            return {}

    def generate_pdf_report(
        self,
        audit_map_dict: Dict[str, Any],
        output_dir: str = "reports",
        audit_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generates a PDF report with a table of contents, criteria explanations,
        issues per page (only where issues exist), and recommendations.
        """
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.lib import colors
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle, Image
            from reportlab.platypus.tableofcontents import TableOfContents
            from reportlab.lib.utils import ImageReader
            import requests
        except Exception as e:
            raise RuntimeError(f"ReportLab is required for PDF generation: {e}")

        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_filename = os.path.join(output_dir, f"audit_report_{timestamp}.pdf")

        criteria_map = self._load_criteria_map()
        columns = self._report_columns()
        pages = audit_map_dict.get("pages", {})

        def _page_category(url: str) -> str:
            parsed = urlparse(url)
            path = parsed.path.strip("/")
            if not path:
                return "Homepage"
            if "blog" in path.lower().split("/"):
                return "Blog"
            return "Internal Page"

        def _status_to_text(status: Optional[str]) -> str:
            if not status:
                return "not_audited"
            if status == "validated":
                return "pass"
            if status == "failed":
                return "fail"
            if status in ["skipped", "pending"]:
                return "not_audited"
            return "needs_improvement"

        def _value_preview(value: Any, max_len: int = 180) -> str:
            if value is None:
                return ""
            try:
                if isinstance(value, (dict, list)):
                    text = json.dumps(value, ensure_ascii=True)
                else:
                    text = str(value)
            except Exception:
                text = str(value)
            if len(text) > max_len:
                return text[:max_len] + "..."
            return text

        def _short_text(text: str, max_len: int = 80) -> str:
            if not text:
                return ""
            cleaned = _clean_text(text)
            if len(cleaned) > max_len:
                return cleaned[:max_len].rstrip() + "..."
            return cleaned

        def _list_preview(items: List[Any], max_items: int = 2, max_len: int = 60) -> str:
            if not items:
                return "0 items"
            sample = []
            for item in items[:max_items]:
                if isinstance(item, (dict, list)):
                    sample.append(_value_preview(item, max_len=max_len))
                else:
                    sample.append(_short_text(str(item), max_len=max_len))
            if len(items) > max_items:
                return f"{len(items)} items, e.g. " + ", ".join(sample)
            return ", ".join(sample)

        def _compact_evidence_dict(value: Dict[str, Any], max_items: int = 6) -> str:
            if not value:
                return ""
            priority_terms = [
                "missing", "error", "issue", "invalid", "warning", "note",
                "count", "ratio", "score", "similar", "duplicate", "canonical",
                "h1", "h2", "h3", "title", "description", "alt", "content",
                "link", "url", "tag", "schema", "status", "question",
            ]
            keys = list(value.keys())
            picked = []
            for key in keys:
                lk = key.lower()
                if any(term in lk for term in priority_terms):
                    picked.append(key)
            if not picked:
                picked = keys[:max_items]
            picked = picked[:max_items]
            lines = []
            for key in picked:
                val = value.get(key)
                if isinstance(val, float):
                    val_text = f"{val:.4f}"
                elif isinstance(val, int):
                    val_text = str(val)
                elif isinstance(val, list):
                    val_text = _list_preview(val, max_items=2, max_len=60)
                elif isinstance(val, dict):
                    val_text = _value_preview(val, max_len=90)
                else:
                    val_text = _short_text(str(val), max_len=90)
                if val_text:
                    lines.append(f"{key}: {val_text}")
            if not lines:
                return _value_preview(value, max_len=120)
            return "\n".join(lines)

        def _criteria_summary(entry: Dict[str, Any]) -> str:
            if not entry:
                return "Criteria: Not defined."
            vtype = entry.get("validation_type", "not specified")
            params = entry.get("validation_params") or {}
            if params:
                params_text = ", ".join([f"{k}={v}" for k, v in params.items()])
                return f"Criteria: {vtype}. Parameters: {params_text}."
            return f"Criteria: {vtype}."

        why_map = {
            "Crawlability & Indexing": "These checks help search engines discover, crawl, and index your pages.",
            "Site Architecture": "Clear structure and linking improve crawl efficiency and user navigation.",
            "Mobile-Friendliness": "Mobile usability affects rankings and user engagement.",
            "HTTPS & Security": "Secure pages build trust and are a ranking signal.",
            "On-Page Technical Elements": "These elements help search engines interpret page content and intent.",
            "Content Quality & Duplication": "Unique, useful content improves rankings and prevents cannibalization.",
            "Logs & Crawl Budget Optimization": "Crawl efficiency ensures important pages are discovered first.",
            "Redirects & Broken Links": "Broken or inefficient redirects harm UX and dilute ranking signals.",
            "Structured Data & Rich Results": "Schema can improve visibility with enhanced search results.",
            "International SEO": "Correct targeting prevents region and language mismatches.",
            "Analytics & Tracking": "Tracking enables measurement and continuous optimization.",
            "GEO perspective/AI SEO Parameters": "Improves visibility in AI-driven search and trust signals.",
            "Page Speed & Core Web Vitals": "Performance and stability improve UX and rankings.",
        }

        special_descriptions = {
            "consistent_language_targeting": "Language targeting should be consistent and aligned with hreflang tags.",
            "lcp": "Largest Contentful Paint (LCP) measures main content load time.",
            "fid_inp": "INP/FID measures responsiveness to user input.",
            "cls": "Cumulative Layout Shift (CLS) measures visual stability.",
            "mobile_speed": "Overall mobile performance score for the page.",
        }

        def _param_state_for_key(params: Dict[str, Any], key: str) -> Tuple[Optional[Dict[str, Any]], str]:
            if key == "consistent_language_targeting":
                return params.get("hreflang_tags"), ""
            if key in ["lcp", "fid_inp", "cls", "mobile_speed"]:
                ps = params.get("page_speed")
                details = ""
                if isinstance(ps, dict):
                    value = ps.get("value")
                    if isinstance(value, dict):
                        if key == "lcp":
                            details = f"LCP: {value.get('lcp_score', 'N/A')}s"
                        elif key == "fid_inp":
                            details = f"INP/FID: {value.get('fid_inp_score', 'N/A')}ms"
                        elif key == "cls":
                            details = f"CLS: {value.get('cls_score', 'N/A')}"
                        else:
                            details = f"Mobile performance score: {value.get('mobile_page_speed_performance', 'N/A')}"
                return ps, details
            return params.get(key), ""

        def _clean_text(text: str) -> str:
            if not text:
                return ""
            text = text.replace("\r", " ").replace("\n", " ")
            text = re.sub(r"[A-Z]:\\\\[^ ]+", "", text)
            text = re.sub(r"\s{2,}", " ", text).strip()
            return text

        def _wrap_text(text: str, width: int = 84) -> str:
            if not text:
                return ""
            lines = text.splitlines()
            wrapped = []
            for line in lines:
                if not line:
                    wrapped.append("")
                    continue
                indent = re.match(r"\s*", line).group(0)
                wrapped.append(textwrap.fill(
                    line,
                    width=width,
                    subsequent_indent=indent,
                    break_long_words=True,
                    break_on_hyphens=False,
                    replace_whitespace=False,
                    drop_whitespace=False,
                ))
            return "\n".join(wrapped)

        def _format_code_block(text: str, max_lines: int = 12, width: int = 84) -> str:
            wrapped = _wrap_text(text, width=width)
            lines = wrapped.splitlines()
            if len(lines) > max_lines:
                lines = lines[:max_lines] + ["..."]
            return "\n".join(lines)

        def _format_json(value: Any, max_lines: int = 12, width: int = 84) -> str:
            try:
                text = json.dumps(value, indent=2, ensure_ascii=True)
            except Exception:
                text = str(value)
            return _format_code_block(text, max_lines=max_lines, width=width)

        def _summarize_message(message: str) -> str:
            msg = _clean_text(message)
            if not msg:
                return ""
            if "lighthouse" in msg.lower() or "npm error" in msg.lower():
                return "Page speed audit could not be completed due to missing Lighthouse dependencies."
            if "Details:" in msg:
                msg = msg.split("Details:", 1)[0].strip()
            if "images found" in msg:
                m = re.search(r"\d+ images found[^.]*\.", msg)
                if m:
                    return m.group(0).strip()
            if "." in msg:
                msg = msg.split(".", 1)[0].strip() + "."
            if len(msg) > 220:
                msg = msg[:217].rstrip() + "..."
            return msg

        def _friendly_missing_list(items: List[str]) -> str:
            if not items:
                return ""
            mapping = {
                "author_details": "author credentials",
                "author_summary": "author bio/summary",
                "author_name_present": "author name",
                "author_experience_present": "author experience",
                "author_social_profile_present": "author social profile",
            }
            friendly = [mapping.get(i, i.replace("_", " ")) for i in items]
            return ", ".join(friendly)

        def _issue_evidence(param_state: Optional[Dict[str, Any]], extra_value: str, key: str) -> str:
            if extra_value:
                return extra_value
            if not param_state:
                return ""
            value = param_state.get("value")
            if key in ["meta_title", "meta_description"] and isinstance(value, str):
                return f'Current: "{_clean_text(value)}"'
            if isinstance(value, dict):
                if value.get("missing"):
                    return f"Missing: {_friendly_missing_list(value.get('missing', []))}"
                if value.get("note"):
                    return _clean_text(str(value.get("note")))
                if key == "canonical_tag" and value.get("normalized_canonical"):
                    return f"Canonical: {value.get('normalized_canonical')}"
                if "count" in value:
                    return _clean_text(f"Count: {value.get('count')}")
                if "errors" in value and isinstance(value.get("errors"), list):
                    errs = value.get("errors") or []
                    return "Errors: " + _list_preview(errs, max_items=2, max_len=70)
                return _compact_evidence_dict(value, max_items=6)
            if isinstance(value, list):
                if key == "image_alt_text":
                    missing = [i for i in value if isinstance(i, dict) and i.get("status") == "missing"]
                    return f"Missing alt on {len(missing)} of {len(value)} images."
                return "Examples: " + _list_preview(value, max_items=2, max_len=60)
            if isinstance(value, (str, int, float)):
                text = _clean_text(str(value))
                if len(text) <= 120:
                    return text
            return ""

        def _issue_summary(param_state: Optional[Dict[str, Any]], extra_value: str, key: str) -> str:
            if not param_state:
                return "Issue details not available."
            value = param_state.get("value")
            if key == "eeat" and isinstance(value, dict) and value.get("missing"):
                missing = _friendly_missing_list(value.get("missing", []))
                return f"Missing E-E-A-T author signals: {missing}."
            if key in ["meta_title", "meta_description"]:
                if isinstance(value, str):
                    return "Length is outside the recommended range."
                return "Length is outside the recommended range."
            if key == "heading_tags":
                return "Heading structure is not in the recommended H1/H2/H3 hierarchy."
            if key == "image_alt_text" and isinstance(value, list):
                missing = [i for i in value if isinstance(i, dict) and i.get("status") == "missing"]
                if missing:
                    return f"{len(missing)} images missing alt text."
            message = param_state.get("llm_reasoning") or param_state.get("remediation_suggestion") or ""
            summary = _summarize_message(message)
            if summary:
                return summary
            return "Issue detected by audit checks."

        def _collect_issues_for_key(key: str) -> List[Dict[str, str]]:
            issues = []
            for url, page_data in pages.items():
                params = page_data.get("parameters", {})
                param_state, extra_value = _param_state_for_key(params, key)
                status_text = _status_to_text(param_state.get("status") if isinstance(param_state, dict) else None)
                if status_text in ["fail", "needs_improvement"]:
                    status_label = "Fail" if status_text == "fail" else "Needs improvement"
                    current_value = ""
                    if isinstance(param_state, dict):
                        val = param_state.get("value")
                        if isinstance(val, str):
                            current_value = val
                    issues.append({
                        "url": url,
                        "category": _page_category(url),
                        "status": status_label,
                        "summary": _issue_summary(param_state, extra_value, key),
                        "evidence": _issue_evidence(param_state, extra_value, key),
                        "current_value": current_value,
                    })
            return issues

        def _escape_html(text: str) -> str:
            if text is None:
                return ""
            return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        def _to_paragraph_text(text: str) -> str:
            if text is None:
                return ""
            return _escape_html(text).replace("\n", "<br/>")

        def _to_code_paragraph_text(text: str) -> str:
            if text is None:
                return ""
            escaped = _escape_html(text)
            lines = escaped.split("\n")
            fixed = []
            for line in lines:
                leading = len(line) - len(line.lstrip(" "))
                if leading:
                    line = ("&nbsp;" * leading) + line.lstrip(" ")
                line = line.replace("  ", "&nbsp; ")
                fixed.append(line)
            return "<br/>".join(fixed)

        def _sanitize_recommendations(items: List[str]) -> List[str]:
            cleaned = []
            for item in items:
                text = str(item).strip()
                if not text:
                    continue
                if re.search(r"\\b(characters?|chars?|lengths?)\\b", text, re.IGNORECASE):
                    continue
                cleaned.append(text)
            return cleaned

        def _split_recommendation(text: str) -> Tuple[str, Optional[str]]:
            t = str(text).strip()
            if not t:
                return "", None
            brace_start = t.find("{")
            brace_end = t.rfind("}")
            if brace_start != -1 and brace_end > brace_start:
                snippet = t[brace_start:brace_end + 1]
                if len(snippet) >= 20 and (":" in snippet or "@context" in snippet):
                    pre = t[:brace_start].rstrip(" :")
                    return pre, snippet
            lt = t.find("<")
            gt = t.rfind(">")
            if lt != -1 and gt > lt:
                snippet = t[lt:gt + 1]
                if len(snippet) >= 10 and (
                    "/>" in snippet
                    or "</" in snippet
                    or "=\"" in snippet
                    or "href=" in snippet
                    or "type=" in snippet
                    or "content=" in snippet
                    or "script" in snippet
                    or "meta" in snippet
                    or "link" in snippet
                ):
                    pre = t[:lt].rstrip(" :")
                    return pre, snippet
            if "User-agent:" in t or "Sitemap:" in t:
                if ":" in t:
                    pre, code = t.split(":", 1)
                    if "User-agent" in code or "Sitemap" in code:
                        return pre.strip(), code.strip()
            return t, None

        def _is_highlight_recommendation(text: str, code_text: Optional[str]) -> bool:
            if code_text:
                return True
            if not text:
                return False
            if re.search(r"<[^>]+>", text):
                return True
            if re.search(r"\bexample\b", text, re.IGNORECASE):
                return True
            if re.search(r"\bimportant|critical|must|required|ensure|fix\b", text, re.IGNORECASE):
                return True
            return False

        def _slug_to_title(url: str) -> str:
            try:
                path = urlparse(url).path.strip("/")
            except Exception:
                path = ""
            if not path:
                return "Home"
            parts = [p for p in path.split("/") if p]
            slug = parts[-1] if parts else "Home"
            words = slug.replace("-", " ").replace("_", " ").strip()
            if not words:
                return "Home"
            return " ".join(w.capitalize() for w in words.split())

        def _build_suggested_title(url: str, site: str, max_len: int = 60) -> str:
            topic = _slug_to_title(url)
            base = f"{topic} | {site}"
            return base

        def _build_suggested_description(url: str, site: str, max_len: int = 155) -> str:
            topic = _slug_to_title(url)
            desc = f"{topic} - practical guidance, key takeaways, and next steps from {site}. Learn more and explore related services."
            return desc

        def _detailed_recommendations(key: str, entry: Dict[str, Any], issues: List[Dict[str, str]], site: str) -> List[str]:
            recs = []
            remediation = entry.get("remediation") if entry else None
            if remediation:
                recs.append(remediation)

            key_map = {
                "robots_txt": "Update /robots.txt at the site root. Allow important sections and explicitly disallow low-value or duplicate paths. Include a Sitemap directive pointing to the XML sitemap URL.",
                "xml_sitemap": "Generate an XML sitemap that includes only canonical, indexable URLs. Host it at /sitemap.xml (or sitemap index) and submit it in Google Search Console.",
                "canonical_tag": "Add a canonical link tag in the head of each page pointing to the preferred URL. Ensure it matches the final, indexable URL and is self-referencing.",
                "hreflang_tags": "Add hreflang tags in the head for each language/region version. Include a self-referencing hreflang and reciprocal links across all variants.",
                "meta_title": "Write a unique title that starts with the primary keyword and ends with the brand. Avoid duplicates across pages.",
                "meta_description": "Write a unique description that reflects page intent and includes the primary keyword naturally.",
                "heading_tags": "Ensure a single, descriptive H1 per page and use H2/H3 in a logical hierarchy aligned with page sections.",
                "image_alt_text": "Add concise, descriptive alt text for each informative image. Leave decorative images with empty alt (alt=\"\").",
                "page_speed": "Optimize LCP/INP/CLS by compressing images, deferring non-critical JS/CSS, enabling caching, and using lazy loading for below-the-fold content.",
                "eeat": "Add visible author name, bio, and credentials on content pages. Link to author profiles and include editorial policies and sources where relevant.",
                "ga_setup": "Install GA4 via GTM or gtag.js and verify hits in the GA4 Realtime report.",
                "gsc_setup": "Verify the domain in Google Search Console (DNS or HTML tag) and submit the sitemap.",
            }
            mapped = key_map.get(key)
            if not mapped and key == "consistent_language_targeting":
                mapped = key_map.get("hreflang_tags")
            if not mapped and key in ["lcp", "fid_inp", "cls", "mobile_speed"]:
                mapped = key_map.get("page_speed")
            if mapped:
                recs.append(mapped)

            # Issue-specific examples
            for issue in issues[:2]:
                url = issue.get("url")
                if key == "meta_title":
                    suggested = _build_suggested_title(url, site)
                    recs.append(f'Example title for {url}: "{suggested}"')
                    recs.append(f'Example tag: <title>{suggested}</title>')
                elif key == "meta_description":
                    suggested = _build_suggested_description(url, site)
                    recs.append(f'Example description for {url}: "{suggested}"')
                    recs.append(f'Example tag: <meta name="description" content="{suggested}" />')
                elif key == "canonical_tag":
                    recs.append(f'Example tag: <link rel="canonical" href="{url}" />')
                elif key == "hreflang_tags":
                    recs.append(f'Example tag (in head): <link rel="alternate" hreflang="en-us" href="{url}" />')
                elif key == "robots_txt":
                    recs.append("Example robots.txt: User-agent: * | Allow: / | Sitemap: https://www.example.com/sitemap.xml")
                elif key == "xml_sitemap":
                    recs.append("Example sitemap index entry: <sitemap><loc>https://www.example.com/sitemap.xml</loc></sitemap>")
                elif key == "schema_markup":
                    recs.append('Example JSON-LD: <script type="application/ld+json">{...}</script>')
                elif key == "og_tags":
                    recs.append('Example Open Graph tags: <meta property="og:title" content="Page Title" /> <meta property="og:description" content="Short summary" /> <meta property="og:image" content="https://www.example.com/og.jpg" />')
                elif key == "breadcrumbs":
                    recs.append('Example breadcrumb markup: <nav aria-label="Breadcrumb"><ol><li><a href="/">Home</a></li><li aria-current="page">Section</li></ol></nav>')
                elif key == "ga_setup":
                    recs.append('Example GA4 tag: <script async src="https://www.googletagmanager.com/gtag/js?id=G-XXXX"></script>')
                elif key == "gsc_setup":
                    recs.append('Example verification: <meta name="google-site-verification" content="TOKEN" />')
                elif key == "image_alt_text":
                    recs.append('Example alt text: "Luxury kitchen faucet in brushed steel"')
                elif key == "heading_tags":
                    recs.append("Example structure: H1 = primary page topic, H2 = major sections, H3 = sub-sections.")
                    recs.append('Example tags: <h1>Primary Topic</h1> <h2>Key Section</h2> <h3>Sub-section</h3>')
            return recs[:6]

        def _llm_section_content(key: str, label: str, entry: Dict[str, Any], issues: List[Dict[str, str]], site: str) -> Optional[Dict[str, Any]]:
            if os.getenv("ENABLE_LLM_PDF", "").strip() != "1":
                return None
            if not issues:
                return None
            try:
                compact_issues = []
                for issue in issues[:5]:
                    compact_issues.append({
                        "url": issue.get("url"),
                        "status": issue.get("status"),
                        "summary": issue.get("summary"),
                        "evidence": issue.get("evidence"),
                        "current_value": issue.get("current_value"),
                    })

                payload = {
                    "parameter": key,
                    "label": label,
                    "criteria": {
                        "description": entry.get("description") if entry else "",
                        "validation_type": entry.get("validation_type") if entry else "",
                        "validation_params": entry.get("validation_params") if entry else {},
                        "remediation": entry.get("remediation") if entry else "",
                    },
                    "issues": compact_issues,
                    "site": site,
                }

                system = (
                    "You are an SEO audit writer. Use the provided criteria and issue evidence to produce clear, "
                    "concise sections with concrete, actionable recommendations and examples. Avoid generic wording. "
                    "If the issue involves missing or incorrect HTML tags, include example tag(s) in recommendations. "
                    "Use plain ASCII, no markdown. Do not mention character counts or exact length limits."
                )
                user = (
                    "Return JSON with keys: definition, importance, recommendations. "
                    "recommendations must be a list of 3-6 items and include concrete examples or code snippets where relevant. "
                    "Base all content on the provided issues and criteria. "
                    f"Input: {json.dumps(payload, ensure_ascii=True)}"
                )
                response = call_llm_completion(
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                    response_format={"type": "json_object"},
                    temperature=0.2,
                )
                content = response.choices[0].message.content or "{}"
                data = json.loads(content)
                if not isinstance(data, dict):
                    return None
                return data
            except Exception as e:
                logging.info(f"LLM PDF section failed for {key}: {e}")
                return None

        def _definition_text(entry: Dict[str, Any]) -> str:
            vtype = entry.get("validation_type") if entry else None
            params = entry.get("validation_params") if entry else None
            if vtype == "existence_check":
                detail = "We verify that the required resource or tag exists and is accessible."
            elif vtype == "detection_check":
                detail = "We detect required tags or signals in the HTML output."
            elif vtype == "count_check":
                detail = "We count occurrences and assess whether structure is correct."
            elif vtype == "length_check":
                detail = "We measure length and compare against recommended thresholds."
            elif vtype == "analysis_check":
                detail = "We analyze content and structure for quality and completeness."
            elif vtype == "similarity_check":
                detail = "We compare content similarity across pages and flag high overlap."
            else:
                detail = "We assess the page against the documented criteria."
            if params:
                details = ", ".join([f"{k}={v}" for k, v in params.items()])
                detail = f"{detail} Thresholds/params: {details}."
            return detail

        def _importance_text(group: str, entry: Dict[str, Any]) -> str:
            base = why_map.get(group, "This check supports SEO quality and user experience.")
            vtype = entry.get("validation_type") if entry else None
            if vtype == "existence_check":
                extra = "Missing elements can block discovery or weaken trust signals."
            elif vtype == "detection_check":
                extra = "Absent signals reduce relevance, sharing quality, or rich result eligibility."
            elif vtype == "count_check":
                extra = "Incorrect structure can confuse crawlers and reduce topical clarity."
            elif vtype == "length_check":
                extra = "Out-of-range lengths can truncate snippets and reduce click-through rate."
            elif vtype == "analysis_check":
                extra = "Weak signals here often correlate with lower rankings and poor UX."
            elif vtype == "similarity_check":
                extra = "High similarity can cause cannibalization and index bloat."
            else:
                extra = ""
            return f"{base} {extra}".strip()

        def _pick_cover_image() -> Tuple[Optional[str], Optional[str], Optional[str]]:
            homepage = None
            for url in pages.keys():
                if url.rstrip("/").count("/") <= 2:
                    homepage = url
                    break
            if not homepage:
                return None, None, None
            params = pages.get(homepage, {}).get("parameters", {})
            image_state = params.get("image_alt_text", {})
            value = image_state.get("value") if isinstance(image_state, dict) else None
            if not isinstance(value, list):
                return homepage, None, None
            for item in value:
                src = item.get("src")
                alt = item.get("alt")
                if not src:
                    continue
                lower = src.lower()
                if any(lower.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]):
                    return homepage, src, alt
            return homepage, None, None

        def _fetch_cover_image(src: str) -> Optional[io.BytesIO]:
            try:
                resp = requests.get(src, timeout=8)
                resp.raise_for_status()
                return io.BytesIO(resp.content)
            except Exception:
                return None

        def _infer_site_name() -> str:
            if not pages:
                return "Audited Website"
            first_url = next(iter(pages.keys()))
            try:
                netloc = urlparse(first_url).netloc
                return netloc or "Audited Website"
            except Exception:
                return "Audited Website"

        # Prepare PDF document
        class _TocDocTemplate(SimpleDocTemplate):
            def afterFlowable(self, flowable):
                if isinstance(flowable, Paragraph):
                    style_name = flowable.style.name
                    if style_name in ["Heading1Box", "Heading1"]:
                        level = 0
                    elif style_name in ["Heading2Box", "Heading2"]:
                        level = 1
                    else:
                        return
                    text = flowable.getPlainText()
                    if text.strip().lower() == "table of contents":
                        return
                    self.notify("TOCEntry", (level, text, self.page))

        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(name="TitleLarge", parent=styles["Title"], fontSize=22, leading=26))
        styles.add(ParagraphStyle(name="BodySmall", parent=styles["BodyText"], fontSize=9, leading=12))
        styles.add(ParagraphStyle(name="BodyNormal", parent=styles["BodyText"], fontSize=10, leading=14))
        styles["Heading1"].spaceAfter = 0
        styles["Heading2"].spaceAfter = 0
        styles["Heading3"].spaceAfter = 4
        styles.add(ParagraphStyle(
            name="Heading1Box",
            parent=styles["Heading1"],
            backColor=colors.HexColor("#E9EEF6"),
            textColor=colors.HexColor("#1F2937"),
            leftIndent=6,
            rightIndent=6,
            spaceBefore=6,
            spaceAfter=6,
            borderPadding=6,
        ))
        styles.add(ParagraphStyle(
            name="Heading2Box",
            parent=styles["Heading2"],
            backColor=colors.HexColor("#F3F4F6"),
            textColor=colors.HexColor("#111827"),
            leftIndent=6,
            rightIndent=6,
            spaceBefore=4,
            spaceAfter=4,
            borderPadding=4,
        ))
        styles.add(ParagraphStyle(
            name="RecHeading",
            parent=styles["Heading3"],
            textColor=colors.HexColor("#15803D"),
        ))
        styles.add(ParagraphStyle(
            name="TableCell",
            parent=styles["BodySmall"],
            wordWrap="CJK",
        ))
        styles.add(ParagraphStyle(
            name="CodeBlock",
            parent=styles["BodySmall"],
            fontName="Courier",
            backColor=colors.HexColor("#F8FAFC"),
            borderPadding=6,
            leftIndent=4,
            rightIndent=4,
            wordWrap="CJK",
        ))
        styles.add(ParagraphStyle(
            name="RecCalloutText",
            parent=styles["BodySmall"],
            textColor=colors.HexColor("#0F172A"),
            leftIndent=0,
            rightIndent=0,
        ))
        styles.add(ParagraphStyle(
            name="RecCalloutCode",
            parent=styles["CodeBlock"],
            backColor=None,
            leftIndent=0,
            rightIndent=0,
        ))

        doc = _TocDocTemplate(report_filename, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
        story = []

        def _callout_block(text: str, code: bool = False):
            style = styles["RecCalloutCode"] if code else styles["RecCalloutText"]
            content = _to_code_paragraph_text(text or "") if code else _to_paragraph_text(text or "")
            para = Paragraph(content, style)
            table = Table([[ "", para ]], colWidths=[6, doc.width - 6])
            table.setStyle(TableStyle([
                ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#DCFCE7")),
                ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#16A34A")),
                ("BOX", (1, 0), (1, 0), 0.5, colors.HexColor("#86EFAC")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 0),
                ("TOPPADDING", (0, 0), (0, 0), 0),
                ("BOTTOMPADDING", (0, 0), (0, 0), 0),
                ("LEFTPADDING", (1, 0), (1, 0), 6),
                ("RIGHTPADDING", (1, 0), (1, 0), 6),
                ("TOPPADDING", (1, 0), (1, 0), 6),
                ("BOTTOMPADDING", (1, 0), (1, 0), 6),
            ]))
            return table

        site_name = _infer_site_name()
        story.append(Paragraph("SEO Audit Report", styles["TitleLarge"]))
        story.append(Spacer(1, 12))
        homepage_url, cover_src, cover_alt = _pick_cover_image()
        story.append(Paragraph(f"Audited Site: {site_name}", styles["BodyNormal"]))
        if homepage_url:
            story.append(Paragraph(f"URL: {homepage_url}", styles["BodyNormal"]))
        story.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles["BodyNormal"]))
        if cover_src:
            img_data = _fetch_cover_image(cover_src)
            if img_data:
                try:
                    img_reader = ImageReader(img_data)
                    iw, ih = img_reader.getSize()
                    max_w = doc.width
                    max_h = 220
                    scale = min(max_w / iw, max_h / ih)
                    story.append(Spacer(1, 12))
                    story.append(Image(img_reader, width=iw * scale, height=ih * scale))
                    if cover_alt:
                        story.append(Spacer(1, 4))
                        story.append(Paragraph(f"Homepage image: {cover_alt}", styles["BodySmall"]))
                except Exception:
                    pass
        story.append(PageBreak())

        story.append(Paragraph("Table of Contents", styles["Heading1Box"]))
        toc = TableOfContents()
        toc.levelStyles = [
            ParagraphStyle(fontSize=11, name="TOCHeading1", leftIndent=12, firstLineIndent=-12, spaceBefore=4),
            ParagraphStyle(fontSize=10, name="TOCHeading2", leftIndent=24, firstLineIndent=-12, spaceBefore=2),
            ParagraphStyle(fontSize=9, name="TOCHeading3", leftIndent=36, firstLineIndent=-12, spaceBefore=1),
        ]
        story.append(toc)
        story.append(PageBreak())

        total_pages = len(pages)
        section_index = 1
        story.append(Paragraph(f"{section_index} Introduction", styles["Heading1Box"]))
        story.append(Paragraph(
            "This report explains each audit criterion, its importance, and lists issues found during the audit. "
            "Only pages with issues are listed for each check.",
            styles["BodyNormal"],
        ))
        story.append(Spacer(1, 8))
        story.append(Paragraph(f"Pages audited: {total_pages}", styles["BodyNormal"]))
        story.append(Spacer(1, 12))

        current_group = None
        group_index = 1
        entries = []
        for group, key, label in columns:
            if key in ["pages_category", "pages"]:
                continue
            entries.append({"group": group, "key": key, "label": label})

        group_index = 2
        for entry in entries:
            group = entry["group"]
            key = entry["key"]
            label = entry["label"]

            if group != current_group:
                current_group = group
                group_index_text = f"{group_index} {group}"
                group_index += 1
                sub_index = 1
                story.append(Spacer(1, 10))
                story.append(Paragraph(group_index_text, styles["Heading1Box"]))
                story.append(Spacer(1, 6))

            section_label = f"{group_index - 1}.{sub_index} {label}"
            sub_index += 1
            story.append(Paragraph(section_label, styles["Heading2Box"]))
            criteria_entry = criteria_map.get(key, {})
            if not criteria_entry and key == "consistent_language_targeting":
                criteria_entry = criteria_map.get("hreflang_tags", {})
            if not criteria_entry and key in ["lcp", "fid_inp", "cls", "mobile_speed"]:
                criteria_entry = criteria_map.get("page_speed", {})
            description = special_descriptions.get(key) or criteria_entry.get("description") or "No description available."
            issues = _collect_issues_for_key(key)
            llm_block = _llm_section_content(key, label, criteria_entry, issues, site_name)
            if llm_block and llm_block.get("definition"):
                story.append(Paragraph(f"Definition: {llm_block.get('definition')}", styles["BodyNormal"]))
            else:
                story.append(Paragraph(f"Definition: {description} {_definition_text(criteria_entry)}", styles["BodyNormal"]))
            if llm_block and llm_block.get("importance"):
                story.append(Paragraph(f"Importance: {llm_block.get('importance')}", styles["BodySmall"]))
            else:
                story.append(Paragraph(f"Importance: {_importance_text(group, criteria_entry)}", styles["BodySmall"]))
            story.append(Paragraph(_criteria_summary(criteria_entry), styles["BodySmall"]))
            story.append(Spacer(1, 6))

            if issues:
                story.append(Paragraph("Findings (only issues):", styles["Heading3"]))

                homepage_issues = [i for i in issues if i["category"] == "Homepage"]
                internal_issues = [i for i in issues if i["category"] != "Homepage"]

                def _add_issue_table(title: str, rows: List[Dict[str, str]]):
                    if not rows:
                        return
                    story.append(Paragraph(title, styles["BodySmall"]))
                    data = [["Page", "Status", "Summary", "Evidence"]]
                    def _cell(text: str, code: bool = False) -> Paragraph:
                        style = styles["CodeBlock"] if code else styles["TableCell"]
                        content = _to_code_paragraph_text(text or "") if code else _to_paragraph_text(text or "")
                        return Paragraph(content, style)
                    for issue in rows:
                        evidence_text = issue.get("evidence") or ""
                        evidence_code = "\n" in evidence_text or evidence_text.strip().startswith(("{", "[")) or "Examples:\n" in evidence_text
                        data.append([
                            _cell(issue.get("url", "")),
                            _cell(issue.get("status", "")),
                            _cell(issue.get("summary", "")),
                            _cell(evidence_text, code=evidence_code),
                        ])
                    table = Table(data, colWidths=[170, 70, 140, 160])
                    table.setStyle(TableStyle([
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#FF6B6B")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ]))
                    story.append(table)
                    story.append(Spacer(1, 6))

                _add_issue_table("Homepage issues", homepage_issues)
                _add_issue_table("Internal page issues", internal_issues)
            else:
                story.append(Paragraph("Findings: No issues found across audited pages.", styles["BodySmall"]))
                story.append(Spacer(1, 6))

            recs = []
            if issues:
                if llm_block and isinstance(llm_block.get("recommendations"), list):
                    recs = llm_block.get("recommendations")
                else:
                    recs = _detailed_recommendations(key, criteria_entry, issues, site_name)
            recs = _sanitize_recommendations(recs)
            if recs:
                story.append(Paragraph("Recommendations:", styles["RecHeading"]))
                for idx, rec in enumerate(recs[:5], start=1):
                    rec_text = str(rec)
                    pre_text, code_text = _split_recommendation(rec_text)
                    highlight = _is_highlight_recommendation(rec_text, code_text)
                    if pre_text:
                        if highlight:
                            story.append(_callout_block(f"{idx}. {pre_text}", code=False))
                        else:
                            story.append(Paragraph(f"{idx}. {_to_paragraph_text(pre_text)}", styles["TableCell"]))
                    else:
                        if highlight:
                            story.append(_callout_block(f"{idx}.", code=False))
                        else:
                            story.append(Paragraph(f"{idx}.", styles["TableCell"]))
                    if code_text:
                        code_block = _format_code_block(code_text, max_lines=10, width=76)
                        story.append(_callout_block(code_block, code=True))
                    if highlight:
                        story.append(Spacer(1, 4))
            story.append(Spacer(1, 10))

        doc.multiBuild(story)

        if not audit_id:
            audit_id = save_audit_results(None, audit_map_dict)
        kb_report_path = save_report_file(report_filename, audit_id=audit_id)

        return {"report_path": report_filename, "kb_report_path": kb_report_path, "audit_id": audit_id}