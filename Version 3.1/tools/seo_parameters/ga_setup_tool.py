from bs4 import BeautifulSoup
import logging
from langchain_core.tools import tool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def check_ga_setup_tool(html_content: str, criteria: dict = None) -> dict:
    """
    Checks for the presence of Google Analytics (gtag.js or analytics.js)
    or Google Tag Manager (GTM) scripts in the provided HTML content.
    
    Args:
        html_content: The raw HTML content of the page.
        
    Returns:
        A dictionary with status and message regarding GA/GTM script detection.
    """
    if criteria is None:
        criteria = {}
    if not html_content:
        return {"status": "error", "message": "No HTML content provided for GA setup analysis.", "details": {"reason": "missing_html"}}

    try:
        soup = BeautifulSoup(html_content, 'lxml')
    except Exception as e:
        return {"status": "error", "message": f"Failed to parse HTML for GA setup analysis: {e}"}

    ga_found = False
    matched = []
    src_markers = criteria.get("src_markers", [
        "googletagmanager.com/gtag/js",
        "google-analytics.com/analytics.js",
        "googletagmanager.com/gtm.js",
    ])
    inline_markers = criteria.get("inline_markers", ["ga('create'", "gtag('config'", "GTM-", "G-"])
    for script in soup.find_all('script'):
        if script.get('src') and any(marker in script.get('src') for marker in src_markers):
            ga_found = True
            matched.append(script.get('src'))
            break
        # Also check inline scripts for gtag/ga or GTM IDs
        if script.string:
            if any(marker in script.string for marker in inline_markers):
                ga_found = True
                matched.append("inline_script")
                break
            
    if ga_found:
        return {"status": "success", "message": "Google Analytics / GTM script detected.", "details": {"matched": matched}}
    return {"status": "warning", "message": "Google Analytics / GTM script not found.", "details": {"checked": True}}

