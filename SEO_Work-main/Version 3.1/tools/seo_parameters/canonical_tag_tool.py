from urllib.parse import urlparse, urlunparse
import re
import logging
from langchain_core.tools import tool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def analyze_canonical_tag_tool(canonical_url: str, page_url: str, criteria: dict = None) -> dict:
    """
    Analyzes the canonical tag for the given page URL.
    
    Args:
        canonical_url: The canonical URL extracted from the page's HTML.
        page_url: The actual URL of the page being analyzed.
        
    Returns:
        A dictionary with analysis status, message, and the canonical URL found.
    """
    if criteria is None:
        criteria = {}
    if not canonical_url:
        return {"status": "warning", "message": "Canonical tag missing or empty.", "canonical_url": None, "details": {"reason": "missing_canonical"}}
    
    parsed_href = urlparse(canonical_url)
    parsed_page_url = urlparse(page_url)

    # Normalize URLs for comparison (remove fragments, sort query params, ensure consistent scheme/host)
    normalized_href = urlunparse(parsed_href._replace(query=re.sub(r'&[^=]+', '', parsed_href.query), fragment=''))
    normalized_page_url = urlunparse(parsed_page_url._replace(query=re.sub(r'&[^=]+', '', parsed_page_url.query), fragment=''))

    if normalized_href == normalized_page_url:
        return {"status": "success", "message": "Canonical tag is self-referencing.", "canonical_url": canonical_url, "details": {"normalized_canonical": normalized_href}}
    elif parsed_href.netloc == parsed_page_url.netloc: # Same domain, but different path/query
        return {"status": "warning", "message": "Canonical tag points to a different URL on the same domain.", "canonical_url": canonical_url, "details": {"normalized_canonical": normalized_href}}
    else: # Different domain
        return {"status": "warning", "message": "Canonical tag points to an external domain.", "canonical_url": canonical_url, "details": {"normalized_canonical": normalized_href}}
