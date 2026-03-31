from bs4 import BeautifulSoup
import json
import logging
from langchain_core.tools import tool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def analyze_breadcrumb_tool(html_content: str, criteria: dict = None) -> dict:
    """
    Analyzes the HTML content to detect breadcrumb navigation, either via
    Schema.org BreadcrumbList markup or common HTML patterns.
    
    Args:
        html_content: The raw HTML content of the page.
        
    Returns:
        A dictionary indicating detection status and details.
    """
    if criteria is None:
        criteria = {}
    if not html_content:
        return {"status": "error", "message": "No HTML content provided for breadcrumb analysis.", "details": {"reason": "missing_html"}}

    try:
        soup = BeautifulSoup(html_content, 'lxml')
    except Exception as e:
        return {"status": "error", "message": f"Failed to parse HTML for breadcrumb analysis: {e}", "details": {}}

    breadcrumb_found_html = False
    breadcrumb_found_schema = False
    schema_details = []

    # Check for Schema.org BreadcrumbList
    schema_types = criteria.get("schema_types", ["BreadcrumbList"])
    schema_scripts = soup.find_all('script', type='application/ld+json')
    for script in schema_scripts:
        try:
            schema_data = json.loads(script.string)
            if isinstance(schema_data, dict) and schema_data.get('@type') in schema_types:
                breadcrumb_found_schema = True
                schema_details.append(schema_data)
            elif isinstance(schema_data, list): # Handle cases where root is a list of schemas
                for item in schema_data:
                    if isinstance(item, dict) and item.get('@type') in schema_types:
                        breadcrumb_found_schema = True
                        schema_details.append(item)
        except json.JSONDecodeError:
            pass # Ignore malformed JSON-LD

    # Check for common HTML patterns (e.g., nav > ol > li, or specific classes)
    # This is heuristic and can vary greatly by site
    aria_labels = criteria.get("aria_labels", ["breadcrumb"])
    class_keywords = criteria.get("class_keywords", ["breadcrumb", "crumbs"])
    if soup.find('nav', {'aria-label': lambda x: x and x.lower() in aria_labels}) or \
       soup.find('ol', class_=lambda x: x and any(k in x.split() for k in class_keywords)) or \
       soup.find(lambda tag: tag.name == 'div' and tag.get('class') and any(k in tag.get('class') for k in class_keywords)):
        breadcrumb_found_html = True
    
    if breadcrumb_found_schema and breadcrumb_found_html:
        return {"status": "success", "message": "Breadcrumb navigation detected via both HTML and Schema.org.", "html_found": True, "schema_found": True, "schema_details": schema_details}
    elif breadcrumb_found_schema:
        return {"status": "success", "message": "Breadcrumb navigation detected via Schema.org.", "html_found": False, "schema_found": True, "schema_details": schema_details}
    elif breadcrumb_found_html:
        return {"status": "success", "message": "Breadcrumb navigation detected via common HTML patterns.", "html_found": True, "schema_found": False, "schema_details": []}
    else:
        return {"status": "warning", "message": "No breadcrumb navigation detected via common HTML patterns or Schema.org.", "html_found": False, "schema_found": False, "schema_details": []}
