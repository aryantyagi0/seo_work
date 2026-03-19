from langchain_core.tools import tool
import logging
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def get_title_tool(parsed_data: dict = None, html_content: str = None) -> str:
    """
    Retrieves the title from parsed data or raw HTML.
    
    Args:
        parsed_data: A dictionary containing extracted SEO elements from the page.
        html_content: Raw HTML content (fallback if parsed_data is not provided).
        
    Returns:
        The text content of the <title> tag, or None if not found.
    """
    if parsed_data and "title" in parsed_data:
        return parsed_data.get("title")

    if html_content:
        try:
            soup = BeautifulSoup(html_content, "lxml")
            if soup.title and soup.title.string:
                return soup.title.string.strip()
        except Exception as e:
            logging.warning(f"Failed to parse HTML for title extraction: {e}")
            return None

    logging.warning("No parsed data or HTML content provided for title extraction.")
    return None

