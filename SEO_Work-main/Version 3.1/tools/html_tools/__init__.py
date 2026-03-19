from .crawl_tool import crawl_page_content
from .text_extractor_tool import extract_clean_text_from_html_tool

# Internal helper used by some analyzer tools (e.g., site_hierarchy).
def _parse_html_internal(html_content: str):
    from bs4 import BeautifulSoup
    if not html_content:
        return None
    try:
        return BeautifulSoup(html_content, "lxml")
    except Exception:
        return None
