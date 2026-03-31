"""
utils/url_404_handler.py

404 URL resolution engine with LLM-in-the-loop for intelligent fallback correction.

Strategy:
1. Python pre-filters sitemap URLs to top 20-30 candidates (fast string similarity)
2. Gathers known valid domains from audit sheet
3. Passes broken URL + error type + candidates + domains to LLM
4. LLM applies strict rules:
   - Rule 1: DNS/Domain typo → correct domain, check if homepage-only
   - Rule 2: Path typo → match against candidates
   - Rule 3: Path truncation → find working parent + child suggestions
   - Rule 4: No match → intelligently hallucinate
"""

from __future__ import annotations

import re
import logging
import asyncio
import json
from difflib import SequenceMatcher
from urllib.parse import urlparse, urlsplit, urlunsplit
import xml.etree.ElementTree as ET
import aiohttp

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from config.settings import OPENAI_API_KEY, WRITER_MODEL, LLM_TIMEOUT

logger = logging.getLogger("Url404Handler")


# HELPERS


def _norm(url: str) -> str:
    """Normalize URL to comparable form."""
    try:
        p = urlsplit(url.strip())
        if not p.scheme or not p.netloc:
            return ""
        path = p.path or "/"
        if path != "/":
            path = path.rstrip("/")
        return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, "", ""))
    except Exception:
        return ""


def _home(url: str) -> str:
    """Extract homepage from URL."""
    p = urlparse(url)
    return f"{p.scheme.lower()}://{p.netloc.lower()}"


def _domain_key(domain: str) -> str:
    """Extract domain key (without www)."""
    d = (domain or "").lower().strip()
    return d[4:] if d.startswith("www.") else d


def _replace_domain(url: str, new_domain: str) -> str:
    """Replace domain in URL."""
    p = urlsplit(url)
    if not p.scheme:
        return ""
    return urlunsplit((p.scheme.lower(), new_domain.lower(), p.path or "/", "", ""))


