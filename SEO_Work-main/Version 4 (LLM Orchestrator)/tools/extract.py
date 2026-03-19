"""
EXTRACT Primitive: Pull specific data from elements
"""
from typing import Any, List, Union, Optional
from bs4 import Tag
from utils.logging_config import get_logger

logger = get_logger("EXTRACT")


async def extract(element: Any, attribute: str) -> Any:
    """
    Extract data from element(s)
    
    Args:
        element: BeautifulSoup Tag, list of Tags, or dict
        attribute: "text", "href", "src", "alt", "content", or any HTML attribute
    
    Returns:
        - Single value if element is single Tag
        - List of values if element is list
        - None if extraction fails
    """
    try:
        # Handle None input
        if element is None:
            logger.warning("EXTRACT: Received None element")
            return None
        
        # Handle list of elements
        if isinstance(element, list):
            return [await extract(el, attribute) for el in element]
        
        # Handle BeautifulSoup Tag
        if isinstance(element, Tag):
            if attribute == "text":
                return element.get_text(strip=True)
            else:
                return element.get(attribute)
        
        # Handle dict (from FETCH result or JSON-LD)
        if isinstance(element, dict):
            # If extracting 'text' from a FETCH result, return the content
            if attribute == "text" and "content" in element:
                return element.get("content", "")
            return element.get(attribute)
        
        # Handle string (e.g., raw text)
        if isinstance(element, str):
            if attribute == "text":
                return element
            return None
        
        # Handle non-standard element types
        logger.warning(f"EXTRACT: Unknown element type {type(element)}")
        return None
    
    except Exception as e:
        logger.error(f"EXTRACT error: {e}")
        return None