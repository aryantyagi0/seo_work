"""
Crawler configuration and page context builder
"""
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from typing import Dict, Any, Optional
from utils.logging_config import get_logger
from config.settings import CRAWL_TIMEOUT, USER_AGENT

logger = get_logger("Crawler")


async def build_page_context(url: str) -> Dict[str, Any]:
    """
    Fetch and parse a URL to build initial page context
    Returns raw HTML and basic metadata
    """
    context = {
        "url": url,
        "html": None,
        "soup": None,
        "status_code": None,
        "error": None,
        "redirect_chain": [],
        "final_url": url,
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=CRAWL_TIMEOUT),
                allow_redirects=True,
            ) as response:
                context["status_code"] = response.status
                context["final_url"] = str(response.url)
                context["redirect_chain"] = [str(r.url) for r in response.history]
                
                if response.status == 200:
                    html = await response.text()
                    context["html"] = html
                    context["soup"] = BeautifulSoup(html, "lxml")
                    logger.info(f"Successfully fetched: {url}")
                else:
                    context["error"] = f"HTTP {response.status}"
                    logger.warning(f"Non-200 status for {url}: {response.status}")
    
    except asyncio.TimeoutError:
        context["error"] = "Timeout"
        logger.error(f"Timeout fetching {url}")
    except Exception as e:
        context["error"] = str(e)
        logger.error(f"Error fetching {url}: {e}")
    
    return context