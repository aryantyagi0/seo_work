from bs4 import BeautifulSoup
import logging
from langchain_core.tools import tool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def check_gsc_setup_tool(html_content: str, criteria: dict = None) -> dict:
    """
    Checks for the presence of the Google Search Console verification meta tag
    in the provided HTML content.
    
    Args:
        html_content: The raw HTML content of the page.
        
    Returns:
        A dictionary with status and message regarding GSC meta tag detection.
    """
    if criteria is None:
        criteria = {}
    if not html_content:
        return {"status": "error", "message": "No HTML content provided for GSC setup analysis.", "details": {"reason": "missing_html"}}

    try:
        soup = BeautifulSoup(html_content, 'lxml')
    except Exception as e:
        return {"status": "error", "message": f"Failed to parse HTML for GSC setup analysis: {e}"}

    gsc_found = False
    matched = []
    meta_names = criteria.get("meta_names", ["google-site-verification"])
    for name in meta_names:
        for meta in soup.find_all('meta', attrs={'name': name}):
            if meta.get('content'):
                gsc_found = True
                matched.append(meta.get('content'))
                break
        if gsc_found:
            break
            
    if gsc_found:
        return {"status": "success", "message": "Google Search Console verification meta tag detected.", "details": {"matched": matched}}
    return {"status": "info", "message": "Google Search Console verification meta tag not found (site may be verified by other methods like DNS or HTML file upload).", "details": {"checked": meta_names}}

