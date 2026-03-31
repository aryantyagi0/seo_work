from urllib.parse import urlparse, urljoin
import logging
import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from tools.html_tools import _parse_html_internal # Import the internal parser

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def analyze_url_structure(url: str):
    """
    Analyzes the structure of a given URL.
    Checks for URL depth and segments (folders).
    """
    parsed_url = urlparse(url)
    path_segments = [s for s in parsed_url.path.split('/') if s]
    
    return {
        "url": url,
        "path_depth": len(path_segments),
        "path_segments": path_segments,
        "status": "success",
        "message": f"URL depth: {len(path_segments)}, Segments: {', '.join(path_segments) if path_segments else 'None'}"
    }

def get_sitemap_urls(sitemap_url: str):
    """
    Fetches and parses an XML sitemap to extract URLs.
    """
    try:
        response = requests.get(sitemap_url, timeout=10)
        response.raise_for_status()
        
        root = ET.fromstring(response.content)
        
        # Namespace for sitemap elements
        namespace = {'sitemap': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        
        urls = []
        for url_element in root.findall('sitemap:url', namespace):
            loc = url_element.find('sitemap:loc', namespace)
            if loc is not None:
                urls.append(loc.text)
        
        return {"status": "success", "message": f"Found {len(urls)} URLs in sitemap.", "urls": urls}
    except requests.RequestException as e:
        return {"status": "error", "message": f"Error fetching sitemap from {sitemap_url}: {e}"}
    except ET.ParseError as e:
        return {"status": "error", "message": f"Error parsing sitemap XML from {sitemap_url}: {e}"}
    except Exception as e:
        return {"status": "error", "message": f"An unexpected error occurred: {e}"}

def map_internal_links(html_content: str, base_url: str):
    """
    Extracts all internal links from the HTML content of a page.
    Returns a list of dictionaries with link and anchor text.
    """
    soup = _parse_html_internal(html_content)
    if not soup:
        return {"status": "error", "message": "Failed to parse HTML for internal links mapping."}

    internal_links = []
    parsed_base_url = urlparse(base_url)
    
    for link_tag in soup.find_all('a', href=True):
        href = link_tag['href']
        anchor_text = link_tag.get_text(strip=True)
        
        # Ignore fragments, mailto, tel links
        if href.startswith('#') or href.startswith('mailto:') or href.startswith('tel:'):
            continue
        
        full_url = requests.compat.urljoin(base_url, href)
        parsed_full_url = urlparse(full_url)
        
        if parsed_full_url.netloc == parsed_base_url.netloc: # Check if same domain
            internal_links.append({"url": full_url, "anchor_text": anchor_text})
            
    return {"status": "success", "message": f"Found {len(internal_links)} internal links.", "links": internal_links}

if __name__ == "__main__":
    # Example Usage
    print("--- Test analyze_url_structure ---")
    url1 = "https://www.example.com/category/subcategory/page-name.html"
    url2 = "https://blog.example.com/post-title"
    print(analyze_url_structure(url1))
    print(analyze_url_structure(url2))

    print("\n--- Test get_sitemap_urls ---")
    # Replace with a real sitemap URL for testing
    # sitemap_test_url = "https://www.google.com/sitemap.xml" # This URL can be problematic for direct access
    sitemap_test_url = "https://www.apple.com/sitemap.xml" # Using a more reliable sitemap for example
    sitemap_results = get_sitemap_urls(sitemap_test_url)
    print(sitemap_results)

    print("\n--- Test map_internal_links ---")
    # Using a placeholder HTML content for demonstration
    html_content_example = """
    <html>
    <body>
        <a href="/">Home</a>
        <a href="/about">About Us</a>
        <a href="https://www.external.com/product">External Link</a>
        <a href="/category/item1">Item 1</a>
        <a href="mailto:test@example.com">Email</a>
    </body>
    </html>
    """
    base_url_example = "https://www.example.com/section/"
    internal_links_results = map_internal_links(html_content_example, base_url_example)
    print(internal_links_results)
