from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
import asyncio
import logging
import nest_asyncio
from langchain_core.tools import tool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def crawl_page_content(url: str, render_js: bool = True) -> str:
    """
    Fetches the full HTML content of a given URL, optionally rendering JavaScript.
    Uses Crawl4AI for robust web crawling and rendering.
    
    Args:
        url: The URL to crawl.
        render_js: If True, JavaScript will be rendered. Set to False for static HTML.
                   Defaults to True to handle modern websites.
        
    Returns:
        The rendered or static HTML content as a string, or an error message if crawling fails.
    """
    try:
        async def _run_crawl():
            # Configure browser and run settings for resilient fallback
            browser_config = BrowserConfig(
                headless=True,
                verbose=False,
                ignore_https_errors=True
            )
            run_config = CrawlerRunConfig(
                js_code="window.scrollTo(0, document.body.scrollHeight);" if render_js else None,
                wait_for_js=render_js,
                bypass_cache=True,
                timeout=30000 # 30s
            )

            async with AsyncWebCrawler(config=browser_config) as crawler:
                page_data = await crawler.arun(url=url, config=run_config)
                if page_data and page_data.html:
                    return page_data.html
                return f"AsyncWebCrawler did not return HTML content for {url}."

        return await _run_crawl()

    except Exception as e:
        logging.error(f"Error crawling {url} with AsyncWebCrawler: {e}")
        # Use our centralized, SSL-resilient fetcher as the ultimate fallback
        from tools.fetch_tool import fetch_url_data
        result = fetch_url_data(url, method="GET", timeout=15)
        return result.get("text", f"Error crawling {url}: {e}")