def _path_sim(a: str, b: str) -> float:
    """SequenceMatcher similarity ratio."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _is_404_like_issue(raw_404: dict) -> bool:
    """Check if raw data indicates a 404 or connection error."""
    if not isinstance(raw_404, dict):
        return False
    if raw_404.get("is_404"):
        return True
    status = raw_404.get("status_code")
    if isinstance(status, int) and status >= 400:
        return True
    text = " ".join([
        str(raw_404.get("reason", "")),
        str(raw_404.get("error", ""))
    ]).lower()
    return any(m in text for m in [
        "cannot connect", "connection error", "getaddrinfo", 
        "name or service not known", "ssl"
    ])


def _find_404_column(raw_metrics: dict) -> str | None:
    """Find the 404 error column in raw metrics."""
    for col in raw_metrics.keys():
        if "404" in col.lower():
            return col
    return None


def _get_error_type(raw_404: dict) -> str:
    """Determine error type."""
    status = raw_404.get("status_code")
    if isinstance(status, int) and status >= 400:
        return f"HTTP {status}"
    text = " ".join([str(raw_404.get("reason", "")), str(raw_404.get("error", ""))]).lower()
    if any(m in text for m in ["cannot connect", "connection error", "getaddrinfo", "name or service not known"]):
        return "DNS/Host Error"
    return "Unknown Error"


def _build_deterministic_404_summary(url: str, raw_404: dict) -> str:
    """Build a deterministic 404 summary."""
    status = raw_404.get("status_code", "unknown")
    suggestions = raw_404.get("suggested_similar_urls", [])
    src = raw_404.get("url_source", "none")
    reason = str(raw_404.get("reason") or raw_404.get("error") or "page not found").strip()
    
    base = f"URL {url} returned HTTP status code {status}, indicating {reason}."
    
    if not suggestions:
        return f"{base} Action: implement a 301 redirect or restore missing content, then update internal links pointing to this URL. Recommended update: no close typo-correction found."
    
    recco = f"Recommended update (from {src}): {', '.join(suggestions)}."
    return f"{base} Action: implement a 301 redirect to the correct live page or restore the missing content, then update internal links pointing to this URL. {recco}"



# XML PARSING (Recursive for Sitemap Indexes)


async def _fetch_url(session: aiohttp.ClientSession, url: str, timeout: int = 10) -> str:
    """Fetch URL content."""
    try:
        async with session.get(
            url, 
            timeout=aiohttp.ClientTimeout(total=timeout),
            ssl=False,
            allow_redirects=True
        ) as r:
            if r.status == 200:
                return await r.text()
    except Exception as e:
        logger.debug(f"Failed to fetch {url}: {e}")
    return ""


async def _parse_xml_recursive(
    session: aiohttp.ClientSession,
    xml_url: str,
    depth: int = 0,
    max_depth: int = 3
) -> list[str]:
    """Recursively parse XML sitemap(s), including index files."""
    if depth > max_depth:
        return []
    
    xml_text = await _fetch_url(session, xml_url)
    if not xml_text:
        return []
    
    urls = []
    try:
        root = ET.fromstring(xml_text)
        
        # Check if it's a sitemap index or regular sitemap
        for elem in root.iter():
            tag = elem.tag.split("}")[-1].lower() if "}" in elem.tag else elem.tag.lower()
            
            if tag == "loc" and elem.text:
                loc = elem.text.strip()
                # If it points to another sitemap, recurse
                if ".xml" in loc.lower():
                    sub_urls = await _parse_xml_recursive(session, loc, depth + 1, max_depth)
                    urls.extend(sub_urls)
                else:
                    # It's a regular webpage URL
                    urls.append(loc)
    except Exception as e:
        logger.debug(f"Error parsing XML {xml_url}: {e}")
    
    return urls


async def _get_sitemap_urls(
    session: aiohttp.ClientSession,
    home: str,
    max_urls: int = 1000
) -> list[str]:
    """Fetch all URLs from sitemap (handling indexes)."""
    sitemap_paths = [
        "/sitemap.xml",
        "/sitemap_index.xml",
        "/wp-sitemap.xml",
        "/page-sitemap.xml",
    ]
    
    all_urls = []
    for path in sitemap_paths:
        xml_url = home.rstrip("/") + path
        urls = await _parse_xml_recursive(session, xml_url)
        all_urls.extend(urls)
        if len(all_urls) >= max_urls:
            break
    
    # Remove duplicates and normalize
    normalized = list(set(_norm(u) for u in all_urls if _norm(u)))
    return normalized[:max_urls]



# CANDIDATE FILTERING & VALIDATION


def _filter_top_candidates(
    broken_url: str,
    candidate_urls: list[str],
    max_results: int = 30
) -> list[str]:
    """Filter candidates to top N by string similarity."""
    if not candidate_urls:
        return []
    
    broken_norm = _norm(broken_url)
    if not broken_norm:
        return candidate_urls[:max_results]
    
    broken_path = urlparse(broken_norm).path or "/"
    
    scored = []
    for cand in candidate_urls:
        cand_path = urlparse(cand).path or "/"
        sim = _path_sim(broken_path, cand_path)
        if sim > 0.25:  # Keep threshold low to get diverse candidates
            scored.append((sim, cand))
    
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:max_results]]


async def _check_url_live(session: aiohttp.ClientSession, url: str, timeout: int = 5) -> bool:
    """Check if a URL is actually live (returns 200)."""
    try:
        async with session.head(
            url,
            timeout=aiohttp.ClientTimeout(total=timeout),
            ssl=False,
            allow_redirects=True
        ) as r:
            return r.status == 200
    except Exception:
        # Also try GET if HEAD fails
        try:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=timeout),
                ssl=False,
                allow_redirects=True
            ) as r:
                return r.status == 200
        except Exception:
            return False


async def _validate_urls(session: aiohttp.ClientSession, urls: list[str]) -> list[str]:
    """Filter URLs to only those that are actually live (HTTP 200)."""
    if not urls:
        return []
    
    live_urls = []
    for url in urls:
        if await _check_url_live(session, url):
            live_urls.append(url)
    
    return live_urls



# LLM ENGINE


async def _llm_resolve_404(
    broken_url: str,
    error_type: str,
    known_domains: list[str],
    candidate_urls: list[str],
    llm_model: ChatOpenAI
) -> tuple[list[str], str]:
    """
    Use LLM to resolve 404 URLs with strict rules.
    Returns (suggested_urls, method_used)
    """
    
    # Build candidate string
    candidates_str = "\n".join([f"  - {u}" for u in candidate_urls[:30]])
    if not candidates_str:
        candidates_str = "  (no candidates available)"
    
    known_domains_str = ", ".join(known_domains)
    
    system_prompt = """You are an expert SEO URL corrector. You will receive a broken URL and must intelligently correct it following these strict rules:

RULE 1 - DNS/Domain Typo (error like: cannot connect, getaddrinfo failed):
  - Extract the broken domain from the URL
  - Check against KNOWN_DOMAINS list
  - Find the CLOSEST matching domain (similarity >= 0.65)
  - If match found AND path is just "/" (homepage): Return ONLY the corrected homepage URL
  - If match found AND path has children: Correct domain AND find closest matching child path from candidates
  
