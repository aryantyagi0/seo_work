import requests
import urllib3
import asyncio
from requests.exceptions import SSLError, RequestException, Timeout
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse

# Suppress insecure request warnings globally
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Global memory to store which domains need SSL fallback
# format: {"domain.com": True/False}
_SSL_FALLBACK_CACHE: Dict[str, bool] = {}

def fetch_html(url: str) -> str:
    """Legacy wrapper for backward compatibility."""
    result = fetch_url_data(url, method="GET")
    return result.get("text", "")

def fetch_url_data(url: str, method: str = "GET", timeout: int = 15, allow_redirects: bool = True) -> Dict[str, Any]:
    """
    Universal fetcher with Intelligent SSL State Memory.
    Remembers if a domain requires SSL fallback to skip the "Wait-for-Failure" delay.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    parsed_url = urlparse(url)
    domain = parsed_url.netloc
    
    # Check if we already know this domain needs fallback
    needs_insecure = _SSL_FALLBACK_CACHE.get(domain, False)

    def perform_request(verify_ssl: bool):
        if method.upper() == "GET":
            return requests.get(url, headers=headers, timeout=timeout, verify=verify_ssl, allow_redirects=allow_redirects)
        elif method.upper() == "HEAD":
            return requests.head(url, headers=headers, timeout=timeout, verify=verify_ssl, allow_redirects=allow_redirects)
        else:
            return requests.request(method.upper(), url, headers=headers, timeout=timeout, verify=verify_ssl, allow_redirects=allow_redirects)

    # Optimization: If domain is cached as 'difficult', go straight to insecure
    if needs_insecure:
        try:
            response = perform_request(verify_ssl=False)
            return {
                "status_code": response.status_code,
                "text": response.text if method.upper() == "GET" else "",
                "headers": dict(response.headers),
                "url": response.url,
                "error": "SSL Verification Bypassed (Cached State)",
                "ssl_fallback": True
            }
        except RequestException as e:
            return {"status_code": 0, "text": "", "headers": {}, "url": url, "error": str(e), "ssl_fallback": True}

    # Standard Flow: Try Strict first
    try:
        response = perform_request(verify_ssl=True)
        return {
            "status_code": response.status_code,
            "text": response.text if method.upper() == "GET" else "",
            "headers": dict(response.headers),
            "url": response.url,
            "error": None,
            "ssl_fallback": False
        }
    except SSLError:
        # Detected failure: Update cache so next time we skip the wait
        _SSL_FALLBACK_CACHE[domain] = True
        try:
            response = perform_request(verify_ssl=False)
            return {
                "status_code": response.status_code,
                "text": response.text if method.upper() == "GET" else "",
                "headers": dict(response.headers),
                "url": response.url,
                "error": "SSL Verification Failed (Insecure Fallback Used)",
                "ssl_fallback": True
            }
        except RequestException as e:
            return {"status_code": 0, "text": "", "headers": {}, "url": url, "error": str(e), "ssl_fallback": True}
    except (RequestException, Timeout) as e:
        return {"status_code": 0, "text": "", "headers": {}, "url": url, "error": str(e), "ssl_fallback": False}

async def fetch_urls_batch(urls: List[str], max_concurrent: int = 10) -> Dict[str, str]:
    """
    Fetches multiple URLs in parallel using asyncio and thread pooling for requests.
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def _fetch_with_semaphore(url: str):
        async with semaphore:
            result = await asyncio.to_thread(fetch_url_data, url)
            return url, result.get("text", "")

    tasks = [_fetch_with_semaphore(url) for url in urls]
    results = await asyncio.gather(*tasks)
    return dict(results)
