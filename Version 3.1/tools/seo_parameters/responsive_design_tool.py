from bs4 import BeautifulSoup
import logging
from langchain_core.tools import tool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def check_responsive_design_tool(html_content: str) -> dict:
    """
    Performs a basic check for responsive design indicators in the HTML content,
    specifically looking for the viewport meta tag. A full check for true
    responsiveness would require rendering the page in a headless browser.
    
    Args:
        html_content: The raw HTML content of the page.
        
    Returns:
        A dictionary with status and message regarding responsive design indicators.
    """
    if not html_content:
        return {"status": "error", "message": "No HTML content provided for responsive design analysis."}

    try:
        soup = BeautifulSoup(html_content, 'lxml')
    except Exception as e:
        return {"status": "error", "message": f"Failed to parse HTML for responsive design analysis: {e}"}

    viewport_meta = soup.find('meta', attrs={'name': 'viewport'})
    
    if viewport_meta and "width=device-width" in viewport_meta.get('content', '') and "initial-scale=1" in viewport_meta.get('content', ''):
        return {"status": "success", "message": "Viewport meta tag for responsive design detected."}
    return {"status": "warning", "message": "Viewport meta tag for responsive design not found or incomplete. Page might not be fully responsive."}
