from bs4 import BeautifulSoup
import json
import logging
from langchain_core.tools import tool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def analyze_faq_in_blog_tool(html_content: str) -> dict:
    """
    Analyzes the HTML content to detect FAQ (Frequently Asked Questions) sections,
    specifically looking for FAQPage Schema.org markup or common HTML patterns
    like lists of questions and answers.
    
    Args:
        html_content: The raw HTML content of the page.
        
    Returns:
        A dictionary indicating detection status, message, and details of detected FAQs.
    """
    if not html_content:
        return {"status": "error", "message": "No HTML content provided for FAQ analysis.", "details": {}}

    try:
        soup = BeautifulSoup(html_content, 'lxml')
    except Exception as e:
        return {"status": "error", "message": f"Failed to parse HTML for FAQ analysis: {e}", "details": {}}

    faq_found_html = False
    faq_found_schema = False
    schema_details = []
    
    # Check for FAQPage Schema.org
    schema_scripts = soup.find_all('script', type='application/ld+json')
    for script in schema_scripts:
        try:
            schema_data = json.loads(script.string)
            if isinstance(schema_data, dict) and schema_data.get('@type') == 'FAQPage':
                faq_found_schema = True
                schema_details.append(schema_data)
            elif isinstance(schema_data, list):
                for item in schema_data:
                    if isinstance(item, dict) and item.get('@type') == 'FAQPage':
                        faq_found_schema = True
                        schema_details.append(item)
        except json.JSONDecodeError:
            pass # Ignore malformed JSON-LD

    # Check for common HTML patterns (e.g., div with class 'faq', dl/dt/dd, ul/li with Q&A)
    # This is heuristic and can vary by site.
    if (soup.find(class_=lambda x: x and ('faq' in x.lower() or 'question' in x.lower())) or 
       soup.find('dl', class_=lambda x: x and 'faq' in x.lower()) or 
       soup.find('ul', class_=lambda x: x and 'faq' in x.lower()) or 
       soup.find('div', class_=lambda x: x and 'accordion' in x.lower() and ('faq' in x.lower() or 'question' in x.lower()))):
        faq_found_html = True
    
    if faq_found_schema and faq_found_html:
        return {"status": "success", "message": "FAQ section detected via both HTML patterns and Schema.org.", "html_found": True, "schema_found": True, "schema_details": schema_details}
    elif faq_found_schema:
        return {"status": "success", "message": "FAQ section detected via Schema.org.", "html_found": False, "schema_found": True, "schema_details": schema_details}
    elif faq_found_html:
        return {"status": "success", "message": "FAQ section detected via common HTML patterns.", "html_found": True, "schema_found": False, "schema_details": []}
    else:
        return {"status": "info", "message": "No obvious FAQ section detected via common HTML patterns or Schema.org.", "html_found": False, "schema_found": False, "schema_details": []}