RULE 2 - HTTP 404 with Path Typo:
  - Look at CANDIDATE_URLS (real URLs from the website's sitemap)
  - Find the closest matching URL to the broken path (typo correction)
  - Return the best matching URL from candidates
  
RULE 3 - HTTP 404 with Structurally Wrong Path (e.g., /services/category where /services/ exists):
  - Intelligently truncate the path to the deepest working level
  - Suggest 2-3 valid sub-pages under that working parent path
  - Return those sub-pages from candidates
  
RULE 4 - Fallback (No close matches found):
  - Intelligently hallucinate likely URLs based on the broken URL structure
  - Follow standard website architecture patterns
  - Return 2-3 plausible alternatives

OUTPUT FORMAT:
Return ONLY a JSON array of strings, e.g. ["url1", "url2", "url3"]
Do NOT include any markdown, code blocks, explanations, or extra text. ONLY the JSON array."""

    human_prompt = f"""Broken URL: {broken_url}
Error Type: {error_type}
Known Valid Domains: {known_domains_str}
Candidate URLs (real URLs from sitemap):
{candidates_str}

Correct this broken URL following the rules strictly. Return ONLY valid JSON array."""

    try:
        response = await llm_model.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_prompt)
        ])
        
        response_text = response.content.strip()
        
        # Try to extract JSON from response
        try:
            # Remove markdown code blocks if present
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0]
            
            result = json.loads(response_text.strip())
            
            if isinstance(result, list):
                urls = [_norm(u) for u in result if _norm(u)]
                if urls:
                    return urls, "llm_urls"
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM JSON response: {e}")
            logger.debug(f"Raw response: {response_text}")
    
    except Exception as e:
        logger.error(f"LLM error for {broken_url}: {e}")
    
    return [], "llm_error"



# MAIN ENGINE


async def process_404_fallbacks(all_results: list, audited_urls: list):
    """
    Main entry point: Process all 404 errors and enrich with LLM-corrected suggestions.
    """
    if not all_results or not audited_urls:
        return
    
    # Initialize LLM
    try:
        llm = ChatOpenAI(
            model_name=WRITER_MODEL,
            temperature=0,
            api_key=OPENAI_API_KEY,
            request_timeout=LLM_TIMEOUT
        )
    except Exception as e:
        logger.error(f"Failed to initialize LLM: {e}")
        return
    
    # Build known domains pool
    known_domains = []
    for url in audited_urls:
        home = _home(url)
        netloc = urlparse(home).netloc
        known_domains.append(netloc)
        # Also add without www
        if netloc.startswith("www."):
            known_domains.append(netloc[4:])
    known_domains = list(set(known_domains))
    
    # Build URL candidate pools per domain
    domain_candidates = {}
    
    async with aiohttp.ClientSession() as session:
        # Pre-fetch sitemaps for all known domains
        for home in set(_home(u) for u in audited_urls):
            domain_candidates[home] = await _get_sitemap_urls(session, home, max_urls=1000)
        
        # Process each result with 404 errors
        tasks = []
        for result in all_results:
            raw_metrics = result.get("raw_metrics", {})
            col_404 = _find_404_column(raw_metrics)
            if not col_404:
                continue
            
            raw_404 = raw_metrics[col_404].get("raw_data", {})
            if not _is_404_like_issue(raw_404):
                continue
            
            broken_url = result.get("url", "")
            if not broken_url:
                continue
            
            error_text = " ".join([
                str(raw_404.get("error", "")),
                str(raw_404.get("reason", ""))
            ]).lower()
            
            # Determine error type
            is_dns_error = any(m in error_text for m in [
                "cannot connect", "getaddrinfo", "name or service not known"
            ])
            error_type = "DNS/Host Error" if is_dns_error else f"HTTP {raw_404.get('status_code', 404)}"
            
            # Get candidates
            broken_home = _home(broken_url)
            base_candidates = domain_candidates.get(broken_home, [])
            
            # Also try corrected domain candidates (if DNS error)
            if is_dns_error:
                broken_dk = _domain_key(urlparse(broken_url).netloc)
                for kd in known_domains:
                    kd_key = _domain_key(kd)
                    if _path_sim(broken_dk, kd_key) > 0.65:
                        corrected_home = _home(kd if kd.startswith("http") else f"https://{kd}")
                        if corrected_home not in domain_candidates:
                            domain_candidates[corrected_home] = await _get_sitemap_urls(
                                session, corrected_home, max_urls=1000
                            )
                        base_candidates.extend(domain_candidates.get(corrected_home, []))
                        break
            
            # Filter to top candidates
            candidates = _filter_top_candidates(broken_url, list(set(base_candidates)), max_results=30)
            
            # Create async task for LLM
            task = _llm_resolve_404(
                broken_url=broken_url,
                error_type=error_type,
                known_domains=known_domains,
                candidate_urls=candidates,
                llm_model=llm
            )
            tasks.append((result, raw_404, len(candidates), task))
        
        # Execute all LLM calls concurrently
        if tasks:
            resolutions = await asyncio.gather(*[t[3] for t in tasks], return_exceptions=True)
            
            for idx, (result, raw_404, candidates_count, _) in enumerate(tasks):
                try:
                    res = resolutions[idx]
                    if isinstance(res, Exception):
                        logger.error(f"Error in 404 resolve: {res}")
                        suggestions, method = [], "error"
                    else:
                        suggestions, method = res
                    
                    # Enrich raw_404
                    raw_404["suggested_similar_urls"] = suggestions
                    raw_404["url_source"] = method
                    raw_404["sitemap_urls_indexed"] = candidates_count
                    
                    # Build summary
                    if suggestions:
                        raw_404["recommended_update"] = (
                            f"Compared this 404 URL against {candidates_count} URLs from {method} "
                            f"and found likely corrected valid URLs: {', '.join(suggestions)}"
                        )
                    else:
                        raw_404["recommended_update"] = (
                            "No close typo-correction was found. "
                            "Action: restore the missing content or implement a 301 redirect to a thematically related page."
                        )
                except Exception as e:
                    logger.error(f"Error enriching 404 result: {e}")
