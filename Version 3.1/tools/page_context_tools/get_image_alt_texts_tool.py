from langchain_core.tools import tool
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def get_image_alt_texts_tool(parsed_data: dict) -> list[dict]:
    """
    Retrieves the image alt texts from the already parsed HTML data.
    
    Args:
        parsed_data: A dictionary containing all extracted SEO elements from the page.
        
    Returns:
        A list of dictionaries, where each dictionary represents an image with 'src' and 'alt' keys.
        Returns an empty list if no images are found or if an error occurs.
    """
    if not parsed_data or "image_alt_texts" not in parsed_data:
        logging.warning("No parsed data or image_alt_texts found in parsed_data for extraction.")
        return []
    
    return parsed_data.get("image_alt_texts", [])

