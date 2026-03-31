from bs4 import BeautifulSoup
from langchain_core.tools import tool
import logging
import re

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def analyze_meta_description_tool(html_content: str, criteria: dict = None) -> dict:
    """
    Extracts and validates the meta description tag.
    """
    if criteria is None:
        criteria = {}
    if not html_content:
        return {"status": "error", "message": "No HTML content provided for meta description analysis.", "details": {}}
    try:
        soup = BeautifulSoup(html_content, 'lxml')
        # Search for meta tags with 'description' in 'name' or 'property' (case-insensitive)
        tag = soup.find('meta', attrs={'name': re.compile(r'description', re.I)}) or \
              soup.find('meta', attrs={'property': re.compile(r'description', re.I)})
        
        description = tag.get('content').strip() if tag and tag.get('content') else None
        if not description:
            return {"status": "error", "message": "Meta description is missing.", "details": {}}
        min_length = criteria.get("min_length", 50)
        max_length = criteria.get("max_length", 160)
        if len(description) < min_length:
            return {"status": "warning", "message": f"Meta description too short ({len(description)} < {min_length}).", "details": {"value": description, "length": len(description)}}
        if len(description) > max_length:
            return {"status": "warning", "message": f"Meta description too long ({len(description)} > {max_length}).", "details": {"value": description, "length": len(description)}}
        return {"status": "success", "message": f"Meta description length {len(description)}.", "details": {"value": description, "length": len(description)}}
    except Exception as e:
        return {"status": "error", "message": f"Error during meta description analysis: {e}", "details": {}}

