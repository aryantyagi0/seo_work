from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import logging
from tools.html_tools.crawl_tool import crawl_page_content # Import the crawl_page_content tool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def crawl_page(url: str, max_links: int = 10):
    """
    Crawls a web page to find and return a list of links using crawl_page_content.
    """
    try:
        html_content = crawl_page_content(url=url)
        
        if not html_content or "Error crawling" in html_content:
            logging.error(f"Failed to retrieve HTML content for {url}: {html_content}")
            return []

        soup = BeautifulSoup(html_content, 'lxml')
        links = set()
        base_netloc = urlparse(url).netloc

        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            full_url = urljoin(url, href)
            
            # Ensure the link is from the same domain
            if urlparse(full_url).netloc == base_netloc:
                links.add(full_url)
            
            if len(links) >= max_links:
                break
        
        return list(links)

    except Exception as e:
        logging.error(f"Error crawling {url}: {e}")
        return []
