from bs4 import BeautifulSoup
import logging
from langchain_core.tools import tool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def _get_soup_from_html(html_content: str) -> BeautifulSoup:
    """
    Parses the HTML content and returns a BeautifulSoup object.
    This is an internal helper, not an exposed agent tool.

    Args:
        html_content: The HTML content as a string.

    Returns:
        A BeautifulSoup object, or None if parsing fails.
    """
    if not html_content:
        return None
    try:
        soup = BeautifulSoup(html_content, 'lxml')
        return soup
    except Exception as e:
        logging.error(f"Error parsing HTML: {e}")
        return None

@tool
async def extract_clean_text_from_html_tool(html_content: str) -> str:
    """
    Extracts all visible text from the raw HTML content.
    
    Args:
        html_content: The raw HTML content as a string.
        
    Returns:
        A string containing all visible text, or None if parsing fails.
    """
    soup = _get_soup_from_html(html_content)
    if not soup:
        return None
    # Remove script and style elements
    for script_or_style in soup(['script', 'style']):
        script_or_style.extract()
    text = soup.get_text(separator=' ', strip=True)
    return text

