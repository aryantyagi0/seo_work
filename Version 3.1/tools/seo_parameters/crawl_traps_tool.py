
import logging
import re
from urllib.parse import urlparse, parse_qs
from langchain_core.tools import tool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def find_crawl_traps_tool(url: str = None, all_links: list[str] = None, criteria: dict = None) -> dict:
    '''
    Detects potential crawl traps using heuristics aligned with Version 2 logic.
    Flags common trap patterns such as calendars, faceted navigation, tracking params,
    and deep, low-value URL paths.

    Args:
        url: The URL to check.
        all_links: Optional list of internal links found on the page.
        criteria: Optional overrides:
            - calendar_patterns: list[str] regex patterns
            - year_pattern: regex string
            - facet_params: list[str]
            - tracking_params: list[str]
            - search_markers: list[str]
            - max_query_params: int
            - max_path_depth: int

    Returns:
        A dictionary with status, message, and details explaining trap signals.
    
    '''
        
    if criteria is None:
        criteria = {}

    if not url:
        return {
            "status": "info",
            "message": "No URL provided for crawl trap analysis.",
            "details": {"reason": "missing_url"}
        }

    calendar_patterns = criteria.get(
        "calendar_patterns",
        [r"/\d{4}/\d{1,2}", r"/\d{4}-\d{2}", r"/calendar", r"/archive", r"page=\d{3,}"]
    )
    year_pattern = re.compile(criteria.get("year_pattern", r"\d{4}-\d{2}|20[2-9]\d"))
    facet_params = criteria.get(
        "facet_params",
        ["sort", "filter", "price", "color", "size", "brand", "order", "view", "layout"]
    )
    tracking_params = criteria.get(
        "tracking_params",
        ["utm_", "gclid", "fbclid", "session", "ref", "campaign", "affiliate"]
    )
    search_markers = criteria.get(
        "search_markers",
        ["/search", "s?k=", "q="]
    )
    max_query_params = int(criteria.get("max_query_params", 3))
    max_path_depth = int(criteria.get("max_path_depth", 8))

    url_lower = url.lower()
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    path_segments = [s for s in parsed.path.split("/") if s]

    flags = []
    matched = {
        "calendar_patterns": [],
        "facet_params": [],
        "tracking_params": [],
        "search_markers": [],
    }

    for pattern in calendar_patterns:
        if re.search(pattern, url_lower):
            matched["calendar_patterns"].append(pattern)
    if matched["calendar_patterns"] or year_pattern.search(url_lower):
        flags.append("calendar_or_archive")

    for p in facet_params:
        if p in parsed.query.lower():
            matched["facet_params"].append(p)
    if matched["facet_params"]:
        flags.append("faceted_navigation")

    for p in tracking_params:
        if p in url_lower:
            matched["tracking_params"].append(p)
    if matched["tracking_params"]:
        flags.append("tracking_params")

    for marker in search_markers:
        if marker in url_lower:
            matched["search_markers"].append(marker)
    if matched["search_markers"]:
        flags.append("search_pages")

    if len(query_params) >= max_query_params:
        flags.append("too_many_query_params")

    if len(path_segments) > max_path_depth:
        flags.append("deep_path")

    is_trap = bool(flags)
    status = "warning" if is_trap else "success"
    message = "Potential crawl trap detected." if is_trap else "No obvious crawl trap signals detected."

    details = {
        "url": url,
        "flags": flags,
        "matched": matched,
        "query_param_count": len(query_params),
        "path_depth": len(path_segments),
        "sample_links": (all_links or [])[:10],
    }

    return {
        "status": status,
        "message": message,
        "details": details,
        "remediation": "Reduce infinite/faceted URL variants, add canonical tags, and block low-value parameters in robots.txt."
        if is_trap else ""
    }

