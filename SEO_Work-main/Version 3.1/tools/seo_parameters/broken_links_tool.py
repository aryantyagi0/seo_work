from urllib.parse import urlparse, urljoin, urlunparse
import logging
import asyncio
from langchain_core.tools import tool
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
import atexit
import functools
import sys
import os

# Import the centralized fetcher
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from tools.fetch_tool import fetch_url_data

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Create a global ThreadPoolExecutor with a balanced number of workers (Safe Zone)
executor = ThreadPoolExecutor(max_workers=10)

# Register a shutdown function to ensure the executor is properly closed on exit
atexit.register(executor.shutdown, wait=True)

@tool
async def check_broken_links_tool(html_content: str, base_url: str) -> dict:
    '''
    Checks for broken internal and external links with optimized speed and SSL fallback.
    '''
    if not html_content:
        return {"status": "error", "message": "No HTML content provided for broken links analysis.", "details": []}

    try:
        soup = BeautifulSoup(html_content, 'html.parser')
    except Exception as e:
        return {"status": "error", "message": f"Failed to parse HTML for broken links analysis: {e}", "details": []}

    checked_urls = set() 
    loop = asyncio.get_running_loop()
    
    urls_to_check = []
    for link_tag in soup.find_all('a', href=True):
        href = link_tag['href']
        if href.startswith('#') or href.startswith('mailto:') or href.startswith('tel:'):
            continue
        full_url = urljoin(base_url, href)
        parsed_url = urlparse(full_url)
        normalized_url = urlunparse(parsed_url._replace(query='', fragment=''))
        if normalized_url not in checked_urls:
            checked_urls.add(normalized_url)
            urls_to_check.append(full_url)

    async def check_url(url):
        # Tiny constant breather
        await asyncio.sleep(0.05)
        
        result = await loop.run_in_executor(
            executor,
            functools.partial(
                fetch_url_data,
                url,
                method="HEAD",
                timeout=10, # Reduced for speed
                allow_redirects=True
            )
        )
        status_code = result.get("status_code", 0)
        if status_code >= 400 or status_code == 0:
            return {
                "url": url, 
                "status_code": status_code or "Unreachable", 
                "message": result.get("error") or f"HTTP {status_code}"
            }
        return None

    # Parallel execution
    tasks = [check_url(url) for url in urls_to_check]
    results = await asyncio.gather(*tasks)
    broken_links = [r for r in results if r is not None]

    if broken_links:
        return {"status": "error", "message": f"{len(broken_links)} broken links found.", "details": broken_links}
    return {"status": "success", "message": "No broken links found.", "details": []}
