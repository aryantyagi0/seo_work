"""
FETCH Primitive: Get any resource from the web
Supports both static (aiohttp) and dynamic (Crawl4AI) fetching.
Crawl4AI auto-disables when Playwright can't run (e.g., Streamlit on Windows).
"""
import sys
import threading
import aiohttp
from typing import Dict, Any, Optional
from utils.logging_config import get_logger
from config.settings import (
    CRAWL_TIMEOUT, 
    USER_AGENT, 
    CRAWL4AI_ENABLED,
    CRAWL4AI_BROWSER,
    CRAWL4AI_HEADLESS,
    CRAWL4AI_WAIT_FOR
)

logger = get_logger("FETCH")

# Track if Crawl4AI has already failed to avoid repeated errors
_crawl4ai_disabled = False


async def fetch(url: str, method: str = "GET", resource_type: str = "html", render_js: bool = False) -> Dict[str, Any]:
    """
    Fetch a resource from the web
    
    Args:
        url: Target URL (string) or dict with scheme/domain/path
        method: HTTP method (GET, HEAD)
        resource_type: Expected type (html, text, xml)
        render_js: If True, use Crawl4AI to render JavaScript (default: False)
    
    Returns:
        {
            status: int,
            content: str,
            headers: dict,
            redirect_chain: list,
            final_url: str,
            error: str or None,
            rendered_with: "aiohttp" or "crawl4ai"
        }
    """
    
    # Handle URL string input
    if isinstance(url, dict):
        scheme = url.get("scheme", "https")
        domain = url.get("domain", "")
        path = url.get("path", "")
        query = url.get("query", "")
        url = f"{scheme}://{domain}{path}{'?' + query if query else ''}"
        logger.debug(f"Converted dict to URL: {url}")
    
    # Ensure URL is in string format
    url = str(url)
    
    # Route to Crawl4AI if JavaScript rendering is requested
    if render_js and CRAWL4AI_ENABLED:
        # Skip Crawl4AI if it previously failed or if not in main thread
        # (Playwright subprocess creation fails in non-main threads on Windows)
        global _crawl4ai_disabled
        if _crawl4ai_disabled:
            logger.debug("Crawl4AI previously failed, falling back to aiohttp")
            return await _fetch_with_aiohttp(url, method, resource_type)
        
        if sys.platform == "win32" and threading.current_thread() is not threading.main_thread():
            logger.info("Crawl4AI skipped: Playwright requires main thread on Windows, using aiohttp")
            _crawl4ai_disabled = True
            return await _fetch_with_aiohttp(url, method, resource_type)
        
        return await _fetch_with_crawl4ai(url)
    
    # Default: Use aiohttp (static fetch)
    return await _fetch_with_aiohttp(url, method, resource_type)


async def _fetch_with_aiohttp(url: str, method: str, resource_type: str) -> Dict[str, Any]:
    """Fetch content using aiohttp"""
    result = {
        "status": None,
        "content": None,
        "headers": {},
        "redirect_chain": [],
        "final_url": url,
        "error": None,
        "rendered_with": "aiohttp"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.request(
                method,
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=CRAWL_TIMEOUT),
                allow_redirects=True,
                ssl=False  # Disable SSL verification for problematic sites
            ) as response:
                result["status"] = response.status
                result["headers"] = dict(response.headers)
                result["final_url"] = str(response.url)
                result["redirect_chain"] = [str(r.url) for r in response.history]
                
                # Only fetch content on successful GET requests
                if method == "GET" and response.status == 200:
                    result["content"] = await response.text()
                
                logger.info(f"FETCH (aiohttp) {url} → {response.status}")
    
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"FETCH (aiohttp) error for {url}: {e}")
    
    return result


async def _fetch_with_crawl4ai(url: str) -> Dict[str, Any]:
    """Fetch content using Crawl4AI with JavaScript rendering"""
    result = {
        "status": None,
        "content": None,
        "headers": {},
        "redirect_chain": [],
        "final_url": url,
        "error": None,
        "rendered_with": "crawl4ai"
    }
    
    try:
        from crawl4ai import AsyncWebCrawler
        
        async with AsyncWebCrawler(
            headless=CRAWL4AI_HEADLESS,
            verbose=False
        ) as crawler:
            crawl_result = await crawler.arun(
                url=url,
                bypass_cache=True
            )
            
            if crawl_result.success:
                result["status"] = 200
                result["content"] = crawl_result.html
                result["final_url"] = crawl_result.url
                result["headers"] = {}
                
                logger.info(f"FETCH (crawl4ai) {url} → Success (JavaScript rendered)")
            else:
                result["error"] = crawl_result.error_message
                result["status"] = 500
                logger.error(f"FETCH (crawl4ai) failed for {url}: {crawl_result.error_message}")
    
    except ImportError:
        global _crawl4ai_disabled
        logger.error("Crawl4AI not installed. Install with: pip install crawl4ai")
        result["error"] = "Crawl4AI not installed"
        _crawl4ai_disabled = True
        # Fallback to aiohttp
        return await _fetch_with_aiohttp(url, "GET", "html")
    
    except (NotImplementedError, RuntimeError) as e:
        # Playwright subprocess creation fails on Windows in non-main threads
        _crawl4ai_disabled = True
        logger.warning(f"Crawl4AI unavailable (Playwright error), falling back to aiohttp: {type(e).__name__}")
        return await _fetch_with_aiohttp(url, "GET", "html")
    
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"FETCH (crawl4ai) error for {url}: {e}")
        # Fallback to aiohttp
        return await _fetch_with_aiohttp(url, "GET", "html")
    
    return result