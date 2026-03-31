import asyncio
import json
import logging
import os
import shutil
import sys
import tempfile
from typing import Dict, Any

logger = logging.getLogger(__name__)

if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass


async def run_lighthouse(url: str, form_factor: str = "mobile") -> Dict[str, int | float | str]:
    if form_factor not in {"mobile", "desktop"}:
        raise ValueError("form_factor must be 'mobile' or 'desktop'")

    lh_profile_dir = os.path.join(tempfile.gettempdir(), f"lh_profile_{os.getpid()}")
    os.makedirs(lh_profile_dir, exist_ok=True)

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        output_path = tmp.name

    try:
        logger.info("Running Lighthouse for %s (%s)", url, form_factor)
        process = await asyncio.create_subprocess_exec(
            "npx.cmd",
            "--no-install",
            "lighthouse",
            url,
            "--quiet",
            "--no-enable-error-reporting",
            "--only-categories=performance",
            "--output=json",
            f"--output-path={output_path}",
            f"--form-factor={form_factor}",
            "--skip-audits=full-page-screenshot,screenshot-thumbnails,final-screenshot",
            f"--chrome-flags=--headless=new --disable-gpu --no-sandbox --disable-extensions --disable-dev-shm-usage --user-data-dir={lh_profile_dir}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)
        except asyncio.TimeoutError:
            logger.error("Lighthouse process timed out after 300 seconds.")
            process.kill()
            raise Exception("Lighthouse process timed out.")

        stderr_decoded = stderr.decode().strip()
        report_exists = os.path.exists(output_path) and os.path.getsize(output_path) > 0

        if process.returncode != 0 and not report_exists:
            logger.error("Lighthouse failed. Stderr: %s", stderr_decoded)
            raise Exception(f"Lighthouse failed: {stderr_decoded}")

        if not report_exists:
            raise Exception("Lighthouse did not produce a valid JSON report.")

        with open(output_path, "r", encoding="utf-8") as f:
            report = json.load(f)
    except Exception:
        logger.exception("Unexpected error in run_lighthouse")
        raise
    finally:
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass
        if os.path.exists(lh_profile_dir):
            shutil.rmtree(lh_profile_dir, ignore_errors=True)

    audits = report.get("audits", {})
    categories = report.get("categories", {})

    perf_score = categories.get("performance", {}).get("score")
    lcp_val = audits.get("largest-contentful-paint", {}).get("numericValue")
    cls_val = audits.get("cumulative-layout-shift", {}).get("numericValue")

    inp_val = None
    inp_audit = audits.get("interaction-to-next-paint")
    if inp_audit and inp_audit.get("numericValue") is not None:
        inp_val = inp_audit["numericValue"]

    if inp_val is None:
        tbt_audit = audits.get("total-blocking-time")
        if tbt_audit and tbt_audit.get("numericValue") is not None:
            inp_val = tbt_audit["numericValue"]

    return {
        "mobile_page_speed_performance": int(perf_score * 100) if perf_score is not None else "N/A",
        "lcp_score": round(lcp_val / 1000, 2) if isinstance(lcp_val, (int, float)) else "N/A",
        "cls_score": cls_val if cls_val is not None else "N/A",
        "fid_inp_score": int(inp_val) if isinstance(inp_val, (int, float)) else "N/A",
    }

    
    