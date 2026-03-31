import logging
from langchain_core.tools import tool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def analyze_schema_markup_tool(schema_markup: list[dict]) -> dict:
    """
    Analyzes JSON-LD schema markup.
    
    Args:
        schema_markup: A list of already parsed JSON-LD schema blocks extracted from the page.
        
    Returns:
        A dictionary with analysis status, message, and details of parsed schema markup.
    """
    if not schema_markup:
        return {"status": "info", "message": "No Schema Markup (JSON-LD) found.", "details": []}
    
    # Check if any parsing errors were reported during initial extraction
    if any("error" in s for s in schema_markup if isinstance(s, dict)):
        return {"status": "warning", "message": "Some Schema Markup contains parsing errors.", "details": schema_markup}
        
    return {"status": "success", "message": f"{len(schema_markup)} Schema Markup blocks found.", "details": schema_markup}

