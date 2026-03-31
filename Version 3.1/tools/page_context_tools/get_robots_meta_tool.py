from langchain_core.tools import tool
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def get_robots_meta_tool(parsed_data: dict) -> str:
    """
    Retrieves the robots meta tag content from the already parsed HTML data.
    
    Args:
        parsed_data: A dictionary containing all extracted SEO elements from the page.
        
    Returns:
        The content of the robots meta tag (e.g., "noindex, nofollow"), or None if not found.
    """
    if not parsed_data or "robots_meta" not in parsed_data:
        logging.warning("No parsed data or robots_meta found in parsed_data for extraction.")
        return None
    
    return parsed_data.get("robots_meta")

