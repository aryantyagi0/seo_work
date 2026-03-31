from langchain_core.tools import tool
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def get_h3_tags_tool(parsed_data: dict) -> list[str]:
    """
    Retrieves the H3 tags from the already parsed HTML data.
    
    Args:
        parsed_data: A dictionary containing all extracted SEO elements from the page.
        
    Returns:
        A list of strings, where each string is the text content of an H3 tag.
        Returns an empty list if no H3 tags are found or if an error occurs.
    """
    if not parsed_data or "h3_tags" not in parsed_data:
        logging.warning("No parsed data or h3_tags found in parsed_data for extraction.")
        return []
    
    return parsed_data.get("h3_tags")

