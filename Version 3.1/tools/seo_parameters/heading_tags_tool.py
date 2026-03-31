import logging
from langchain_core.tools import tool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def analyze_heading_tags_tool(h1_tags: list[str], h2_tags: list[str], h3_tags: list[str]) -> dict:
    """
    Analyzes heading tags (H1, H2, H3) data: counts them and checks for multiple H1s.
    
    Args:
        h1_tags: A list of H1 tag texts already extracted from the page.
        h2_tags: A list of H2 tag texts already extracted from the page.
        h3_tags: A list of H3 tag texts already extracted from the page.
        
    Returns:
        A dictionary with counts and content of H1, H2, H3 tags, and H1 specific status/message.
    """
    report = {
        "h1_count": len(h1_tags),
        "h1_content": h1_tags,
        "h2_count": len(h2_tags),
        "h2_content": h2_tags,
        "h3_count": len(h3_tags),
        "h3_content": h3_tags,
    }
    
    # Corrected Logic: Calculate status based on H1 count
    if report["h1_count"] == 1:
        report["h1_status"] = "success"
        report["h1_message"] = "Exactly one H1 tag found."
    elif report["h1_count"] == 0:
        report["h1_status"] = "error"
        report["h1_message"] = "No H1 tag found."
    else:
        report["h1_status"] = "warning"
        report["h1_message"] = f"Multiple H1 tags found ({report['h1_count']})."

    return {
        "status": report["h1_status"],
        "message": report["h1_message"],
        "details": report
    }

