from urllib.parse import urlparse, urlunparse
import re
import logging
from langchain_core.tools import tool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def analyze_hreflang_tags_tool(hreflang_tags: list[dict], page_url: str) -> dict:
    """
    Analyzes hreflang tags: checks for existence, correct format, and self-referencing.
    Also checks for x-default.
    
    Args:
        hreflang_tags: A list of hreflang tags already extracted from the page.
        page_url: The actual URL of the page being analyzed.
        
    Returns:
        A dictionary with analysis status, message, and details of found hreflang tags.
    """
    if not hreflang_tags:
        return {"status": "info", "message": "No hreflang tags found.", "details": []}
    
    results = []
    has_self_referencing = False
    has_x_default = False
    
    for link in hreflang_tags:
        lang = link.get('hreflang')
        href = link.get('href')
        
        entry = {"hreflang": lang, "href": href, "status": "valid"}
        
        if not lang or not href:
            entry["status"] = "error"
            entry["message"] = "Hreflang tag missing 'hreflang' or 'href' attribute."
        elif not re.match(r'^[a-z]{2}(-[a-z]{2})?$', lang, re.IGNORECASE) and lang != 'x-default':
            entry["status"] = "error"
            entry["message"] = f"Invalid hreflang code: {lang}. Must be 'language-region' or 'x-default'."
        else:
            # Check if self-referencing
            # Normalize URLs for comparison (remove fragments, sort query params, ensure consistent scheme/host)
            parsed_href = urlparse(href)
            parsed_page_url = urlparse(page_url)
            normalized_href = urlunparse(parsed_href._replace(query=re.sub(r'&[^=]+', '', parsed_href.query), fragment=''))
            normalized_page_url = urlunparse(parsed_page_url._replace(query=re.sub(r'&[^=]+', '', parsed_page_url.query), fragment=''))

            if normalized_href == normalized_page_url:
                has_self_referencing = True
            if lang == 'x-default':
                has_x_default = True
        results.append(entry)
        
    overall_status = "success"
    overall_message = "Hreflang tags found."
    if not has_self_referencing:
        overall_status = "warning"
        overall_message += " No self-referencing hreflang tag found."
    if not has_x_default:
        overall_status = "warning"
        overall_message += " No 'x-default' hreflang tag found."
        
    return {"status": overall_status, "message": overall_message, "details": results}
