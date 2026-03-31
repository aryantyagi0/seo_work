import logging
from typing import Dict, Any
from urllib.parse import urljoin
import asyncio
import requests
import urllib3
from requests.exceptions import SSLError, RequestException
from langchain_core.tools import tool

# Suppress warnings for insecure retries
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

_ROBOTS_CACHE: Dict[str, Dict[str, Any]] = {}

@tool
async def analyze_robots_txt(base_url: str) -> dict:
    """
    Fetches and analyzes the robots.txt file of a given base URL.
    Returns the content if found, or an informative message if not found or inaccessible.
    """
    if base_url in _ROBOTS_CACHE:
        return _ROBOTS_CACHE[base_url]

    robots_url = urljoin(base_url, "/robots.txt")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    
    try:
        # First Attempt: Strict SSL
        response = await asyncio.to_thread(
            requests.get,
            robots_url,
            headers=headers,
            timeout=10,
            verify=True
        )
        response.raise_for_status()
        content = response.text
        message = "robots.txt found and fetched successfully."
        status = "success"
    except (SSLError, RequestException) as e:
        # Fallback only for SSL issues or try again without verification on any fetch error
        try:
            response = await asyncio.to_thread(
                requests.get,
                robots_url,
                headers=headers,
                timeout=10,
                verify=False
            )
            response.raise_for_status()
            content = response.text
            message = "robots.txt fetched successfully."
            status = "success" # Changed from warning to success
        except RequestException as fallback_e:
            content = "" # Critical: Ensure this is an empty string for the sitemap tool
            message = f"robots.txt could not be fetched (even with insecure fallback): {fallback_e}"
            status = "warning"

    result = {
        "status": status,
        "message": message,
        "details": {"robots_url": robots_url, "content": content},
    }

    _ROBOTS_CACHE[base_url] = result
    return result
