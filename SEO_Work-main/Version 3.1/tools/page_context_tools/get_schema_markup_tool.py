from langchain_core.tools import tool
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def get_schema_markup_tool(parsed_data: dict) -> list[dict]:
    """
    Retrieves the schema markup from the already parsed HTML data.
    
    Args:
        parsed_data: A dictionary containing all extracted SEO elements from the page.
        
    Returns:
        A list of dictionaries, where each dictionary represents a parsed JSON-LD schema block.
        Returns an empty list if none are found.
    """
    if not parsed_data or "schema_markup" not in parsed_data:
        logging.warning("No parsed data or schema_markup found in parsed_data for extraction.")
        return []
    
    return parsed_data.get("schema_markup", [])

