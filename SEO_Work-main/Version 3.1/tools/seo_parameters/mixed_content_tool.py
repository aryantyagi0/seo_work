from bs4 import BeautifulSoup
import logging
from langchain_core.tools import tool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def check_mixed_content_tool(html_content: str, page_url: str) -> dict:
    """
    Checks for mixed content (HTTP resources on an HTTPS page) within the provided HTML.
    
    Args:
        html_content: The raw HTML content of the page.
        page_url: The URL of the page being analyzed.
        
    Returns:
        A dictionary with status, message, and details of detected mixed content.
    """
    if not html_content:
        return {"status": "error", "message": "No HTML content provided for mixed content analysis.", "details": []}

    try:
        soup = BeautifulSoup(html_content, 'lxml')
    except Exception as e:
        return {"status": "error", "message": f"Failed to parse HTML for mixed content analysis: {e}", "details": []}

    if not page_url.startswith("https://"):
        return {"status": "info", "message": "Page is not HTTPS, mixed content check is not applicable.", "details": []}
    
    mixed_content_found = []
    
    # Find all elements that typically load external resources
    for tag in soup.find_all(['img', 'script', 'link', 'iframe', 'video', 'audio', 'source']):
        src_attr = tag.get('src')
        href_attr = tag.get('href')
        
        resource_url = src_attr if src_attr else href_attr
        
        if resource_url and resource_url.startswith('http://'):
            mixed_content_found.append({"tag": tag.name, "url": resource_url})
            
    if mixed_content_found:
        return {"status": "error", "message": f"Mixed content detected: {len(mixed_content_found)} HTTP resources found on HTTPS page.", "details": mixed_content_found}
    return {"status": "success", "message": "No mixed content detected.", "details": []}
