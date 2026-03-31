import logging
from langchain_core.tools import tool

# --- Gracefully handle Lighthouse import ---
try:
    from tools.lighthouse_tool import run_lighthouse
    LIGHTHOUSE_AVAILABLE = True
except (ImportError, SyntaxError) as e:
    logging.warning(f"Could not import Lighthouse tool, page speed analysis will be disabled. Error: {e}")
    run_lighthouse = None
    LIGHTHOUSE_AVAILABLE = False
# ---

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def analyze_page_speed_tool(url: str, form_factor: str = "mobile") -> dict:
    """
    Runs a Lighthouse performance audit to extract Core Web Vitals and performance score.
    Returns LCP, INP (or TBT fallback), CLS, and mobile performance score.
    If the Lighthouse tool is not available, it will return an informational message.
    """
    if not LIGHTHOUSE_AVAILABLE:
        return {
            "status": "info",
            "message": "Page speed tool is disabled because the Lighthouse module could not be loaded.",
            "details": {},
        }

    try:
        results = await run_lighthouse(url, form_factor=form_factor)
        return {
            "status": "success",
            "message": "Page speed metrics captured.",
            "details": results,
        }
    except Exception as e:
        return {
            "status": "info",
            "message": f"Page speed audit could not be completed: {e}",
            "details": {},
        }
