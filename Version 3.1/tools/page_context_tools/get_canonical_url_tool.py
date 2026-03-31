from langchain_core.tools import tool
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def get_canonical_url_tool(parsed_data: dict) -> str:
    """
    Retrieves the canonical URL from the already parsed HTML data.
    
    Args:
        parsed_data: A dictionary containing all extracted SEO elements from the page.
        
    Returns:
        The URL specified in the canonical link tag, or None if not found.
    """
    if not parsed_data or "canonical_url" not in parsed_data:
        logging.warning("No parsed data or canonical_url found in parsed_data for extraction.")
        return None
    
    return parsed_data.get("canonical_url")

