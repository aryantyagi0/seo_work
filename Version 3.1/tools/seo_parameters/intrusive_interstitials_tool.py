from bs4 import BeautifulSoup
import re
import logging
from langchain_core.tools import tool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def check_intrusive_interstitials_tool(html_content: str) -> dict:
    """
    Performs a basic heuristic check for common patterns of intrusive interstitials
    in the provided HTML content. This is a heuristic check and may not catch all cases
    without rendering the page and analyzing layout.
    
    Args:
        html_content: The raw HTML content of the page.
        
    Returns:
        A dictionary with status and message regarding potential intrusive interstitials.
    """
    if not html_content:
        return {"status": "error", "message": "No HTML content provided for intrusive interstitials analysis."}

    try:
        soup = BeautifulSoup(html_content, 'lxml')
    except Exception as e:
        return {"status": "error", "message": f"Failed to parse HTML for intrusive interstitials analysis: {e}"}

    # Look for common patterns: elements with specific classes/ids
    interstitial_keywords = ['popup', 'modal', 'overlay', 'interstitial', 'gdpr-banner', 'cookie-consent-banner']
    
    for keyword in interstitial_keywords:
        # Check by class name
        if soup.find(class_=re.compile(r'\b' + re.escape(keyword) + r'\b', re.IGNORECASE)):
            return {"status": "warning", "message": f"Potentially intrusive interstitial pattern detected (class containing '{keyword}'). Manual review recommended."}
        # Check by ID
        if soup.find(id=re.compile(r'\b' + re.escape(keyword) + r'\b', re.IGNORECASE)):
            return {"status": "warning", "message": f"Potentially intrusive interstitial pattern detected (ID containing '{keyword}'). Manual review recommended."}
            
    # Advanced checks would involve CSS analysis for fixed/full-screen positioning, high z-index, etc.
    # This is beyond basic HTML parsing without a full rendering engine.
    
    return {"status": "info", "message": "No obvious intrusive interstitial patterns detected in HTML. Manual review is best to confirm."}
