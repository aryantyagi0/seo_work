from langchain_core.tools import tool
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def get_meta_description_tool(parsed_data: dict) -> str:
    """
    Retrieves the meta description from the already parsed HTML data.
    
    Args:
        parsed_data: A dictionary containing all extracted SEO elements from the page.
        
    Returns:
        The text content of the meta description tag, or None if not found.
    """
    if not parsed_data or "meta_description" not in parsed_data:
        logging.warning("No parsed data or meta_description found in parsed_data for extraction.")
        return None
    
    return parsed_data.get("meta_description")

