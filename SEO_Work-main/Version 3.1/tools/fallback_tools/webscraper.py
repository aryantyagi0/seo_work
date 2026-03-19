from bs4 import BeautifulSoup
import logging
from tools.html_tools.crawl_tool import crawl_page_content # Import the crawl_page_content tool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def scrape_page(url: str):
    """
    Scrapes a single web page and returns its content using crawl_page_content.
    """
    try:
        html_content = crawl_page_content(url=url)
        
        if not html_content or "Error crawling" in html_content:
            logging.error(f"Failed to retrieve HTML content for {url}: {html_content}")
            return None
        
        soup = BeautifulSoup(html_content, 'lxml')
        
        # Extract text content
        text = soup.get_text(separator=' ', strip=True)
        
        return {
            "url": url,
            "title": soup.title.string if soup.title else "No title found",
            "text": text,
        }
    except Exception as e:
        logging.error(f"Error scraping {url}: {e}")
        return None
