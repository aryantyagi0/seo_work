import logging
import re
from bs4 import BeautifulSoup
from langchain_core.tools import tool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def analyze_eeat_tool(html_content: str | None = None, page_text_content: str | None = None) -> dict:
    """
    Rule-based EEAT checks for blog pages:
    - Author details (name + experience/credentials)
    - Social profile (LinkedIn)
    - Author summary/bio
    """
    if not html_content:
        return {"status": "needs_improvement", "message": "No HTML content provided for EEAT analysis.", "details": {}}

    try:
        soup = BeautifulSoup(html_content, 'lxml')
    except Exception as e:
        return {"status": "error", "message": f"Failed to parse HTML for EEAT analysis: {e}"}

    author_name = None
    author_section_text = ""

    meta_author = soup.find('meta', attrs={'name': 'author'})
    if meta_author and meta_author.get('content'):
        author_name = meta_author['content'].strip()

    author_candidates = soup.find_all(
        lambda tag: tag.get('class') and any('author' in c.lower() or 'byline' in c.lower() or 'bio' in c.lower() for c in tag.get('class', []))
    ) + soup.find_all(id=lambda v: v and any(k in v.lower() for k in ['author', 'byline', 'bio']))

    for tag in author_candidates:
        text = tag.get_text(" ", strip=True)
        if text and len(text.split()) >= 5:
            author_section_text = text
            if not author_name:
                match = re.search(r"\bby\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)", text)
                if match:
                    author_name = match.group(1)
            break

    author_experience = False
    if author_section_text:
        if re.search(r"\b\d+\+?\s*(years|yrs)\b", author_section_text.lower()):
            author_experience = True
        if re.search(r"\b(expert|specialist|certified|credential|experience)\b", author_section_text.lower()):
            author_experience = True

    linkedin_present = any("linkedin.com" in (a.get("href") or "") for a in soup.find_all("a", href=True))

    author_summary_present = len(author_section_text.split()) >= 30

    author_details_present = bool(author_name) and author_experience

    missing = []
    if not author_details_present:
        missing.append("author_details")
    if not linkedin_present:
        missing.append("author_social_profile")
    if not author_summary_present:
        missing.append("author_summary")

    status = "pass" if not missing else "needs_improvement"

    return {
        "status": status,
        "message": "EEAT checks completed for author signals.",
        "details": {
            "author_name_present": bool(author_name),
            "author_experience_present": author_experience,
            "author_social_profile_present": linkedin_present,
            "author_summary_present": author_summary_present,
            "missing": missing,
        },
    }

