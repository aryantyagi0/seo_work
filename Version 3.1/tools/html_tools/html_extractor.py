from bs4 import BeautifulSoup
from typing import List, Optional, Dict

def extract_title(html_content: str) -> Optional[str]:
    """
    Extracts the text content of the <title> tag from HTML.
    Returns None if no title tag is found.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    title_tag = soup.find('title')
    return title_tag.get_text(strip=True) if title_tag else None

def extract_meta_description(html_content: str) -> Optional[str]:
    """
    Extracts the content of the meta description tag.
    Returns None if no meta description is found.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    meta_desc_tag = soup.find('meta', attrs={'name': 'description'})
    return meta_desc_tag['content'].strip() if meta_desc_tag and 'content' in meta_desc_tag.attrs else None

def extract_canonical_url(html_content: str) -> Optional[str]:
    """
    Extracts the href attribute of the canonical link tag.
    Returns None if no canonical link tag is found.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    canonical_link = soup.find('link', attrs={'rel': 'canonical'})
    return canonical_link['href'].strip() if canonical_link and 'href' in canonical_link.attrs else None

def extract_images_alt_text(html_content: str) -> List[Dict[str, Optional[str]]]:
    """
    Extracts all images and their alt text.
    Returns a list of dictionaries, each containing the 'src' and 'alt' of an image.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    images = soup.find_all('img')
    result = []
    for img in images:
        result.append({
            "src": img.get("src"),
            "alt": img.get("alt")
        })
    return result
