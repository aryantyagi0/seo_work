from langchain_core.tools import tool
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def get_hreflang_tags_tool(parsed_data: dict) -> list[dict]:
    """
    Retrieves the hreflang tags from the already parsed HTML data.
    
    Args:
        parsed_data: A dictionary containing all extracted SEO elements from the page.
        
    Returns:
        A list of dictionaries, where each dictionary represents an hreflang tag
        with 'hreflang' and 'href' keys. Returns an empty list if none are found.
    """
    if not parsed_data or "hreflang_tags" not in parsed_data:
        logging.warning("No parsed data or hreflang_tags found in parsed_data for extraction.")
        return []
    
    return parsed_data.get("hreflang_tags", [])

