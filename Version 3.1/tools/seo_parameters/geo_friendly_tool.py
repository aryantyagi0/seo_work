import logging
import re
from bs4 import BeautifulSoup
from langchain_core.tools import tool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def analyze_geo_friendly_tool(html_content: str | None = None, page_text_content: str | None = None) -> dict:
    """
    Rule-based GEO-friendly check for AI search readiness:
    - Heading structure present
    - Short paragraphs (<= 40 words) ratio
    """
    if not html_content:
        if not page_text_content:
            return {"status": "error", "message": "No content provided for GEO-Friendly analysis."}
        word_count = len(re.findall(r"\b\w+\b", page_text_content))
        return {
            "status": "needs_improvement",
            "message": "HTML not provided; GEO structure check incomplete.",
            "details": {"text_word_count": word_count},
        }

    try:
        soup = BeautifulSoup(html_content, 'lxml')
    except Exception as e:
        return {"status": "error", "message": f"Failed to parse HTML for GEO-Friendly analysis: {e}"}

    headings = soup.find_all(['h1', 'h2', 'h3'])
    paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all('p') if p.get_text(strip=True)]

    short_paragraphs = 0
    for p in paragraphs:
        word_count = len(re.findall(r"\b\w+\b", p))
        if word_count <= 40:
            short_paragraphs += 1

    short_ratio = (short_paragraphs / len(paragraphs)) if paragraphs else 0.0
    has_headings = len(headings) > 0

    status = "pass" if has_headings and short_ratio >= 0.7 else "needs_improvement"
    message = "GEO-friendly structure check complete."

    return {
        "status": status,
        "message": message,
        "details": {
            "heading_count": len(headings),
            "paragraph_count": len(paragraphs),
            "short_paragraph_ratio": short_ratio,
        },
    }

