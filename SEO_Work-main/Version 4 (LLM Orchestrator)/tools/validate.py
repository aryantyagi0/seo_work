"""
VALIDATE Primitive: Check against patterns or standards
Enhanced with ssl_check, ga4_check, gsc_check, mixed_content_check,
interstitial_check, robots_txt_full_check for reliable deterministic auditing.
"""
import re
import json
import ssl
import socket
import asyncio
import aiohttp
import xml.etree.ElementTree as ET
from typing import Any, Dict
from datetime import datetime
from urllib.parse import urlparse, urljoin
from utils.logging_config import get_logger
from config.settings import USER_AGENT, BROKEN_LINK_LIMIT, LINK_CHECK_TIMEOUT

logger = get_logger("VALIDATE")


async def validate(data: Any, rule: str) -> Dict[str, Any]:
    """
    Validate data against a rule
    
    Args:
        data: Data to validate
        rule: "is_valid_json", "is_valid_xml", "is_https", "matches_pattern",
              "is_email", "is_valid_robots", "is_valid_sitemap", "is_not_empty",
              "contains_url", "ssl_check", "ga4_check", "gsc_check",
              "mixed_content_check", "interstitial_check", "robots_txt_full_check",
              "broken_links_check"
    
    Returns:
        {"valid": bool, "errors": List[str], ...extra details}
    """
    result = {"valid": False, "errors": []}
    
    try:
        # Extract content from FETCH dict if needed
        actual_data = data
        if isinstance(data, dict) and "content" in data:
            actual_data = data.get("content") or ""
        
        if rule == "is_valid_json":
            try:
                json.loads(str(actual_data))
                result["valid"] = True
            except json.JSONDecodeError as e:
                result["errors"].append(f"Invalid JSON: {e}")
        
        elif rule == "is_valid_xml":
            try:
                ET.fromstring(str(actual_data))
                result["valid"] = True
            except ET.ParseError as e:
                result["errors"].append(f"Invalid XML: {e}")
        
        elif rule == "is_https":
            result["valid"] = str(data).startswith("https://")
            if not result["valid"]:
                result["errors"].append("Not HTTPS")
        
        elif rule == "matches_pattern":
            if isinstance(data, dict):
                text = data.get("text", "")
                pattern = data.get("pattern", "")
                result["valid"] = bool(re.search(pattern, text))
        
        elif rule == "is_email":
            email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            result["valid"] = bool(re.match(email_pattern, str(data)))
        
        elif rule == "is_valid_robots":
            text = str(actual_data) if actual_data else ""
            if not text or not text.strip():
                result["errors"].append("Empty or missing robots.txt")
            else:
                has_user_agent = bool(re.search(r'User-agent:', text, re.IGNORECASE))
                has_allow_or_disallow = bool(re.search(r'(Allow|Disallow):', text, re.IGNORECASE))
                has_sitemap = bool(re.search(r'Sitemap:', text, re.IGNORECASE))
                
                if has_user_agent and has_allow_or_disallow:
                    result["valid"] = True
                    result["details"] = {
                        "has_user_agent": has_user_agent,
                        "has_allow_disallow": has_allow_or_disallow,
                        "has_sitemap_directive": has_sitemap,
                    }
                else:
                    if not has_user_agent:
                        result["errors"].append("Missing User-agent directive")
                    if not has_allow_or_disallow:
                        result["errors"].append("Missing Allow/Disallow directive")

        # Robots.txt full check: fetch, parse, and validate
        # Data must be a URL string
        elif rule == "robots_txt_full_check":
            url = str(data) if not isinstance(data, dict) else data.get("url", str(data))
            result = await _robots_txt_full_check(url)

        # SSL check: real SSL socket and redirect validation
        # Data must be a URL string
        elif rule == "ssl_check":
            url = str(data) if not isinstance(data, dict) else data.get("url", str(data))
            result = await _ssl_check(url)

        # GA4 check: scan HTML for tracking tags
        # Data must be HTML string or FETCH dict
        elif rule == "ga4_check":
            html = str(actual_data) if actual_data else ""
            result = _ga4_check(html)

        # GSC check: scan HTML for verification methods
        # Data must be HTML string or FETCH dict
        elif rule == "gsc_check":
            html = str(actual_data) if actual_data else ""
            result = _gsc_check(html)

        # Mixed content check: find insecure HTTP resources on HTTPS page
        # Data must be dict: {"url": "...", "html": "..."} or FETCH dict
        elif rule == "mixed_content_check":
            if isinstance(data, dict):
                url = data.get("url", "")
                html = data.get("content") or data.get("html") or ""
            else:
                url = ""
                html = str(data)
            result = _mixed_content_check(url, html)

        # Interstitial check: detect popups, modals, overlays
        # Data must be HTML string or FETCH dict
        elif rule == "interstitial_check":
            html = str(actual_data) if actual_data else ""
            result = _interstitial_check(html)

        # Broken links check: HEAD request all links, report broken ones
        # Data must be dict: {"url": "...", "html": "..."} or FETCH dict
        elif rule == "broken_links_check":
            if isinstance(data, dict):
                url = data.get("url", "")
                html = data.get("content") or data.get("html") or ""
            elif isinstance(data, str) and data.startswith("http"):
                url = data
                html = ""
            elif isinstance(data, str) and len(data) > 200:
                # Likely raw HTML passed as string
                url = ""
                html = data
            else:
                # Handle unexpected types (bool, slice, int, short string, etc.)
                logger.warning(f"broken_links_check received unexpected data: {type(data).__name__}")
                result["valid"] = False
                result["errors"].append(f"broken_links_check needs {{url, html}} dict; got {type(data).__name__}")
                result["details"] = {"reason": f"Invalid input type: {type(data).__name__}. Requires dict with url and html keys."}
                return result

            # If we have a URL but no HTML, fetch it
            if url and not html:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            url,
                            timeout=aiohttp.ClientTimeout(total=10),
                            ssl=False,
                            headers={"User-Agent": USER_AGENT},
                        ) as resp:
                            if resp.status == 200:
                                html = await resp.text()
                except Exception as e:
                    logger.warning(f"broken_links_check: could not fetch {url}: {e}")

            if not html:
                result["valid"] = True
                result["details"] = {"reason": "No HTML content available to check for broken links"}
                return result

            result = await _broken_links_check(url, html)

        # FAQ blog check: verify blog pages include FAQPage schema
        # Data must be dict: {"url": "...", "html": "..."}
        # Only runs on blog pages, skips homepage
        elif rule == "faq_blog_check":
            if isinstance(data, dict):
                url = data.get("url", "")
                html = data.get("content") or data.get("html") or ""
            else:
                url = ""
                html = str(data)
            result = _faq_blog_check(url, html)
        
        elif rule == "is_valid_sitemap":
            text = str(actual_data) if actual_data else ""
            if not text or not text.strip():
                result["errors"].append("Empty or missing sitemap")
            else:
                try:
                    ET.fromstring(text)
                    result["valid"] = True
                except ET.ParseError as e:
                    result["errors"].append(f"Invalid sitemap XML: {e}")

        # Sitemap full check: fetch and parse /sitemap.xml
        # Data must be URL string
        elif rule == "sitemap_full_check":
            url = str(data) if not isinstance(data, dict) else data.get("url", str(data))
            result = await _sitemap_full_check(url)
        
        elif rule == "is_not_empty":
            result["valid"] = bool(data and str(data).strip())
            if not result["valid"]:
                result["errors"].append("Data is empty or missing")
        
        elif rule == "contains_url":
            url_pattern = r'https?://[^\s<>"]+'
            result["valid"] = bool(re.search(url_pattern, str(data)))
            if not result["valid"]:
                result["errors"].append("No URL found in data")
        
        else:
            result["errors"].append(f"Unknown rule: {rule}")
    
    except Exception as e:
        result["errors"].append(str(e))
        logger.error(f"VALIDATE error: {e}")
    
    return result


