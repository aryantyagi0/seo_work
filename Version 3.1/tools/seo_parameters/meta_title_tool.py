from bs4 import BeautifulSoup
from langchain_core.tools import tool
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def analyze_meta_title_tool(html_content: str, criteria: dict = None) -> dict:
    """
    Extracts and validates the <title> tag.
    """
    if criteria is None:
        criteria = {}
    if not html_content:
        return {"status": "error", "message": "No HTML content provided for meta title analysis.", "details": {}}
    try:
        soup = BeautifulSoup(html_content, 'lxml')
        title = soup.title.string.strip() if soup.title and soup.title.string else None
        if not title:
            return {"status": "error", "message": "Meta title is missing.", "details": {}}
        min_length = criteria.get("min_length", 10)
        max_length = criteria.get("max_length", 60)
        if len(title) < min_length:
            return {"status": "warning", "message": f"Meta title too short ({len(title)} < {min_length}).", "details": {"value": title, "length": len(title)}}
        if len(title) > max_length:
            return {"status": "warning", "message": f"Meta title too long ({len(title)} > {max_length}).", "details": {"value": title, "length": len(title)}}
        return {"status": "success", "message": f"Meta title length {len(title)}.", "details": {"value": title, "length": len(title)}}
    except Exception as e:
        return {"status": "error", "message": f"Error during meta title analysis: {e}", "details": {}}

