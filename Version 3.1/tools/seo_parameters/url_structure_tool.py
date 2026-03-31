from urllib.parse import urlparse
import logging
from langchain_core.tools import tool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def analyze_url_structure_tool(url: str) -> dict:
    """
    Analyzes the structure of a given URL, checking for URL depth and segments (folders).
    
    Args:
        url: The URL string to analyze.
        
    Returns:
        A dictionary with analysis details including URL depth, path segments, status, and message.
    """
    parsed_url = urlparse(url)
    path_segments = [s for s in parsed_url.path.split('/') if s]
    
    return {
        "url": url,
        "path_depth": len(path_segments),
        "path_segments": path_segments,
        "status": "success",
        "message": f"URL depth: {len(path_segments)}, Segments: {', '.join(path_segments) if path_segments else 'None'}"
    }

