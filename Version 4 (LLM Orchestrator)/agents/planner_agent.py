"""
Planner Agent - LLM Brain 1: The Architect
Decomposes columns into primitive operation chains
"""
import yaml
import json
from pathlib import Path
from typing import Dict, Any
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from config.settings import OPENAI_API_KEY, PLANNER_MODEL, LLM_TEMPERATURE, LLM_TIMEOUT, PROMPTS_DIR
from utils.logging_config import get_logger

logger = get_logger("PlannerAgent")


class PlannerAgent:
    def __init__(self):
        # Load planner prompt from YAML file
        prompt_path = PROMPTS_DIR / "planner.yaml"
        with open(prompt_path, 'r') as f:
            self.prompt_config = yaml.safe_load(f)
        
        # Load column reference data if available
        col_ref_path = PROMPTS_DIR / "column_reference.yaml"
        self.column_reference = {}
        if col_ref_path.exists():
            with open(col_ref_path, 'r') as f:
                col_data = yaml.safe_load(f)
                self.column_reference = col_data.get("columns", {})
        
        self.llm = ChatOpenAI(
            model_name=PLANNER_MODEL,
            openai_api_key=OPENAI_API_KEY,
            temperature=LLM_TEMPERATURE,
            timeout=LLM_TIMEOUT,
            model_kwargs={"response_format": {"type": "json_object"}}
        )
        
        # Plan cache: plans are column-specific, not URL-specific.
        # Reuse the same plan across multiple URLs to avoid redundant LLM calls.
        self._plan_cache: Dict[str, Dict[str, Any]] = {}
        
        logger.info("Planner Agent initialized")
    
    def _build_system_prompt(self) -> str:
        """Build system prompt from YAML configuration and column reference"""
        config = self.prompt_config
        
        prompt = f"**Role:** {config.get('role', 'SEO Planner')}\n\n"
        prompt += f"**Mission:** {config.get('mission', 'Plan primitive chains for SEO auditing')}\n\n"
        
        # Include list of available primitives
        primitives = config.get('primitives', [])
        if primitives:
            prompt += "**Your 10 Primitives:**\n"
            for prim in primitives:
                prompt += f"- {prim['name']}: {prim['description']}\n"
        
        # Enhanced VALIDATE rules for deterministic checks
        prompt += """
**CRITICAL — Enhanced VALIDATE Rules (use these for deterministic checks):**
- VALIDATE rule="robots_txt_full_check": Pass $current_url. Fetches /robots.txt, parses, validates. Returns {valid, details{disallow_rules, allow_rules, sitemap_references, is_blocked, content_preview}}.
- VALIDATE rule="ssl_check": Pass $current_url. Real SSL socket check + redirect validation. Returns {valid, details{days_until_expiry, tls_version, redirect_secure}}.
- VALIDATE rule="ga4_check": Pass $page_html (or FETCH dict). Scans for G-*, GTM-*, gtag.js, dataLayer. Returns {valid, details{tags_found}}.
- VALIDATE rule="gsc_check": Pass $page_html (or FETCH dict). Checks google-site-verification meta + infers from GA4. Returns {valid, details{verification_methods}}.
- VALIDATE rule="mixed_content_check": Pass {"url": "$current_url", "html": "$page_html"}. Scans for http:// resources on HTTPS page. Returns {valid, details{http_resources, active_count, passive_count, sample_urls}}.
- VALIDATE rule="interstitial_check": Pass $page_html (or FETCH dict). Detects popups/modals/overlays. valid=True means NO intrusive interstitials. Returns {valid, details{interstitial_detected}}.
- VALIDATE rule="broken_links_check": Pass {"url": "$current_url", "html": "$page_html"}. HEAD-requests up to 50 links. Returns {valid, details{total_links_on_page, broken_count, broken_links, summary}}.

**CRITICAL — Enhanced MEASURE Metrics:**
- MEASURE metric="keyword_density": Pass $page_html or text. Returns {status, total_words, top_single_words, top_bigrams, top_trigrams}.
- MEASURE metric="url_depth": Pass $current_url. Returns integer depth (0 = root).

**MANDATORY PRIMITIVE PREFERENCES (follow these EXACTLY):**
- "Robots.txt configured correctly" → Use VALIDATE rule="robots_txt_full_check" with data=$current_url
- "XML Sitemap updated & submitted" → Use VALIDATE rule="sitemap_full_check" with data=$current_url
- "SSL certificate active" → Use VALIDATE rule="ssl_check" with data=$current_url
- "Google Analytics/GA4 setup" → Use VALIDATE rule="ga4_check" with data=$page_html
- "Google Search Console setup" → Use VALIDATE rule="gsc_check" with data=$page_html
- "No mixed content warnings" → Use VALIDATE rule="mixed_content_check" with data={"url": "$current_url", "html": "$page_html"}
- "No intrusive interstitials" → Use VALIDATE rule="interstitial_check" with data=$page_html
- "Broken Links" → Use VALIDATE rule="broken_links_check" with data={"url": "$current_url", "html": "$page_html"}
- "Keyword Density" → Use MEASURE metric="keyword_density" with data=$page_html
- "Logical site hierarchy" → Use MEASURE metric="url_depth" with data=$current_url
- "FAQ In Blog" → Use VALIDATE rule="faq_blog_check" with data={"url": "$current_url", "html": "$page_html"}
- "Thin content audit" → SELECT body, EXTRACT text, MEASURE word_count, COMPARE >= 200. The body text must strip script/style tags before counting.
- "404 Errors" → This checks if the current page returns HTTP 404. Use COMPARE with value1=$status_code, value2=404, operator="==". The status_code is already in $intermediate_vars from the fetch step.
- "Breadcrumb navigation" → SELECT with selector="nav[aria-label*='breadcrumb'], .breadcrumb, [itemtype*='BreadcrumbList']" mode="exists" to check if breadcrumb HTML exists. Then also check for BreadcrumbList in JSON-LD schema via SELECT with selector="script[type='application/ld+json']" mode="many", then EXTRACT text, then use REASON to check if any contain BreadcrumbList.
- "Duplicate content check" → Use SEARCH with method="semantic" and corpus="all_texts" to find similar pages in the global corpus. The query should be the main content text.

**CRITICAL RULES FOR BROKEN LINKS AND 404:**
- For "Broken Links", the VALIDATE rule="broken_links_check" MUST receive data as a dict: {"url": "$current_url", "html": "$page_html"}. NEVER pass a boolean, string, or variable from COMPARE as data.
- For "404 Errors", do NOT use VALIDATE broken_links_check. Just use COMPARE to check $status_code against 404.

**IMPORTANT FOR XML SITEMAP:** 
- Do NOT use XPath selectors like //url/loc. Use VALIDATE rule="sitemap_full_check" instead.
- The sitemap_full_check fetches, parses, counts URLs, and checks if current URL is included — all in one call.
"""
        
        # Include critical parameter rules for primitives
        param_rules = config.get('CRITICAL_PARAMETER_RULES', {})
        if param_rules:
            prompt += "\n**Critical Parameter Rules:**\n"
            for prim_name, rules in param_rules.items():
                required = rules.get('required', [])
                optional = rules.get('optional', [])
                example = rules.get('example', {})
                prompt += f"- {prim_name}: required={required}, optional={optional}\n"
                if example:
                    prompt += f"  Example: {json.dumps(example)}\n"
        
        # Master metric registry as quick reference
        registry = config.get('master_metric_registry', {})
        if registry:
            prompt += "\n**Master Metric Registry (Quick Reference):**\n"
            for key, val in registry.items():
                prompt += f"- {key}: {val}\n"
        
        # Discovery protocol steps
        protocol = config.get('discovery_protocol', {})
        steps = protocol.get('steps', [])
        if steps:
            prompt += "\n**Discovery Protocol:**\n"
            for step in steps:
                prompt += f"- {step}\n"
        
        # Output format specification
        output_fmt = config.get('output_format', {})
        json_structure = output_fmt.get('json_structure', '')
        if json_structure:
            prompt += f"\n**Output Format:**\n{json_structure}"
        
        # Example mappings from configuration
        examples = config.get('EXAMPLES', {})
        if examples:
            prompt += "\n**Examples:**\n"
            for ex_name, ex_data in examples.items():
                prompt += f"\n{ex_name}:\n{json.dumps(ex_data, indent=2, default=str)}\n"
        
        return prompt
    
    async def generate_plan(self, column_name: str, intermediate_vars: Dict[str, Any]) -> Dict[str, Any]:
        """Generate primitive execution plan for a given column.
        Plans are cached by column name since they are column-specific, not URL-specific."""
        
        # Return cached plan if available (plans don't change between URLs)
        if column_name in self._plan_cache:
            logger.info(f"Plan cache HIT for column: {column_name}")
            return self._plan_cache[column_name]
        
        logger.info(f"Planning for column: {column_name}")
        
        system_prompt = self._build_system_prompt()
        
        # Add column-specific reference if available
        col_ref_section = ""
        col_ref = self.column_reference.get(column_name)
        if col_ref:
            col_ref_section = f"""
**Column Reference (from column_reference.yaml):**
- Description: {col_ref.get('description', 'N/A')}
- Required Metrics: {col_ref.get('required_metrics', [])}
- Suggested Primitive Chain: {json.dumps(col_ref.get('primitive_chain', []), default=str)}
"""
        
        user_prompt = f"""
**Column:** {column_name}
{col_ref_section}
**Available Intermediate Variables (from previous columns):**
{json.dumps(list(intermediate_vars.keys()), indent=2)}

**Task:** Generate a primitive operation chain to satisfy all metrics for this column.
- Re-use existing variables when possible (e.g., $page_html, $title_text)
- For columns listed in MANDATORY PRIMITIVE PREFERENCES, you MUST use the specified VALIDATE or MEASURE call.
- Return valid JSON with: column, operations[], final_result_template
"""
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        try:
            response = await self.llm.ainvoke(messages)
            plan = json.loads(response.content)
            logger.info(f"Plan generated for {column_name}: {len(plan.get('operations', []))} operations")
            # Cache the plan for reuse across URLs
            self._plan_cache[column_name] = plan
            return plan
        
        except Exception as e:
            logger.error(f"Planner error for {column_name}: {e}")
            return {
                "column": column_name,
                "operations": [],
                "error": str(e)
            }