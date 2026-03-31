import logging
import asyncio
from langchain_core.tools import tool
from concurrent.futures import ThreadPoolExecutor
import atexit
import functools
import sys
import os
from urllib.parse import urljoin

# Import the centralized fetcher
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from tools.fetch_tool import fetch_url_data

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Create a global ThreadPoolExecutor to be managed explicitly
executor = ThreadPoolExecutor(max_workers=5)

# Register a shutdown function to ensure the executor is properly closed on exit
atexit.register(executor.shutdown, wait=True)

@tool
async def check_llmstext_file_tool(base_url: str) -> dict:
    """
    Checks for the existence of an 'llms.txt' file at the root of the given base URL using centralized SSL-safe fetcher.
    
    Args:
        base_url: The base URL of the website (e.g., "https://example.com").
        
    Returns:
        A dictionary with status and message regarding the detection of the llms.txt file.
    """
    llmstext_url = urljoin(base_url, "/llms.txt")
    loop = asyncio.get_running_loop()
    
    result = await loop.run_in_executor(
        executor,
        functools.partial(
            fetch_url_data,
            llmstext_url,
            method="HEAD",
            timeout=15
        )
    )
    
    status_code = result.get("status_code", 0)
    if status_code == 200:
        message = f"llms.txt file found at {llmstext_url}."
        if result.get("ssl_fallback"):
            message += " (Verified via insecure SSL connection)."
        return {"status": "success", "message": message}
    
    return {"status": "info", "message": f"llms.txt file not found or inaccessible at {llmstext_url}. Status code: {status_code if status_code != 0 else 'Error'}"}
