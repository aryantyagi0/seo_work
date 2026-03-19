from bs4 import BeautifulSoup
import re
import logging
from langchain_core.tools import tool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def check_hidden_content_tool(html_content: str) -> dict:
    """
    Checks for content that might be hidden via common CSS properties (display:none, visibility:hidden).
    This is a basic heuristic check and a full analysis would require parsing CSS stylesheets
    and rendering the page, which is beyond simple HTML parsing.
    
    Args:
        html_content: The raw HTML content of the page.
        
    Returns:
        A dictionary with status, message, and details of potentially hidden elements.
    """
    if not html_content:
        return {"status": "error", "message": "No HTML content provided for hidden content analysis.", "details": []}

    try:
        soup = BeautifulSoup(html_content, 'lxml')
    except Exception as e:
        return {"status": "error", "message": f"Failed to parse HTML for hidden content analysis: {e}", "details": []}

    hidden_elements = []
    
    # Find elements with inline style display:none or visibility:hidden
    for tag in soup.find_all(lambda tag: tag.has_attr('style') and (
        'display:none' in tag['style'].replace(' ', '') or 
        'visibility:hidden' in tag['style'].replace(' ', ''))
    ):
        text_content = tag.get_text(strip=True)
        if text_content: # Only report if there's actual text content
            hidden_elements.append({"tag": tag.name, "text_sample": text_content[:100], "reason": "inline style"})
        
    # Find elements with common classes that might hide content
    common_hidden_classes = ['hidden', 'sr-only', 'visually-hidden', 'display-none', 'js-hide']
    for cls in common_hidden_classes:
        for tag in soup.find_all(class_=re.compile(r'\b' + re.escape(cls) + r'\b', re.IGNORECASE)):
            text_content = tag.get_text(strip=True)
            if text_content and not any(h['text_sample'] == text_content[:100] for h in hidden_elements): # Avoid duplicates
                hidden_elements.append({"tag": tag.name, "text_sample": text_content[:100], "reason": f"class '{cls}'"})
    
    if hidden_elements:
        return {"status": "warning", "message": f"Potentially hidden content detected: {len(hidden_elements)} elements. Manual review recommended.", "details": hidden_elements}
    return {"status": "success", "message": "No obvious hidden content detected via common HTML/inline CSS.", "details": []}

