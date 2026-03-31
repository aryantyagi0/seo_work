from urllib.parse import urlparse, urljoin, urlunparse
import requests
import logging
from langchain_core.tools import tool
from bs4 import BeautifulSoup # Direct import

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def analyze_internal_linking_tool(html_content: str, base_url: str) -> dict:
    """
    Analyzes internal linking structure from a single page.
    Counts internal links and identifies anchor text.
    
    Args:
        html_content: The raw HTML content of the page.
        base_url: The base URL of the page being analyzed.
        
    Returns:
        A dictionary with internal/external link counts, details, status, and message.
    """
    if not html_content:
        return {"status": "error", "message": "No HTML content provided for internal linking analysis."}
        
    try:
        soup = BeautifulSoup(html_content, 'lxml')
    except Exception as e:
        return {"status": "error", "message": f"Failed to parse HTML for internal linking analysis: {e}"}

    internal_links = []
    external_links = []
    
    parsed_base_url = urlparse(base_url)
    
    for link_tag in soup.find_all('a', href=True):
        href = link_tag['href']
        anchor_text = link_tag.get_text(strip=True)
        
        # Ignore fragments, mailto, tel links
        if href.startswith('#') or href.startswith('mailto:') or href.startswith('tel:'):
            continue
        
        full_url = urljoin(base_url, href)
        parsed_full_url = urlparse(full_url)
        
        if parsed_full_url.netloc == parsed_base_url.netloc: # Check if same domain
            internal_links.append({"url": full_url, "anchor_text": anchor_text})
        else:
            external_links.append({"url": full_url, "anchor_text": anchor_text})
            
    return {
        "internal_link_count": len(internal_links),
        "external_link_count": len(external_links),
        "internal_links_details": internal_links,
        "external_links_details": external_links,
        "status": "success" if internal_links else "warning",
        "message": f"Found {len(internal_links)} internal and {len(external_links)} external links."
    }
