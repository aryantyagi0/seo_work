import logging
from langchain_core.tools import tool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def analyze_og_tags_tool(og_tags: dict, required_tags: list = None) -> dict:
    """
    Analyzes Open Graph (OG) tags for the given data: checks for existence
    and content of specified required tags.
    
    Args:
        og_tags: A dictionary of Open Graph tags already extracted from the page.
        required_tags: An optional list of OG tags to specifically check for.
                       Defaults to commonly required tags if not provided.
        
    Returns:
        A dictionary with analysis status, message, and details of found/missing OG tags.
    """
    if not og_tags:
        return {"status": "warning", "message": "No OG tags provided for analysis.", "details": {}}

    if required_tags is None:
        required_tags = ["og:title", "og:description", "og:image", "og:url", "og:type"]
        
    og_results = {}
    missing_tags = []
    
    for tag_name in required_tags:
        if tag_name in og_tags and og_tags[tag_name]:
            og_results[tag_name] = {"status": "found", "content": og_tags[tag_name]}
        else:
            missing_tags.append(tag_name)
            og_results[tag_name] = {"status": "missing", "content": None}
            
    if missing_tags:
        return {"status": "warning", "message": f"Missing Open Graph tags: {', '.join(missing_tags)}", "details": og_results}
    return {"status": "success", "message": "All required Open Graph tags are present.", "details": og_results}