# Robots.txt validation helper
async def _robots_txt_full_check(url: str) -> Dict[str, Any]:
    """Fetch, parse, and validate robots.txt file"""
    parsed = urlparse(url)
    home = f"{parsed.scheme}://{parsed.netloc}"
    robots_url = f"{home}/robots.txt"
    result = {"valid": False, "errors": []}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                robots_url,
                timeout=aiohttp.ClientTimeout(total=8),
                ssl=False,
                headers={"User-Agent": USER_AGENT},
            ) as resp:
                if resp.status != 200:
                    result["errors"].append(f"robots.txt returned HTTP {resp.status}")
                    return result
                content = await resp.text()
    except Exception as e:
        result["errors"].append(f"Could not fetch robots.txt: {e}")
        return result

    if not content or not content.strip():
        result["errors"].append("robots.txt is empty")
        return result

    # Parse
    disallow, allow, sitemaps = [], [], []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(":", 1)
        if len(parts) < 2:
            continue
        key, val = parts[0].strip().lower(), parts[1].strip()
        if key == "disallow":
            disallow.append(val)
        elif key == "allow":
            allow.append(val)
        elif key == "sitemap":
            sitemaps.append(val)

    has_ua = bool(re.search(r'User-agent:', content, re.IGNORECASE))
    has_rules = bool(disallow or allow)

    path = parsed.path or "/"
    is_blocked = any(path.startswith(r) for r in disallow if r)
    if is_blocked:
        is_blocked = not any(path.startswith(r) for r in allow if r)

    result["valid"] = has_ua and has_rules and not is_blocked
    result["details"] = {
        "has_user_agent": has_ua,
        "has_rules": has_rules,
        "disallow_rules": disallow,
        "allow_rules": allow,
        "sitemap_references": sitemaps,
        "is_blocked": is_blocked,
        "content_preview": content[:500],
    }
    if is_blocked:
        result["errors"].append("Current URL path is blocked by Disallow rule")
    return result


