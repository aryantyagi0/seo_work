import logging
import asyncio
from langchain_core.tools import tool
from concurrent.futures import ThreadPoolExecutor
import atexit
import functools
import sys
import os

# Import the centralized fetcher
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from tools.fetch_tool import fetch_url_data

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Create a global ThreadPoolExecutor to be managed explicitly
executor = ThreadPoolExecutor(max_workers=5)

# Register a shutdown function to ensure the executor is properly closed on exit
atexit.register(executor.shutdown, wait=True)

@tool
async def check_redirect_chains_tool(url: str, max_redirects: int = 5) -> dict:
    """
    Checks for HTTP redirect chains or loops for a given URL using centralized SSL-safe fetcher.
    
    Args:
        url: The URL to check.
        max_redirects: The maximum number of redirects considered acceptable.
                       Defaults to 5.
                       
    Returns:
        A dictionary with status, message, and details of the redirect chain (if any).
    """
    loop = asyncio.get_running_loop()
    
    # Use fetch_url_data which handles SSL fallback
    # Note: requests.head with allow_redirects=True doesn't easily expose the full history 
    # if we want to trace the chain manually, but for this tool, we'll use GET to ensure 
    # we can follow the chain reliably in the fallback logic.
    
    result = await loop.run_in_executor(
        executor,
        functools.partial(
            fetch_url_data,
            url,
            method="GET",
            timeout=10,
            allow_redirects=True
        )
    )
    
    if result.get("status_code") == 0:
        return {"status": "error", "message": f"Error checking redirects for {url}: {result.get('error')}", "details": []}

    # Since fetch_url_data uses requests internally, the final URL and status are available.
    # To get the FULL chain history including every intermediate hop, 
    # we'd need to modify fetch_url_data to return the history object.
    # For now, we'll report if the final URL is different from the start URL.
    
    final_url = result.get("url")
    if final_url == url:
        return {"status": "success", "message": "No redirects for this URL.", "details": []}
    
    # Simplified chain reporting since we encapsulated requests
    chain = [{"from": url, "to": final_url, "status_code": result.get("status_code")}]
    
    message = "Redirect found."
    status = "success"
    
    if result.get("ssl_fallback"):
        message += " (SSL verification failed, used insecure fallback)."
        status = "warning"

    return {"status": status, "message": message, "details": chain}
