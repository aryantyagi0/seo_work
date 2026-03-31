from urllib.parse import urljoin
import logging
import re
import requests # Import requests
import urllib3
import asyncio
from typing import Optional

# Suppress insecure request warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from langchain_core.tools import tool
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET # For more robust XML parsing

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

_SITEMAP_CACHE = {}

def _call_tool(tool_obj, **kwargs):
    if hasattr(tool_obj, "invoke"):
        return tool_obj.invoke(kwargs)
    return tool_obj(**kwargs)

@tool
async def analyze_xml_sitemap(base_url: str, robots_txt_content: str = "") -> dict:
    """
    Finds and analyzes the XML sitemap(s) for a given base URL, including recursive parsing of sitemap indexes.
    Attempts to find sitemaps from robots.txt content, then common locations.
    Extracts all unique URLs found within all discovered sitemaps.
    
    Args:
        base_url: The base URL of the website (e.g., "https://example.com").
        robots_txt_content: The content of the robots.txt file, if available. Defaults to empty string.
        
    Returns:
        A dictionary with analysis status, message, a list of discovered sitemap URLs,
        and a comprehensive list of unique URLs extracted from them.
    """
    cache_key = base_url
    if cache_key in _SITEMAP_CACHE:
        return _SITEMAP_CACHE[cache_key]

    initial_sitemap_candidates = set()
    
    # 1. Check robots.txt content if provided
    if robots_txt_content:
        for line in robots_txt_content.splitlines():
            match = re.search(r'Sitemap:\s*(.*)', line, re.IGNORECASE)
            if match:
                initial_sitemap_candidates.add(match.group(1).strip())

    # 2. Check common locations
    common_sitemap_paths = ["/sitemap.xml", "/sitemap_index.xml"] # Focus on main sitemaps first
    for sm_path in common_sitemap_paths:
        initial_sitemap_candidates.add(urljoin(base_url, sm_path))
    
    all_discovered_sitemaps = set()
    all_extracted_urls = set()
    visited_sitemaps = set() # To prevent infinite recursion
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    
    async def _fetch_and_parse_sitemap(sitemap_url: str):
        if sitemap_url in visited_sitemaps:
            return
        visited_sitemaps.add(sitemap_url)
        all_discovered_sitemaps.add(sitemap_url)

        logging.info(f"Fetching sitemap: {sitemap_url}")
        sitemap_content = None
        
        try:
            # First Attempt: Strict SSL
            response = await asyncio.to_thread(
                requests.get,
                sitemap_url,
                headers=headers,
                timeout=15,
                verify=True
            )
            response.raise_for_status()
            sitemap_content = response.text
        except (requests.exceptions.SSLError, requests.exceptions.RequestException):
            # Second Attempt: Insecure Fallback
            try:
                response = await asyncio.to_thread(
                    requests.get,
                    sitemap_url,
                    headers=headers,
                    timeout=15,
                    verify=False
                )
                response.raise_for_status()
                sitemap_content = response.text
            except requests.exceptions.RequestException as e:
                logging.warning(f"Could not fetch sitemap {sitemap_url} (even with fallback): {e}")
                return
        
        if not sitemap_content:
            logging.warning(f"Sitemap content is empty for {sitemap_url}")
            return

        try:
            # Use ElementTree for better XML handling, especially for large files
            root = ET.fromstring(sitemap_content.encode('utf-8')) # Encode to bytes
            
            # Check if it's a sitemap index or a URL set
            if "sitemapindex" in root.tag: # Sitemap index
                for sitemap_tag in root.findall('{http://www.sitemaps.org/schemas/sitemap/0.9}sitemap'):
                    loc = sitemap_tag.find('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')
                    if loc is not None and loc.text:
                        await _fetch_and_parse_sitemap(loc.text.strip()) # Recurse
            elif "urlset" in root.tag: # Regular sitemap with URLs
                for url_tag in root.findall('{http://www.sitemaps.org/schemas/sitemap/0.9}url'):
                    loc = url_tag.find('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')
                    if loc is not None and loc.text:
                        all_extracted_urls.add(loc.text.strip())
            else:
                logging.warning(f"Unknown XML format for sitemap {sitemap_url}. Tag: {root.tag}")
                
        except ET.ParseError as e:
            # Try with BeautifulSoup as a fallback for malformed XML
            try:
                soup = BeautifulSoup(sitemap_content, 'xml')
                if soup.find('sitemapindex'):
                    for loc in soup.find_all('loc'):
                        await _fetch_and_parse_sitemap(loc.text.strip())
                elif soup.find('urlset'):
                    for loc in soup.find_all('loc'):
                        all_extracted_urls.add(loc.text.strip())
            except Exception as bs_e:
                logging.error(f"Error parsing XML sitemap {sitemap_url} with both ElementTree and BeautifulSoup: {e}, {bs_e}")

        except Exception as e:
            logging.error(f"Unexpected error in _fetch_and_parse_sitemap for {sitemap_url}: {e}")


    for sitemap_candidate in list(initial_sitemap_candidates):
        await _fetch_and_parse_sitemap(sitemap_candidate)

    if all_extracted_urls:
        result = {
            "status": "success",
            "message": f"Found {len(all_extracted_urls)} unique URLs across {len(all_discovered_sitemaps)} sitemaps.",
            "sitemap_urls": list(all_discovered_sitemaps),
            "extracted_urls": list(all_extracted_urls)
        }
    else:
        result = {
            "status": "info",
            "message": "No XML sitemap found or no URLs extracted.",
            "sitemap_urls": list(all_discovered_sitemaps),
            "extracted_urls": []
        }

    _SITEMAP_CACHE[cache_key] = result
    return result

@tool
async def extract_urls_from_sitemap_tool(sitemap_analysis_result: dict) -> list[str]:
    """
    Extracts the list of URLs from the result of the analyze_xml_sitemap tool.
    
    Args:
        sitemap_analysis_result: The dictionary output from analyze_xml_sitemap.
        
    Returns:
        A list of URLs.
    """
    if sitemap_analysis_result and sitemap_analysis_result.get("status") == "success":
        return sitemap_analysis_result.get("extracted_urls", [])
    return []

