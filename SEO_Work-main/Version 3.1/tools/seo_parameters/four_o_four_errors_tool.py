import logging
import asyncio
from langchain_core.tools import tool
from concurrent.futures import ThreadPoolExecutor
import atexit
import functools
import sys
import os

# Import the centralized fetcher
# Adjusting path to ensure import works from the tools package
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from tools.fetch_tool import fetch_url_data

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Create a global ThreadPoolExecutor with a balanced number of workers (Safe Zone)
executor = ThreadPoolExecutor(max_workers=10)

# Register a shutdown function to ensure the executor is properly closed on exit
atexit.register(executor.shutdown, wait=True)

@tool
async def check_404_errors_tool(urls_to_check: list[str]) -> dict:
    """
    Checks a list of URLs for 404 (Not Found) errors with optimized speed and SSL fallback.
    """
    errors = []
    loop = asyncio.get_running_loop()
    
    async def check_url(url):
        # Small fixed breather to prevent connection spikes
        await asyncio.sleep(0.05)
        
        # Use fetch_url_data which handles SSL fallback and HEAD requests
        result = await loop.run_in_executor(
            executor,
            functools.partial(
                fetch_url_data,
                url,
                method="HEAD",
                timeout=10, # Reduced slightly for speed
                allow_redirects=True
            )
        )
        
        if result.get("status_code") == 404:
            return {"url": url, "status_code": 404}
        elif result.get("status_code") == 0:
            return {"url": url, "status_code": "Error", "message": result.get("error")}
        return None

    # Run checks in parallel for better performance
    tasks = [check_url(url) for url in urls_to_check]
    results = await asyncio.gather(*tasks)
    
    # Filter out None results (successes)
    errors = [r for r in results if r is not None]
            
    if errors:
        return {"status": "error", "message": f"{len(errors)} 404 errors found among {len(urls_to_check)} URLs checked.", "details": errors}
    return {"status": "success", "message": f"No 404 errors found among the {len(urls_to_check)} checked URLs.", "details": []}