# Sitemap validation helper
async def _sitemap_full_check(url: str) -> Dict[str, Any]:
    """Fetch, parse, and validate sitemap.xml file"""
    import re as _re
    parsed = urlparse(url)
    home = f"{parsed.scheme}://{parsed.netloc}"
    sitemap_url = f"{home}/sitemap.xml"
    result = {"valid": False, "errors": [], "details": {}}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                sitemap_url,
                timeout=aiohttp.ClientTimeout(total=10),
                ssl=False,
                headers={"User-Agent": USER_AGENT},
            ) as resp:
                if resp.status != 200:
                    result["errors"].append(f"Sitemap returned HTTP {resp.status}")
                    result["details"] = {"sitemap_url": sitemap_url, "status_code": resp.status}
                    return result
                content = await resp.text()
    except Exception as e:
        result["errors"].append(f"Could not fetch sitemap: {e}")
        return result

    if not content or not content.strip():
        result["errors"].append("Sitemap is empty")
        return result

    # Parse XML to extract URLs from sitemap
    urls_found = []
    try:
        root = ET.fromstring(content)
        for elem in root.iter():
            local_name = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if local_name == "loc" and elem.text:
                urls_found.append(elem.text.strip())
    except ET.ParseError:
        # Fallback to regex for malformed XML
        loc_matches = _re.findall(r"<loc>\s*(https?://[^<]+)\s*</loc>", content, _re.IGNORECASE)
        urls_found = loc_matches

    # Check if current URL is included
    normalized_url = url.rstrip("/")
    contains_current = any(u.rstrip("/") == normalized_url for u in urls_found)

    result["valid"] = len(urls_found) > 0 and contains_current
    result["details"] = {
        "sitemap_url": sitemap_url,
        "url_count": len(urls_found),
        "contains_current_url": contains_current,
        "sample_urls": urls_found[:10],
    }
    if len(urls_found) == 0:
        result["errors"].append("Sitemap exists but contains 0 URLs")
    if not contains_current:
        result["errors"].append("Current URL not found in sitemap")

    return result


# SSL validation helper
async def _ssl_check(url: str) -> Dict[str, Any]:
    """Check SSL certificate validity and security configuration"""
    parsed = urlparse(url)
    hostname = parsed.netloc
    result = {"valid": False, "errors": []}

    if not hostname:
        result["errors"].append("Cannot determine hostname")
        return result

    audit = await asyncio.to_thread(_run_ssl_audit, hostname)
    result["valid"] = audit.get("value") == "Yes"
    result["details"] = audit
    if not result["valid"]:
        result["errors"].append(audit.get("reason", "SSL check failed"))
    return result


