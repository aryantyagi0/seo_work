from bs4 import BeautifulSoup
from langchain_core.tools import tool
import logging
from urllib.parse import urljoin, urlparse
import json # For schema markup extraction

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def parse_html_and_extract_tags(html_content: str, url: str) -> dict:
    """
    Parses the provided HTML content and extracts all relevant SEO-critical tags and clean text.
    This tool performs comprehensive extraction without pruning, ensuring all data is available
    for subsequent analysis and validation.

    Args:
        html_content: The full HTML content of the page.
        url: The URL of the page, used for resolving relative links and canonical checks.

    Returns:
        A dictionary containing extracted SEO elements:
        - 'title': Content of the <title> tag (str or None)
        - 'meta_description': Content of the <meta name="description"> tag (str or None)
        - 'h1_tags': List of H1 tag texts (list[str])
        - 'h2_tags': List of H2 tag texts (list[str])
        - 'h3_tags': List of H3 tag texts (list[str])
        - 'canonical_url': Canonical URL extracted (str or None)
        - 'og_tags': Dictionary of Open Graph tags (dict)
        - 'hreflang_tags': List of hreflang attributes (list[dict])
        - 'schema_markup': List of parsed JSON-LD schema blocks (list[dict])
        - 'image_alt_texts': List of dictionaries with image src and alt text (list[dict])
        - 'robots_meta': Content of the robots meta tag (str or None)
        - 'clean_text_content': All visible text content from the page (str)
        - 'all_links': List of all internal and external links found (list[str])
        - 'status': 'success' or 'error'
        - 'message': Description of any errors
    """
    if not html_content:
        logging.warning(f"No HTML content provided for parsing URL: {url}.")
        return {"status": "error", "message": "No HTML content to parse."}

    extracted_data = {
        "url": url,
        "title": None,
        "meta_description": None,
        "h1_tags": [],
        "h2_tags": [],
        "h3_tags": [],
        "canonical_url": None,
        "og_tags": {},
        "hreflang_tags": [],
        "schema_markup": [],
        "image_alt_texts": [],
        "robots_meta": None,
        "clean_text_content": None,
        "all_links": [],
        "status": "success",
        "message": "HTML parsed and tags extracted successfully."
    }

    try:
        soup = BeautifulSoup(html_content, 'lxml')

        # 1. Title
        if soup.title and soup.title.string:
            extracted_data["title"] = soup.title.string.strip()

        # 2. Meta Description
        meta_description_tag = soup.find('meta', attrs={'name': 'description'})
        if meta_description_tag and meta_description_tag.get('content'):
            extracted_data["meta_description"] = meta_description_tag['content'].strip()

        # 3. H1, H2, H3 Tags
        extracted_data["h1_tags"] = [h1.get_text(strip=True) for h1 in soup.find_all('h1') if h1.get_text(strip=True)]
        extracted_data["h2_tags"] = [h2.get_text(strip=True) for h2 in soup.find_all('h2') if h2.get_text(strip=True)]
        extracted_data["h3_tags"] = [h3.get_text(strip=True) for h3 in soup.find_all('h3') if h3.get_text(strip=True)]

        # 4. Canonical URL
        canonical_tag = soup.find('link', attrs={'rel': 'canonical'})
        if canonical_tag and canonical_tag.get('href'):
            extracted_data["canonical_url"] = urljoin(url, canonical_tag['href'].strip())

        # 5. Open Graph Tags
        og_tags = {}
        for prop in ['title', 'description', 'image', 'url', 'type', 'site_name', 'locale']:
            og_tag = soup.find('meta', property=f'og:{prop}')
            if og_tag and og_tag.get('content'):
                og_tags[f'og:{prop}'] = og_tag['content'].strip()
        if og_tags:
            extracted_data["og_tags"] = og_tags

        # 6. Hreflang Tags
        for link_tag in soup.find_all('link', attrs={'rel': 'alternate', 'hreflang': True}):
            if link_tag.get('href') and link_tag.get('hreflang'):
                extracted_data["hreflang_tags"].append({
                    "hreflang": link_tag['hreflang'].strip(),
                    "href": urljoin(url, link_tag['href'].strip())
                })

        # 7. Schema Markup (JSON-LD)
        for script_tag in soup.find_all('script', type='application/ld+json'):
            if script_tag.string:
                try:
                    schema_data = json.loads(script_tag.string)
                    if isinstance(schema_data, list):
                        extracted_data["schema_markup"].extend(schema_data)
                    elif isinstance(schema_data, dict):
                        extracted_data["schema_markup"].append(schema_data)
                except json.JSONDecodeError as e:
                    logging.warning(f"JSON-LD parsing error on {url}: {e}")

        # 8. Image Alt Texts
        for img_tag in soup.find_all('img', alt=True):
            if img_tag.get('src'):
                extracted_data["image_alt_texts"].append({
                    "src": urljoin(url, img_tag['src'].strip()),
                    "alt": img_tag['alt'].strip()
                })

        # 9. Robots Meta Tag
        robots_meta_tag = soup.find('meta', attrs={'name': 'robots'})
        if robots_meta_tag and robots_meta_tag.get('content'):
            extracted_data["robots_meta"] = robots_meta_tag['content'].strip()

        # 10. Clean Text Content (remove scripts and styles for this)
        clean_soup = BeautifulSoup(html_content, 'lxml') # Create a new soup to avoid modifying original
        for script_or_style in clean_soup(['script', 'style', 'header', 'footer', 'nav']): # Remove common non-content elements
            script_or_style.decompose()
        extracted_data["clean_text_content"] = clean_soup.get_text(separator=' ', strip=True)

        # 11. All Links (internal and external)
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            full_url = urljoin(url, href)
            # Basic validation for URLs
            if full_url.startswith('http') or full_url.startswith('https'):
                extracted_data["all_links"].append(full_url)
        # Ensure unique links
        extracted_data["all_links"] = list(dict.fromkeys(extracted_data["all_links"]))


    except Exception as e:
        logging.error(f"Error parsing HTML and extracting tags for {url}: {e}")
        extracted_data["status"] = "error"
        extracted_data["message"] = f"Error during HTML parsing: {e}"

    return extracted_data
