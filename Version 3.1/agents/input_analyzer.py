from typing import List, Optional, Dict, Any, Tuple
import logging
import re
import os
import json
from urllib.parse import urlparse
from xml.etree import ElementTree
import sys

# Import the centralized fetcher
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from tools.fetch_tool import fetch_url_data
from tools.seo_parameters.site_hierarchy import map_internal_links

class InputAnalyzer:
    MAX_RECURSION_DEPTH = 3

    def __init__(self):
        # These will be removed as query intent is no longer handled here.
        # Keeping for reference during refactoring, but will be deleted later.
        self.parameter_key_map = {}
        self.comparable_params = []
        self._sitemap_cache: Dict[str, List[str]] = {}

    def extract_urls(self, user_query: str) -> List[str]:
        """
        Extracts all URLs from the user's query using a regex.
        """
        # Improved regex to handle various URL formats and delimiters
        url_pattern = r"https?://[^\s,;|\)\"']+"
        matches = re.findall(url_pattern, user_query)
        # Clean trailing punctuation and normalize
        urls = []
        for url in matches:
            u = url.rstrip(',.;:)]"\'')
            if u not in urls:
                urls.append(u)
        return urls
    
    def _get_homepage_url(self, url: str) -> str:
        """Extracts the base URL (scheme and domain) from a full URL."""
        try:
            parsed_url = urlparse(url)
            if not parsed_url.scheme or not parsed_url.netloc:
                return url # Return as is if already partial
            return f"{parsed_url.scheme}://{parsed_url.netloc}"
        except Exception:
            return url

    def _find_sitemap_in_robots(self, homepage_url: str) -> tuple[Optional[str], str]:
        """Finds the sitemap URL from the robots.txt file using SSL-safe fetcher."""
        if not homepage_url.startswith("http"):
            return None, "Invalid homepage URL for robots.txt check."
            
        robots_url = homepage_url.rstrip("/") + "/robots.txt"
        
        result = fetch_url_data(robots_url, method="GET", timeout=15)
        
        if result.get("status_code") == 200:
            content = result.get("text", "")
            sitemap_match = re.search(r"Sitemap:\s*(https?://[^\s]+)", content, re.IGNORECASE)
            if sitemap_match:
                msg = f"Sitemap found in robots.txt at {robots_url}."
                if result.get("ssl_fallback"):
                    msg += " (via insecure fallback)"
                return sitemap_match.group(1).strip(), msg
            return None, f"No sitemap directive found in robots.txt at {robots_url}."
        else:
            return None, f"Could not fetch or parse robots.txt at {robots_url}: {result.get('error')}"

    def _get_urls_from_sitemap(self, sitemap_url: str, collected_urls: Optional[set] = None, max_urls_to_collect: int = 100, current_depth: int = 0, messages: Optional[List[str]] = None) -> tuple[List[str], List[str]]:
        """
        Fetches and parses an XML sitemap recursively using SSL-safe fetcher.
        """
        if collected_urls is None:
            collected_urls = set()
        if messages is None:
            messages = []
        
        if current_depth > self.MAX_RECURSION_DEPTH:
            return list(collected_urls), messages

        # Normalize sitemap URL
        sitemap_url = sitemap_url.strip()
        result = fetch_url_data(sitemap_url, method="GET", timeout=15)
        
        if result.get("status_code") != 200:
            messages.append(f"Error fetching sitemap at {sitemap_url}: {result.get('error')}")
            return list(collected_urls), messages

        try:
            content = result.get("text", "")
            if not content:
                return list(collected_urls), messages
                
            # Remove encoding declaration if it's causing issues with fromstring
            content_bytes = content.encode('utf-8')
            root = ElementTree.fromstring(content_bytes)
            
            # Common namespaces
            sitemap_ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
            
            # Handle both with and without namespace
            tag = root.tag.lower()
            
            if 'sitemapindex' in tag:
                # It's an index, look for loc tags
                locs = root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
                if not locs: locs = root.findall(".//loc")
                
                for loc in locs:
                    if loc.text:
                        nested = loc.text.strip()
                        if len(collected_urls) < max_urls_to_collect:
                            self._get_urls_from_sitemap(nested, collected_urls, max_urls_to_collect, current_depth + 1, messages)
                        else:
                            break

            elif 'urlset' in tag:
                # It's a URL set
                locs = root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
                if not locs: locs = root.findall(".//loc")
                
                for loc in locs:
                    if loc.text:
                        u = loc.text.strip()
                        if u not in collected_urls:
                            collected_urls.add(u)
                        if len(collected_urls) >= max_urls_to_collect:
                            break
            
            return list(collected_urls), messages
        except Exception as e:
            messages.append(f"Error parsing sitemap at {sitemap_url}: {e}")
            return list(collected_urls), messages

    def _is_sitemap_url(self, url: str) -> bool:
        """Checks if a given URL is likely a sitemap URL."""
        u = url.lower()
        return u.endswith('.xml') or 'sitemap' in u

    def _get_internal_links_from_homepage(self, homepage_url: str, max_urls_to_collect: int = 100) -> tuple[List[str], str]:
        """
        Fetches homepage HTML and extracts internal links as fallback when sitemap is missing/insufficient.
        """
        if not homepage_url.startswith("http"):
            return [], "Invalid homepage URL for internal links fallback."

        result = fetch_url_data(homepage_url, method="GET", timeout=15)
        if result.get("status_code") != 200:
            return [], f"Could not fetch homepage for internal links fallback: {result.get('error')}"

        link_map_result = map_internal_links(result.get("text", ""), homepage_url)
        if link_map_result.get("status") != "success":
            return [], f"Internal links fallback failed: {link_map_result.get('message', 'Unknown error')}"

        links = []
        seen = set()
        for item in link_map_result.get("links", []):
            url = item.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            links.append(url)
            if len(links) >= max_urls_to_collect:
                break
        return links, f"Internal links fallback found {len(links)} URLs."

    def get_cached_sitemap_urls(self, url: str, max_urls_to_collect: int = 1000) -> tuple[List[str], str]:
        """
        Returns cached sitemap URLs for a base domain, or builds the cache once per domain.
        """
        homepage = self._get_homepage_url(url)
        if homepage in self._sitemap_cache:
            return self._sitemap_cache[homepage], f"Sitemap cache hit for {homepage}."

        sitemap_candidates = []
        sm_from_robots, robots_msg = self._find_sitemap_in_robots(homepage)
        if sm_from_robots:
            sitemap_candidates.append(sm_from_robots)

        # Common sitemap locations
        for suffix in ["/sitemap.xml", "/sitemap_index.xml"]:
            candidate = homepage.rstrip("/") + suffix
            if candidate not in sitemap_candidates:
                sitemap_candidates.append(candidate)

        collected_urls: set[str] = set()
        messages: List[str] = [robots_msg]

        for sm_url in sitemap_candidates:
            if len(collected_urls) >= max_urls_to_collect:
                break
            urls, sm_msgs = self._get_urls_from_sitemap(
                sm_url,
                collected_urls,
                max_urls_to_collect=max_urls_to_collect
            )
            collected_urls.update(urls)
            messages.extend(sm_msgs)

        final_urls = list(collected_urls)
        self._sitemap_cache[homepage] = final_urls
        return final_urls, f"Sitemap cache built for {homepage} with {len(final_urls)} URLs. {' | '.join([m for m in messages if m])}"

    def get_urls_to_audit(self, initial_urls: str | List[str], limit: int | None = 100) -> dict:
        """
        Orchestrates the process of finding and returning a list of URLs to audit.
        Supports multiple input URLs and prioritizes them.
        """
        if limit is None: limit = 100
        
        if isinstance(initial_urls, str):
            input_urls = [initial_urls]
        else:
            input_urls = initial_urls

        urls_to_audit_set = set() 
        final_urls = [] 
        
        # 1. Add all user-provided URLs first (STRICT PRIORITY)
        for url in input_urls:
            # Basic normalization (remove trailing slash for comparison)
            norm = url.rstrip("/")
            if norm not in [u.rstrip("/") for u in urls_to_audit_set]:
                urls_to_audit_set.add(url)
                final_urls.append(url)

        # 2. If we haven't reached the limit, try discovery
        if len(final_urls) < limit and input_urls:
            homepage = self._get_homepage_url(input_urls[0])
            sitemap_candidates = []
            
            # Find in robots.txt
            sm_from_robots, _ = self._find_sitemap_in_robots(homepage)
            if sm_from_robots:
                sitemap_candidates.append(sm_from_robots)
            
            # Input URL itself if it's a sitemap
            for url in input_urls:
                if self._is_sitemap_url(url) and url not in sitemap_candidates:
                    sitemap_candidates.append(url)

            # Process candidates
            for sm_url in sitemap_candidates:
                if len(final_urls) >= limit: break
                
                # Fetch up to the limit
                collected, _ = self._get_urls_from_sitemap(sm_url, urls_to_audit_set, limit)
                for u in collected:
                    if u not in final_urls:
                        final_urls.append(u)
                        if len(final_urls) >= limit: break

            # Fallback: if sitemap discovery is missing or insufficient, expand from homepage internal links.
            if len(final_urls) < limit:
                remaining = limit - len(final_urls)
                internal_urls, _ = self._get_internal_links_from_homepage(homepage, max_urls_to_collect=remaining)
                for u in internal_urls:
                    if u not in urls_to_audit_set:
                        urls_to_audit_set.add(u)
                    if u not in final_urls:
                        final_urls.append(u)
                        if len(final_urls) >= limit:
                            break

        return {
            "status": "success", 
            "reason": f"Collected {len(final_urls)} URLs.", 
            "urls": final_urls[:limit]
        }
        
    def analyze_input_for_llm(self, user_query: str) -> Dict[str, Any]:
        """
        Updated to support multiple URLs in query.
        """
        original_query = user_query.strip()
        extracted_urls = self.extract_urls(original_query)
        
        urls_to_audit_result = {"status": "failed", "reason": "No URL provided.", "urls": []}
        if extracted_urls:
            urls_to_audit_result = self.get_urls_to_audit(extracted_urls)
        
        return {
            "original_query": original_query,
            "extracted_urls": extracted_urls,
            "urls_to_audit": urls_to_audit_result["urls"],
            "url_discovery_status": urls_to_audit_result["status"],
            "url_discovery_reason": urls_to_audit_result["reason"]
        }