def _run_ssl_audit(hostname: str) -> Dict:
    """Perform SSL socket connection and audit"""
    try:
        # Check for HTTP to HTTPS redirect
        redirect_secure = False
        try:
            import requests as req_lib
            r = req_lib.head(f"http://{hostname}", allow_redirects=False, timeout=5)
            if r.status_code in (301, 302, 307, 308):
                loc = r.headers.get("Location", "")
                if loc.startswith("https://"):
                    redirect_secure = True
        except Exception:
            pass

        ctx = ssl.create_default_context()
        with socket.create_connection((hostname, 443), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                tls_ver = ssock.version()
                not_after = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
                san = [e[1] for e in cert.get("subjectAltName", []) if e[0] == "DNS"]
                days_left = (not_after - datetime.now()).days
                domain_match = hostname in san or any(
                    hostname.endswith(s[1:]) for s in san if s.startswith("*.")
                )

                if days_left < 0:
                    return {"value": "No", "reason": f"Expired {abs(days_left)} days ago"}
                if not domain_match:
                    return {"value": "No", "reason": "Domain name mismatch"}
                if not tls_ver.startswith(("TLSv1.2", "TLSv1.3")):
                    return {"value": "No", "reason": f"Legacy protocol: {tls_ver}"}

                return {
                    "value": "Yes",
                    "reason": "SSL configuration is optimal" if redirect_secure else "SSL valid, HTTP→HTTPS redirect may be missing",
                    "days_until_expiry": days_left,
                    "tls_version": tls_ver,
                    "redirect_secure": redirect_secure,
                }
    except Exception as e:
        return {"value": "No", "reason": f"Connection error: {e}"}


# GA4 tracking detection helper
def _detect_ga4_in_html(html: str) -> bool:
    """Check for GA4/GTM tracking tags in HTML"""
    if not html:
        return False
    hl = html.lower()
    if re.search(r"G-[A-Z0-9]{10}", html, re.IGNORECASE):
        return True
    if "googletagmanager.com/gtag/js" in hl:
        return True
    if re.search(r"gtag\s*\(", html, re.IGNORECASE):
        return True
    if re.search(r"GTM-[A-Z0-9]{7}", html, re.IGNORECASE):
        return True
    if "datalayer" in hl:
        return True
    return False


def _ga4_check(html: str) -> Dict[str, Any]:
    """Validate GA4/GTM tracking implementation"""
    result = {"valid": False, "errors": []}
    if not html:
        result["errors"].append("No HTML to scan")
        return result

    tags = []
    m = re.search(r"G-[A-Z0-9]{10}", html, re.IGNORECASE)
    if m:
        tags.append(m.group())
    m = re.search(r"GTM-[A-Z0-9]{7}", html, re.IGNORECASE)
    if m:
        tags.append(m.group())
    if "googletagmanager.com/gtag/js" in html.lower():
        tags.append("gtag.js")
    if re.search(r"gtag\s*\(", html, re.IGNORECASE):
        tags.append("gtag()")
    if "datalayer" in html.lower():
        tags.append("dataLayer")

    result["valid"] = bool(tags)
    result["details"] = {"tags_found": tags}
    if not tags:
        result["errors"].append("No GA4/GTM tracking detected")
    return result


# GSC verification detection helper
def _gsc_check(html: str) -> Dict[str, Any]:
    """Validate Google Search Console verification"""
    result = {"valid": False, "errors": []}
    if not html:
        result["errors"].append("No HTML to scan")
        return result

    methods = []
    if "google-site-verification" in html.lower():
        methods.append("meta-tag")
    if re.search(r"google[a-z0-9]{16}\.html", html.lower()):
        methods.append("html-file")
    if not methods and _detect_ga4_in_html(html):
        methods.append("inferred-from-ga4")

    result["valid"] = bool(methods)
    result["details"] = {"verification_methods": methods}
    if not methods:
        result["errors"].append("No GSC verification detected")
    return result


# Mixed content detection helper
def _mixed_content_check(url: str, html: str) -> Dict[str, Any]:
    """Detect insecure HTTP resources on HTTPS pages"""
    result = {"valid": False, "errors": []}

    if url and not url.startswith("https://"):
        result["valid"] = True  # Not applicable — not HTTPS
        result["details"] = {"reason": "Site not using HTTPS, mixed content N/A"}
        return result

    if not html:
        result["valid"] = True
        result["details"] = {"reason": "No HTML to check"}
        return result

    from bs4 import BeautifulSoup as BS4
    soup = BS4(html, "lxml")
    items = []
    # Map HTML tags to their resource attributes
    asset_map = {"img": "src", "script": "src", "link": "href",
                 "iframe": "src", "video": "src", "audio": "src", "source": "src"}
    for tag, attr in asset_map.items():
        for el in soup.find_all(tag):
            res = el.get(attr)
            if res:
                full = urljoin(url, res)
                if full.startswith("http://"):
                    items.append({"url": full, "type": tag})
    items = list({i["url"]: i for i in items}.values())

    if not items:
        result["valid"] = True
        result["details"] = {"reason": "No insecure assets found", "http_resources": 0}
    else:
        # Categorize resources as active (render-blocking) or passive
        active = [i for i in items if i["type"] in ("script", "link", "iframe")]
        passive = [i for i in items if i["type"] in ("img", "video", "audio", "source")]
        result["valid"] = False
        result["errors"].append(f"Found {len(items)} HTTP resources on HTTPS page")
        result["details"] = {
            "http_resources": len(items),
            "active_count": len(active),
            "passive_count": len(passive),
            "sample_urls": [i["url"] for i in items[:5]],
        }
    return result


# Interstitial detection helper
_INTERSTITIAL_KW = ["popup", "modal", "overlay", "interstitial",
                     "subscribe", "newsletter", "consent"]


def _interstitial_check(html: str) -> Dict[str, Any]:
    """Detect intrusive interstitials. Returns valid=True when no interstitials found."""
    result = {"valid": True, "errors": [], "details": {"interstitial_detected": "No"}}
    if not html:
        return result

    from bs4 import BeautifulSoup as BS4
    soup = BS4(html, "lxml")
    candidates = []
    for div in soup.find_all("div"):
        ident = ((div.get("id") or "") + " " + " ".join(div.get("class", []))).lower()
        if any(kw in ident for kw in _INTERSTITIAL_KW):
            candidates.append(div)

    if not candidates:
        return result  # No interstitials detected → valid=True

    for el in candidates:
        style = el.get("style", "").lower()
        # Check for fixed position overlays
        if "position:fixed" in style and "top:0" in style:
            if el.find("button") or el.find("a"):
                result["valid"] = True
                result["details"]["interstitial_detected"] = "Needs Improvement"
                return result
            result["valid"] = False
            result["details"]["interstitial_detected"] = "Yes"
            result["errors"].append("Intrusive interstitial detected")
            return result

    return result  # Candidates found but none match fixed position pattern → safe


# Broken links checking helper
async def _broken_links_check(url: str, html: str) -> Dict[str, Any]:
    """HEAD request all links and report broken ones. Skips social media domains."""
    result = {"valid": False, "errors": []}
    if not html:
        result["valid"] = True
        result["details"] = {"reason": "No HTML"}
        return result

    # List of domains that block automated requests
    SKIP_DOMAINS = {
        "twitter.com", "x.com", "facebook.com", "fb.com", "instagram.com",
        "linkedin.com", "tiktok.com", "pinterest.com", "youtube.com",
        "reddit.com", "tumblr.com", "snapchat.com", "wa.me", "whatsapp.com",
        "t.me", "telegram.org", "discord.com", "discord.gg",
        "play.google.com", "apps.apple.com", "itunes.apple.com",
        "maps.google.com", "goo.gl", "bit.ly",
    }

    from bs4 import BeautifulSoup as BS4
    soup = BS4(html, "lxml")
    hrefs = set()
    for a in soup.find_all("a", href=True):
        h = a["href"].strip()
        # Skip special URL schemes
        if h and not h.startswith(("#", "mailto:", "tel:", "javascript:")):
            # Skip Cloudflare email protection
            if "cdn-cgi/l/email-protection" not in h:
                hrefs.add(h)

    if not hrefs:
        result["valid"] = True
        result["details"] = {"total_links": 0, "broken_count": 0}
        return result

    # Filter out social media URLs that are known to block bots
    filtered_hrefs = []
    skipped_social = []
    for h in hrefs:
        full = h if h.startswith("http") else urljoin(url, h)
        try:
            domain = urlparse(full).netloc.lower().lstrip("www.")
        except Exception:
            domain = ""
        if domain in SKIP_DOMAINS:
            skipped_social.append(full)
        else:
            filtered_hrefs.append(h)

    to_check = filtered_hrefs[:BROKEN_LINK_LIMIT]  # Configurable link limit for performance
    broken = []

    async with aiohttp.ClientSession() as session:
        tasks = [_head_link(session, h, url) for h in to_check]
        results_list = await asyncio.gather(*tasks)
        for r in results_list:
            if r.get("broken"):
                broken.append(r)

    result["valid"] = len(broken) == 0
    result["details"] = {
        "total_links_on_page": len(hrefs),
        "total_checked": len(to_check),
        "skipped_social_media": len(skipped_social),
        "broken_count": len(broken),
        "broken_links": [b["url"] for b in broken[:10]],
        "summary": f"{len(broken)} broken out of {len(to_check)} checked" if broken else "All links working",
    }
    if broken:
        result["errors"].append(f"{len(broken)} broken links found")
    return result


async def _head_link(session, href, base_url):
    """Check if a link is broken by attempting HEAD or GET request."""
    try:
        full = href if href.startswith("http") else urljoin(base_url, href)
        
        # Try HEAD first for efficiency
        try:
            async with session.head(
                full, timeout=aiohttp.ClientTimeout(total=LINK_CHECK_TIMEOUT),
                allow_redirects=True, ssl=False,
                headers={"User-Agent": USER_AGENT},
            ) as r:
                return {"url": full, "status": r.status, "broken": r.status >= 400}
        except (aiohttp.ClientError, asyncio.TimeoutError):
            # HEAD failed, try GET (some servers block HEAD)
            async with session.get(
                full, timeout=aiohttp.ClientTimeout(total=LINK_CHECK_TIMEOUT),
                allow_redirects=True, ssl=False,
                headers={"User-Agent": USER_AGENT},
            ) as r:
                return {"url": full, "status": r.status, "broken": r.status >= 400}
    except Exception:
        # Mark as broken if both HEAD and GET fail
        return {"url": href, "status": 0, "broken": True}


# FAQ schema checking helper
def _faq_blog_check(url: str, html: str) -> Dict[str, Any]:
    """Check if blog pages include FAQPage schema. Only applies to blog pages."""
    result = {"valid": False, "errors": [], "details": {}}
    
    parsed = urlparse(url)
    path = parsed.path.lower()
    
    # Skip homepage
    if not path or path == "/" or path == "":
        result["valid"] = True  # N/A - not applicable
        result["details"] = {"reason": "Homepage - FAQ check not applicable"}
        return result
    
    # Check if page is in blog section
    blog_indicators = ["/blog", "/post", "/article", "/news", "/insights", "/resources"]
    is_blog = any(indicator in path for indicator in blog_indicators)
    
    if not is_blog:
        result["valid"] = True  # N/A - not a blog
        result["details"] = {"reason": "Not a blog page - FAQ check not applicable"}
        return result
    
    # It's a blog page - check for FAQPage schema
    if not html:
        result["errors"].append("No HTML to scan")
        return result
    
    # Look for FAQPage schema in HTML or JSON-LD
    has_faq_schema = False
    if "FAQPage" in html or "faqpage" in html.lower():
        has_faq_schema = True
    
    # Also check JSON-LD format
    import re
    json_ld_pattern = r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
    matches = re.findall(json_ld_pattern, html, re.DOTALL | re.IGNORECASE)
    for match in matches:
        if "FAQPage" in match:
            has_faq_schema = True
            break
    
    result["valid"] = has_faq_schema
    result["details"] = {
        "is_blog_page": True,
        "faq_schema_found": has_faq_schema
    }
    if not has_faq_schema:
        result["errors"].append("Blog page missing FAQPage schema")
    
    return result