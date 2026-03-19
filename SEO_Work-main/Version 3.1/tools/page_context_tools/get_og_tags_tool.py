from langchain_core.tools import tool
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def get_og_tags_tool(parsed_data: dict) -> dict:
    """
    Retrieves the Open Graph (OG) tags from the already parsed HTML data.
    
    Args:
        parsed_data: A dictionary containing all extracted SEO elements from the page.
        
    Returns:
        A dictionary where keys are OG property names (e.g., "og:title") and values are their content.
        Returns an empty dictionary if no OG tags are found or if an error occurs.
    """
    if not parsed_data or "og_tags" not in parsed_data:
        logging.warning("No parsed data or og_tags found in parsed_data for extraction.")
        return {}
    
    return parsed_data.get("og_tags", {})

