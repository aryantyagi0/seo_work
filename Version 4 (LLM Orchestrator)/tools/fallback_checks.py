"""
Dedicated Deterministic Checks
These bypass the LLM Planner entirely for reliability and speed.
Each function returns: {"status": str, "raw_data": dict}
"""
import re
import ssl
import socket
import asyncio
import aiohttp
import collections
from typing import Dict, Any, List, Set
from datetime import datetime
from urllib.parse import urlparse, urljoin, parse_qs
from bs4 import BeautifulSoup

from utils.logging_config import get_logger
from config.settings import USER_AGENT, CRAWL_TIMEOUT, BROKEN_LINK_LIMIT, LINK_CHECK_TIMEOUT

logger = get_logger("DedicatedChecks")

# 1. ROBOTS.TXT

_domain_cache: Dict[str, Dict] = {}


async def check_robots_txt(url: str, html: str) -> Dict[str, Any]:
    """Check if robots.txt is properly configured (V3 logic)"""
    parsed = urlparse(url)
    home_url = f"{parsed.scheme}://{parsed.netloc}"

    if home_url not in _domain_cache:
        await _fetch_domain_data(home_url)

    domain_data = _domain_cache.get(home_url, {})
    robots_content = domain_data.get("robots_txt_content")

    if not robots_content:
        return {
            "status": "No",
            "raw_data": {"content": None, "reason": "robots.txt not found or empty"},
        }

    path = parsed.path or "/"
    disallow_rules = domain_data.get("disallow_rules", [])
    allow_rules = domain_data.get("allow_rules", [])
    sitemap_refs = domain_data.get("sitemap_references", [])

    is_disallowed = any(path.startswith(rule) for rule in disallow_rules if rule)
    if is_disallowed:
        is_disallowed = not any(path.startswith(rule) for rule in allow_rules if rule)

    status = "No" if is_disallowed else "Yes"

    return {
        "status": status,
        "raw_data": {
            "content_preview": robots_content[:500],
            "disallow_rules": disallow_rules,
            "allow_rules": allow_rules,
            "sitemap_references": sitemap_refs,
            "is_blocked": is_disallowed,
        },
    }


async def _fetch_domain_data(home_url: str):
    """Fetch robots.txt for a domain"""
    _domain_cache[home_url] = {
        "robots_txt_content": None,
        "disallow_rules": [],
        "allow_rules": [],
        "sitemap_references": [],
    }

    robots_url = urljoin(home_url, "/robots.txt")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                robots_url,
                timeout=aiohttp.ClientTimeout(total=8),
                ssl=False,
                headers={"User-Agent": USER_AGENT},
            ) as response:
                if response.status == 200:
                    content = await response.text()
                    _domain_cache[home_url]["robots_txt_content"] = content
                    _parse_robots_txt(home_url, content)
    except Exception as e:
        logger.warning(f"Could not fetch robots.txt for {home_url}: {e}")


def _parse_robots_txt(home_url: str, content: str):
    """Parse robots.txt content"""
    disallow_rules, allow_rules, sitemap_refs = [], [], []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(":", 1)
        if len(parts) < 2:
            continue
        key, value = parts[0].strip().lower(), parts[1].strip()
        if key == "disallow":
            disallow_rules.append(value)
        elif key == "allow":
            allow_rules.append(value)
        elif key == "sitemap":
            sitemap_refs.append(value)

    _domain_cache[home_url].update({
        "disallow_rules": disallow_rules,
        "allow_rules": allow_rules,
        "sitemap_references": sitemap_refs,
    })

# 2. LOGICAL SITE HIERARCHY

async def check_logical_hierarchy(url: str, html: str) -> Dict[str, Any]:
    """Check URL depth for logical site hierarchy (V3 logic)"""
    path = urlparse(url).path.strip("/")
    depth = 0 if not path else len(path.split("/"))

    if depth <= 2:
        status = "Yes"
    elif depth <= 4:
        status = "Needs Improvement"
    else:
        status = "No"

    return {
        "status": status,
        "raw_data": {"url_depth": depth, "url_path": path or "/"},
    }

# 3. NO INTRUSIVE INTERSTITIALS

INTERSTITIAL_KEYWORDS = [
    "popup", "modal", "overlay", "interstitial",
    "subscribe", "newsletter", "consent",
]


async def check_interstitials(url: str, html: str) -> Dict[str, Any]:
    """Detect intrusive interstitials (V3 logic)"""
    if not html:
        return {"status": "Yes", "raw_data": {"reason": "No HTML to check"}}

    soup = BeautifulSoup(html, "html.parser")
    interstitial_result = _detect_interstitial(soup)

    # Inversion: "No" interstitial found = "Yes" (good / pass)
    if interstitial_result in (None, "No", "no", "none", "unknown"):
        status = "Yes"
    else:
        status = "No"

    return {
        "status": status,
        "raw_data": {"interstitial_detected": interstitial_result},
    }


def _detect_interstitial(soup) -> str:
    """V3 interstitial detection logic"""
    candidates = []
    for div in soup.find_all("div"):
        identifier = (
            (div.get("id") or "") + " " + " ".join(div.get("class", []))
        ).lower()
        if any(kw in identifier for kw in INTERSTITIAL_KEYWORDS):
            candidates.append(div)

    if not candidates:
        return "No"

    for el in candidates:
        style = el.get("style", "").lower()
        if "position:fixed" in style and "top:0" in style:
            if el.find("button") or el.find("a"):
                return "Needs Improvement"
            return "Yes"

    return "No"

# 4. SSL CERTIFICATE ACTIVE

async def check_ssl_certificate(url: str, html: str) -> Dict[str, Any]:
    """Deterministic SSL certificate check (V3 logic)"""
    parsed = urlparse(url)
    hostname = parsed.netloc

    if not hostname:
        return {
            "status": "No",
            "raw_data": {"reason": "Hostname could not be determined"},
        }

    result = await asyncio.to_thread(_run_ssl_audit, hostname)

    return {
        "status": result.get("value", "No"),
        "raw_data": result,
    }


def _run_ssl_audit(hostname: str) -> Dict:
    """Deterministic SSL & redirect logic (from V3)"""
    try:
        # Redirect check
        redirect_secure = False
        try:
            import requests
            r = requests.head(f"http://{hostname}", allow_redirects=False, timeout=5)
            if r.status_code in [301, 302, 307, 308]:
                loc = r.headers.get("Location", "")
                if loc.startswith("https://"):
                    redirect_secure = True
        except Exception:
            redirect_secure = False

        # SSL certificate validation
        context = ssl.create_default_context()
        with socket.create_connection((hostname, 443), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                tls_version = ssock.version()
                expire_not_after = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
                san = [entry[1] for entry in cert.get("subjectAltName", []) if entry[0] == "DNS"]

                days_left = (expire_not_after - datetime.now()).days
                domain_match = hostname in san or any(
                    hostname.endswith(s[1:]) for s in san if s.startswith("*.")
                )

                if days_left < 0:
                    return {"value": "No", "reason": f"Expired {abs(days_left)} days ago"}
                if not domain_match:
                    return {"value": "No", "reason": "Domain name mismatch on certificate"}
                if not tls_version.startswith(("TLSv1.2", "TLSv1.3")):
                    return {"value": "No", "reason": f"Legacy protocol: {tls_version}"}
                if not redirect_secure:
                    return {
                        "value": "Yes",
                        "reason": "SSL valid but HTTP→HTTPS redirect may be missing",
                        "days_until_expiry": days_left,
                        "tls_version": tls_version,
                    }

                return {
                    "value": "Yes",
                    "reason": "SSL configuration is optimal",
                    "days_until_expiry": days_left,
                    "tls_version": tls_version,
                }

    except Exception as e:
        logger.error(f"SSL check failed for {hostname}: {e}")
        return {"value": "No", "reason": f"Connection error: {str(e)}"}

# 5. NO MIXED CONTENT WARNINGS

async def check_mixed_content(url: str, html: str) -> Dict[str, Any]:
    """Deterministic mixed content check (V3 logic)"""
    if not url.startswith("https://"):
        return {
            "status": "N/A",
            "raw_data": {"reason": "Site is not using HTTPS"},
        }

    if not html:
        return {
            "status": "Yes",
            "raw_data": {"reason": "No HTML to check"},
        }

    soup = BeautifulSoup(html, "html.parser")
    items = _extract_mixed_content(soup, url)

    if not items:
        return {
            "status": "Yes",
            "raw_data": {"reason": "No insecure assets found", "http_resources": 0},
        }

    active_types = {"script", "link", "iframe"}
    passive_types = {"img", "video", "audio", "source"}

    active_items = [i for i in items if i.get("type") in active_types]
    passive_items = [i for i in items if i.get("type") in passive_types]

    if active_items:
        reason = f"Found {len(active_items)} active mixed content (scripts/css/iframes using http://)"
    elif passive_items:
        reason = f"Found {len(passive_items)} passive mixed content (images/video using http://)"
    else:
        reason = f"Found {len(items)} insecure assets"

    return {
        "status": "No",
        "raw_data": {
            "reason": reason,
            "http_resources": len(items),
            "active_count": len(active_items),
            "passive_count": len(passive_items),
            "sample_urls": [i["url"] for i in items[:5]],
        },
    }


def _extract_mixed_content(soup, base_url: str) -> List[Dict]:
    """Extract http:// resources from HTTPS page"""
    logs = []
    asset_map = {
        "img": "src", "script": "src", "link": "href",
        "iframe": "src", "video": "src", "audio": "src", "source": "src",
    }
    for tag, attr in asset_map.items():
        for element in soup.find_all(tag):
            resource_url = element.get(attr)
            if resource_url:
                full_url = urljoin(base_url, resource_url)
                if full_url.startswith("http://"):
                    logs.append({"url": full_url, "type": tag})
    return list({item["url"]: item for item in logs}.values())

# 6. KEYWORD DENSITY

async def check_keyword_density(url: str, html: str) -> Dict[str, Any]:
    """Keyword density analysis (V3 logic with TF-IDF)"""
    if not html:
        return {
            "status": "No",
            "raw_data": {"reason": "No HTML to analyze"},
        }

    soup = BeautifulSoup(html, "html.parser")

    # Remove script/style tags for clean text
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    main_text = soup.get_text(separator=" ", strip=True)

    result = _analyze_keyword_density(main_text)

    return {
        "status": result.get("status", "No"),
        "raw_data": result,
    }


ENGLISH_STOPWORDS = set("""
a about above after again against all am an and any are aren't as at be because been before being below between both but by
can't cannot could couldn't did didn't do does doesn't doing don't down during each few for from further had hadn't has hasn't have haven't having he he'd he'll he's her here here's hers herself him himself his how how's i i'd i'll i'm i've if in into is isn't it it's its itself let's me more most mustn't my myself no nor not of off on once only or other ought our ours ourselves out over own same shan't she she'd she'll she's should shouldn't so some such than that that's the their theirs them themselves then there there's these they they'd they'll they're they've this those through to too under until up very was wasn't we we'd we'll we're we've were weren't what what's when when's where where's which while who who's whom why why's with won't would wouldn't you you'd you'll you're you've your yours yourself yourselves
""".split())


def _analyze_keyword_density(text: str) -> Dict:
    """TF-IDF based keyword density analysis (from V3)"""
    if not text or not text.strip():
        return {"status": "No", "offenders": []}

    content_text = text.lower()
    words = re.findall(r"\b[a-z]{3,}\b", content_text)
    total_words = len(words) if words else 1

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer

        vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 3))
        tfidf_matrix = vectorizer.fit_transform([content_text])
        feature_names = vectorizer.get_feature_names_out()

        if len(feature_names) == 0:
            return {"status": "No", "offenders": []}

        scores = tfidf_matrix.toarray()[0]
        ranked_idx = scores.argsort()[::-1]

        grouped = {1: [], 2: [], 3: []}
        seen = set()

        for idx in ranked_idx:
            fname = feature_names[idx]
            if fname in seen:
                continue
            if " " in fname:
                count = content_text.count(fname)
            else:
                count = sum(1 for w in words if w == fname)
            density = (count / total_words) * 100
            n = fname.count(" ") + 1
            if n > 3:
                continue
            # Collect top terms regardless of offender status for reporting
            if len(grouped[n]) < 5:
                grouped[n].append((fname, round(density, 2)))
                seen.add(fname)
            if all(len(grouped[g]) >= 5 for g in grouped):
                break

        # Determine offenders (density outside 0.5-5% range)
        any_issues = any(
            d < 0.5 or d > 5.0
            for grams in grouped.values()
            for _, d in grams
        )

        return {
            "status": "Yes" if not any_issues else "Needs Improvement",
            "total_words": total_words,
            "top_single_words": grouped[1],
            "top_bigrams": grouped[2],
            "top_trigrams": grouped[3],
            "offenders": {
                "1-gram": grouped[1],
                "2-gram": grouped[2],
                "3-gram": grouped[3],
            },
        }

    except ImportError:
        # Fallback: simple frequency-based analysis without sklearn
        freq = {}
        for word in words:
            if word not in ENGLISH_STOPWORDS and len(word) > 2:
                freq[word] = freq.get(word, 0) + 1

        sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:10]
        top_keywords = [
            (word, round((count / total_words) * 100, 2))
            for word, count in sorted_words
        ]

        return {
            "status": "Yes" if top_keywords else "No",
            "total_words": total_words,
            "top_single_words": top_keywords,
            "top_bigrams": [],
            "top_trigrams": [],
            "offenders": {"1-gram": top_keywords, "2-gram": [], "3-gram": []},
        }
    except Exception:
        return {"status": "No", "offenders": []}

# 7. BROKEN LINKS

async def check_broken_links(url: str, html: str) -> Dict[str, Any]:
    """Check for broken links (V3 logic). Skips social media URLs that block bots."""
    if not html:
        return {
            "status": "No",
            "raw_data": {"reason": "No HTML to check"},
        }

    # Social media / known-bot-blocking domains to skip
    SKIP_DOMAINS = {
        "twitter.com", "x.com", "facebook.com", "fb.com", "instagram.com",
        "linkedin.com", "tiktok.com", "pinterest.com", "youtube.com",
        "reddit.com", "tumblr.com", "snapchat.com", "wa.me", "whatsapp.com",
        "t.me", "telegram.org", "discord.com", "discord.gg",
        "play.google.com", "apps.apple.com", "itunes.apple.com",
        "maps.google.com", "goo.gl", "bit.ly",
    }

    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a_tag in soup.find_all("a", href=True):
        href = a_tag.get("href", "").strip()
        if href and not href.startswith(("#", "mailto:", "tel:", "javascript:")):
            if "cdn-cgi/l/email-protection" not in href:
                links.append(href)

    # Deduplicate
    links = list(set(links))

    if not links:
        return {
            "status": "Yes",
            "raw_data": {"reason": "No links found", "total_links": 0, "broken_count": 0},
        }

    # Filter out social media URLs
    filtered_links = []
    skipped_social = []
    for href in links:
        full_url = href if href.startswith("http") else urljoin(url, href)
        try:
            domain = urlparse(full_url).netloc.lower().lstrip("www.")
        except Exception:
            domain = ""
        if domain in SKIP_DOMAINS:
            skipped_social.append(full_url)
        else:
            filtered_links.append(href)

    # Limit links to check for performance
    links_to_check = filtered_links[:BROKEN_LINK_LIMIT]
    broken = []

    async with aiohttp.ClientSession() as session:
        tasks = [_check_single_link(session, href, url) for href in links_to_check]
        results = await asyncio.gather(*tasks)
        for r in results:
            if r.get("broken"):
                broken.append(r)

    broken_count = len(broken)
    total = len(links_to_check)

    return {
        "status": "Yes" if broken_count == 0 else "No",
        "raw_data": {
            "total_links_checked": total,
            "total_links_on_page": len(links),
            "skipped_social_media": len(skipped_social),
            "broken_count": broken_count,
            "broken_links": [b["url"] for b in broken[:10]],
            "summary": f"{broken_count} broken out of {total} checked" if broken_count else "All links working",
        },
    }


async def _check_single_link(session: aiohttp.ClientSession, href: str, base_url: str) -> Dict:
    """Check a single link"""
    try:
        full_url = href if href.startswith("http") else urljoin(base_url, href)
        async with session.head(
            full_url,
            timeout=aiohttp.ClientTimeout(total=LINK_CHECK_TIMEOUT),
            allow_redirects=True,
            ssl=False,
            headers={"User-Agent": USER_AGENT},
        ) as r:
            return {
                "url": full_url,
                "status": r.status,
                "broken": r.status >= 400,
            }
    except Exception:
        return {"url": href, "status": 0, "broken": True}

# 8. GOOGLE ANALYTICS / GA4 SETUP

def _detect_ga4_in_html(html: str) -> bool:
    """Shared GA4 detection logic (V3)"""
    if not html:
        return False
    html_lower = html.lower()
    if re.search(r"G-[A-Z0-9]{10}", html, re.IGNORECASE):
        return True
    if "googletagmanager.com/gtag/js" in html_lower:
        return True
    if re.search(r"gtag\s*\(", html, re.IGNORECASE):
        return True
    if re.search(r"GTM-[A-Z0-9]{7}", html, re.IGNORECASE):
        return True
    if "datalayer" in html_lower:
        return True
    return False


async def check_ga4_setup(url: str, html: str) -> Dict[str, Any]:
    """Detect GA4/GTM tracking codes (V3 logic)"""
    if not html:
        return {"status": "No", "raw_data": {"reason": "No HTML"}}

    tags_found = []

    g_match = re.search(r"G-[A-Z0-9]{10}", html, re.IGNORECASE)
    if g_match:
        tags_found.append(g_match.group())

    gtm_match = re.search(r"GTM-[A-Z0-9]{7}", html, re.IGNORECASE)
    if gtm_match:
        tags_found.append(gtm_match.group())

    if "googletagmanager.com/gtag/js" in html.lower():
        tags_found.append("gtag.js")

    if re.search(r"gtag\s*\(", html, re.IGNORECASE):
        tags_found.append("gtag()")

    if "datalayer" in html.lower():
        tags_found.append("dataLayer")

    status = "Yes" if tags_found else "No"

    return {
        "status": status,
        "raw_data": {"tags_found": tags_found},
    }

# 9. GOOGLE SEARCH CONSOLE SETUP

async def check_gsc_setup(url: str, html: str) -> Dict[str, Any]:
    """Check GSC verification (V3 logic with GA4 inference)"""
    if not html:
        return {"status": "No", "raw_data": {"reason": "No HTML"}}

    verification_methods = []

    # Meta tag verification
    if "google-site-verification" in html.lower():
        verification_methods.append("meta-tag")

    # HTML file verification pattern
    if re.search(r"google[a-z0-9]{16}\.html", html.lower()):
        verification_methods.append("html-file")

    # Business override: if GA4 detected, infer GSC is configured
    if not verification_methods and _detect_ga4_in_html(html):
        verification_methods.append("inferred-from-ga4")
        logger.info("[GSC] GA4 detected in HTML → inferring GSC is configured")

    status = "Yes" if verification_methods else "No"

    return {
        "status": status,
        "raw_data": {"verification_methods": verification_methods},
    }

# 9. INTERNAL LINKING OPTIMIZATION

async def check_internal_linking(url: str, html: str) -> Dict[str, Any]:
    """Count internal links on the page (V3 logic)"""
    if not html:
        return {"status": "0", "raw_data": {"internal_link_count": 0, "links": []}}
    
    soup = BeautifulSoup(html, "html.parser")
    domain = urlparse(url).netloc
    links = []
    
    for a in soup.find_all("a", href=True):
        full_url = urljoin(url, a["href"])
        if urlparse(full_url).netloc == domain:
            links.append(full_url)
        if len(links) >= 100:
            break
    
    count = len(links)
    return {
        "status": str(count),
        "raw_data": {"internal_link_count": count, "links": links[:20]},
    }

# 10. XML SITEMAP CHECK

async def check_xml_sitemap(url: str, html: str) -> Dict[str, Any]:
    """Fetch and validate XML sitemap, count URLs, check if current URL is included."""
    import xml.etree.ElementTree as ET
    
    parsed = urlparse(url)
    home_url = f"{parsed.scheme}://{parsed.netloc}"
    sitemap_url = f"{home_url}/sitemap.xml"
    
    result_data = {
        "sitemap_url": sitemap_url,
        "sitemap_found": False,
        "is_valid_xml": False,
        "url_count": 0,
        "contains_current_url": False,
        "sample_urls": [],
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                sitemap_url,
                timeout=aiohttp.ClientTimeout(total=10),
                ssl=False,
                headers={"User-Agent": USER_AGENT},
            ) as resp:
                if resp.status != 200:
                    return {
                        "status": "No",
                        "raw_data": {**result_data, "reason": f"Sitemap returned HTTP {resp.status}"},
                    }
                content = await resp.text()
    except Exception as e:
        return {
            "status": "No",
            "raw_data": {**result_data, "reason": f"Could not fetch sitemap: {e}"},
        }

    if not content or not content.strip():
        return {
            "status": "No",
            "raw_data": {**result_data, "reason": "Sitemap is empty"},
        }

    result_data["sitemap_found"] = True

    # Parse XML and extract URLs
    urls_found = []
    try:
        root = ET.fromstring(content)
        result_data["is_valid_xml"] = True
        
        # Handle namespace
        for elem in root.iter():
            local_name = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if local_name == "loc" and elem.text:
                urls_found.append(elem.text.strip())
    except ET.ParseError:
        # Try regex fallback for malformed XML
        loc_pattern = r"<loc>\s*(https?://[^<]+)\s*</loc>"
        urls_found = re.findall(loc_pattern, content, re.IGNORECASE)

    result_data["url_count"] = len(urls_found)
    result_data["sample_urls"] = urls_found[:10]

    # Check if current URL is in the sitemap
    normalized_url = url.rstrip("/")
    for sitemap_entry in urls_found:
        if sitemap_entry.rstrip("/") == normalized_url:
            result_data["contains_current_url"] = True
            break

    if len(urls_found) == 0:
        status = "No"
        result_data["reason"] = "Sitemap exists but contains 0 URLs"
    elif not result_data["contains_current_url"]:
        status = "Needs Improvement"
        result_data["reason"] = f"Sitemap has {len(urls_found)} URLs but does not include current URL"
    else:
        status = "Yes"
        result_data["reason"] = f"Sitemap found with {len(urls_found)} URLs, current URL included"

    return {"status": status, "raw_data": result_data}

# 11. THIN CONTENT AUDIT

async def check_thin_content(url: str, html: str) -> Dict[str, Any]:
    """Thin content check — counts words in page body (sans boilerplate).
    V3-proven logic: strip header/footer/nav/aside/script/style from body,
    then count real alphabetic words.
    Uses body-level extraction (not small containers) to avoid false positives.
    """
    THIN_THRESHOLD = 200  # minimum words for non-thin content

    if not html:
        return {
            "status": "No",
            "raw_data": {"reason": "No HTML to analyze", "word_count": 0},
        }

    soup = BeautifulSoup(html, "html.parser")

    # Strategy: try LARGE containers first (body fallback), then specific.
    # This avoids picking a small .content div with 79 words when body has 800.
    best_text = ""
    best_word_count = 0

    # 1. Try specific content containers
    for selector in ["main", "article", "[role='main']",
                      "#main-content", ".main-content", ".page-content", ".site-content",
                      ".post-content", ".entry-content", "#content", ".content"]:
        el = soup.select_one(selector)
        if el:
            clone = BeautifulSoup(str(el), "html.parser")
            for tag in clone(["script", "style", "noscript", "svg", "path", "meta", "link",
                              "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = clone.get_text(separator=" ", strip=True)
            wc = len(re.findall(r"\b[a-zA-Z]{2,}\b", text))
            if wc > best_word_count:
                best_text = text
                best_word_count = wc

    # 2. Also try cleaned body (often has MORE words than a small container)
    body_soup = BeautifulSoup(html, "html.parser")
    body = body_soup.find("body") or body_soup
    for tag in body(["header", "footer", "nav", "aside", "script", "style", "noscript",
                     "svg", "path", "meta", "link"]):
        tag.decompose()
    body_text = body.get_text(separator=" ", strip=True)
    body_wc = len(re.findall(r"\b[a-zA-Z]{2,}\b", body_text))

    # Use whichever is larger
    if body_wc > best_word_count:
        main_text = body_text
    else:
        main_text = best_text
    
    # Clean and count words (only actual words, not single chars or numbers)
    words = re.findall(r"\b[a-zA-Z]{2,}\b", main_text)
    word_count = len(words)

    if word_count >= THIN_THRESHOLD:
        status = "Yes"
        reason = (
            f"The page contains approximately {word_count} words, comfortably above the "
            f"{THIN_THRESHOLD}-word threshold, so it is not considered thin."
        )
    elif word_count >= 100:
        status = "Needs Improvement"
        reason = (
            f"The page contains approximately {word_count} words, which is below the "
            f"{THIN_THRESHOLD}-word threshold. Consider adding more substantive content."
        )
    else:
        status = "No"
        reason = (
            f"The page contains only approximately {word_count} words, significantly below "
            f"the {THIN_THRESHOLD}-word threshold. This is considered thin content."
        )

    return {
        "status": status,
        "raw_data": {
            "word_count": word_count,
            "threshold": THIN_THRESHOLD,
            "is_thin": word_count < THIN_THRESHOLD,
            "reason": reason,
        },
    }

# 12. EEAT CHECK (Blog pages only)

async def check_eeat(url: str, html: str) -> Dict[str, Any]:
    """
    EEAT check: Only applies to blog/article pages.
    For non-blog pages, returns N/A.
    """
    parsed = urlparse(url)
    path = parsed.path.lower().rstrip("/")

    # EEAT is only applicable to blog/article pages
    blog_indicators = ["/blog", "/post", "/article", "/news", "/insights", "/resources", "/guides", "/learn"]
    is_blog = any(indicator in path for indicator in blog_indicators)

    if not is_blog:
        return {
            "status": "N/A",
            "raw_data": {
                "reason": "EEAT is only applicable to blog/article pages. This page is not a blog.",
                "is_blog_page": False,
                "url_path": path or "/",
            },
        }

    if not html:
        return {
            "status": "No",
            "raw_data": {"reason": "No HTML to analyze for EEAT signals", "is_blog_page": True},
        }

    soup = BeautifulSoup(html, "html.parser")
    signals = {
        "author_found": False,
        "author_name": None,
        "author_bio_found": False,
        "date_found": False,
        "credentials_found": False,
        "sources_cited": False,
        "schema_person_found": False,
    }

    # Check for author information
    author_selectors = [
        "[rel='author']", ".author", ".byline", "[class*='author']",
        "[itemprop='author']", "a[href*='/author/']",
    ]
    for sel in author_selectors:
        el = soup.select_one(sel)
        if el:
            signals["author_found"] = True
            signals["author_name"] = el.get_text(strip=True)[:100]
            break

    # Check for author bio/credentials
    bio_selectors = [".author-bio", ".author-description", "[class*='bio']", "[class*='credential']"]
    for sel in bio_selectors:
        if soup.select_one(sel):
            signals["author_bio_found"] = True
            signals["credentials_found"] = True
            break

    # Check for publication date
    date_selectors = ["time[datetime]", "[class*='date']", "[itemprop='datePublished']", "[class*='publish']"]
    for sel in date_selectors:
        if soup.select_one(sel):
            signals["date_found"] = True
            break

    # Check for cited sources
    external_links = 0
    domain = parsed.netloc
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if href.startswith("http") and domain not in href:
            external_links += 1
    signals["sources_cited"] = external_links > 2

    # Check for Person schema
    html_lower = html.lower()
    if '"@type"' in html_lower and '"person"' in html_lower:
        signals["schema_person_found"] = True

    # Score EEAT
    score = sum([
        signals["author_found"],
        signals["author_bio_found"],
        signals["date_found"],
        signals["credentials_found"],
        signals["sources_cited"],
        signals["schema_person_found"],
    ])

    if score >= 4:
        status = "Yes"
    elif score >= 2:
        status = "Needs Improvement"
    else:
        status = "No"

    signals["eeat_score"] = f"{score}/6"
    signals["is_blog_page"] = True

    return {"status": status, "raw_data": signals}

# 13. CANONICAL TAGS CHECK

async def check_canonical_tags(url: str, html: str) -> Dict[str, Any]:
    """Check for proper canonical tag implementation."""
    if not html:
        return {"status": "No", "raw_data": {"reason": "No HTML to check"}}

    soup = BeautifulSoup(html, "html.parser")
    canonical = soup.find("link", {"rel": "canonical"})

    if not canonical:
        return {
            "status": "No",
            "raw_data": {"canonical_found": False, "reason": "No canonical tag found"},
        }

    canonical_href = canonical.get("href", "").strip()
    normalized_url = url.rstrip("/")
    normalized_canonical = canonical_href.rstrip("/")
    is_self_referencing = normalized_url == normalized_canonical

    return {
        "status": "Yes" if is_self_referencing else "Needs Improvement",
        "raw_data": {
            "canonical_found": True,
            "canonical_url": canonical_href,
            "is_self_referencing": is_self_referencing,
            "reason": "Self-referencing canonical tag found" if is_self_referencing
                      else f"Canonical points to {canonical_href} (not self-referencing)",
        },
    }

# 14. 404 ERRORS CHECK

async def check_404_errors(url: str, html: str) -> Dict[str, Any]:
    """Check if the page itself is a 404 error."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=8),
                ssl=False,
                headers={"User-Agent": USER_AGENT},
                allow_redirects=True,
            ) as resp:
                is_404 = resp.status == 404
                return {
                    "status": "No" if is_404 else "Yes",
                    "raw_data": {
                        "status_code": resp.status,
                        "is_404": is_404,
                        "reason": f"Page returned HTTP {resp.status}" if is_404
                                  else f"Page returned HTTP {resp.status} (not a 404)",
                    },
                }
    except Exception as e:
        return {
            "status": "No",
            "raw_data": {"reason": f"Error checking page: {e}"},
        }

# 15. BREADCRUMB NAVIGATION CHECK

async def check_breadcrumb(url: str, html: str) -> Dict[str, Any]:
    """
    Detect breadcrumb navigation via HTML nav elements, CSS classes,
    ARIA attributes, microdata, and JSON-LD BreadcrumbList schema.
    """
    if not html:
        return {"status": "No", "raw_data": {"reason": "No HTML to analyze"}}

    soup = BeautifulSoup(html, "html.parser")
    signals = {
        "html_breadcrumb_found": False,
        "schema_breadcrumb_found": False,
        "breadcrumb_items": [],
        "detection_method": None,
    }

    # 1. HTML / CSS / ARIA detection
    breadcrumb_selectors = [
        # ARIA
        "nav[aria-label*='breadcrumb' i]",
        "nav[aria-label*='Breadcrumb' i]",
        "ol[aria-label*='breadcrumb' i]",
        # Class names
        "nav.breadcrumb", "nav.breadcrumbs",
        ".breadcrumb", ".breadcrumbs",
        ".breadcrumb-nav", ".breadcrumb-list",
        "[class*='breadcrumb']",
        # Microdata
        "[itemtype*='BreadcrumbList']",
        # Common Wordpress / theme patterns
        "#breadcrumbs", "#breadcrumb",
        ".woocommerce-breadcrumb",
        ".yoast-breadcrumb",
        ".rank-math-breadcrumb",
    ]
    for sel in breadcrumb_selectors:
        try:
            el = soup.select_one(sel)
            if el:
                signals["html_breadcrumb_found"] = True
                signals["detection_method"] = f"CSS selector: {sel}"
                # Extract breadcrumb items text
                items = [a.get_text(strip=True) for a in el.find_all("a")]
                if not items:
                    items = [li.get_text(strip=True) for li in el.find_all("li")]
                if not items:
                    items = [el.get_text(separator=" > ", strip=True)]
                signals["breadcrumb_items"] = items[:10]
                break
        except Exception:
            continue

    # 2. JSON-LD BreadcrumbList schema
    json_ld_scripts = soup.find_all("script", {"type": "application/ld+json"})
    for script in json_ld_scripts:
        try:
            import json as _json
            data = _json.loads(script.string or "")
            # Handle single object or @graph array
            items_to_check = [data]
            if isinstance(data, list):
                items_to_check = data
            elif isinstance(data, dict) and "@graph" in data:
                items_to_check = data["@graph"]

            for item in items_to_check:
                if isinstance(item, dict):
                    schema_type = item.get("@type", "")
                    if schema_type == "BreadcrumbList" or (
                        isinstance(schema_type, list) and "BreadcrumbList" in schema_type
                    ):
                        signals["schema_breadcrumb_found"] = True
                        # Extract items from itemListElement
                        list_items = item.get("itemListElement", [])
                        names = [
                            li.get("name") or li.get("item", {}).get("name", "")
                            for li in list_items
                            if isinstance(li, dict)
                        ]
                        signals["breadcrumb_items"] = names[:10] if names else signals["breadcrumb_items"]
                        signals["detection_method"] = signals.get("detection_method") or "JSON-LD BreadcrumbList"
                        break
        except Exception:
            continue

    # 3. Fallback: look for '>' or '/' separated text in known breadcrumb-like elements
    if not signals["html_breadcrumb_found"] and not signals["schema_breadcrumb_found"]:
        # Check for inline breadcrumb text patterns like "Home > Services > Web Dev"
        for nav in soup.find_all("nav"):
            text = nav.get_text(separator=" ", strip=True)
            if text.count(" > ") >= 1 or text.count(" / ") >= 1 or text.count(" » ") >= 1:
                signals["html_breadcrumb_found"] = True
                signals["detection_method"] = "nav element with separator pattern"
                signals["breadcrumb_items"] = [t.strip() for t in re.split(r'\s*[>/»]\s*', text) if t.strip()][:10]
                break

    found = signals["html_breadcrumb_found"] or signals["schema_breadcrumb_found"]

    # V3 logic: homepage (path_depth == 0) → breadcrumb not required → "Yes"
    parsed_url = urlparse(url)
    path_depth = parsed_url.path.strip("/").count("/") + 1 if parsed_url.path.strip("/") else 0
    is_homepage = path_depth == 0
    signals["is_homepage"] = is_homepage
    signals["path_depth"] = path_depth

    if found:
        status = "Yes"
        signals["reason"] = (
            f"Breadcrumb navigation detected via {signals['detection_method']}. "
            f"Items: {', '.join(signals['breadcrumb_items'][:5])}"
        )
    elif is_homepage:
        status = "Yes"
        signals["reason"] = (
            "Homepage (root path) — breadcrumb navigation is not required. "
            "Breadcrumbs are primarily useful for deeper pages."
        )
    else:
        status = "No"
        signals["reason"] = "No breadcrumb navigation found in HTML structure or JSON-LD schema."

    return {"status": status, "raw_data": signals}

# 16. DUPLICATE CONTENT CHECK — handled POST-CRAWL (see postcrawl_duplicates.py)

# Global in-memory corpus for cross-URL duplicate detection (legacy, kept for SEARCH primitive)
_page_corpus: Dict[str, Dict[str, str]] = {}


def _extract_main_text(soup) -> str:
    """Extract main content text — tries ALL containers + body, keeps highest word count."""
    import copy
    best_text = ""
    best_wc = 0

    for selector in ["main", "article", "[role='main']", "#content", ".content",
                      "#main-content", ".main-content", ".post-content", ".entry-content"]:
        el = soup.select_one(selector)
        if el:
            el_copy = copy.copy(el)
            for tag in el_copy(["script", "style", "noscript", "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = el_copy.get_text(separator=" ", strip=True)
            wc = len(text.split())
            if wc > best_wc:
                best_wc = wc
                best_text = text

    # Always also try body minus boilerplate
    body = soup.find("body")
    if body:
        body_copy = copy.copy(body)
        for tag in body_copy(["header", "footer", "nav", "aside", "script", "style", "noscript"]):
            tag.decompose()
        body_text = body_copy.get_text(separator=" ", strip=True)
        body_wc = len(body_text.split())
        if body_wc > best_wc:
            best_wc = body_wc
            best_text = body_text

    return best_text or soup.get_text(separator=" ", strip=True)


def store_page_in_corpus(url: str, html: str):
    """Store page data in the global corpus for the SEARCH primitive."""
    if not html:
        return
    soup = BeautifulSoup(html, "html.parser")

    title_el = soup.find("title")
    title = title_el.get_text(strip=True) if title_el else ""

    desc_el = soup.find("meta", attrs={"name": "description"})
    description = desc_el.get("content", "") if desc_el else ""

    main_text = _extract_main_text(BeautifulSoup(html, "html.parser"))

    images = soup.find_all("img", alt=True)
    alt_texts = " | ".join(img.get("alt", "").strip() for img in images if img.get("alt", "").strip())

    _page_corpus[url] = {
        "meta_title": title,
        "meta_description": description,
        "main_content": main_text[:5000],
        "image_alt": alt_texts[:2000],
    }


async def check_duplicate_content(url: str, html: str) -> Dict[str, Any]:
    """Duplicate content — handled POST-CRAWL by postcrawl_duplicates.py.
    This returns a placeholder. Actual results are written after all URLs are processed.
    """
    return {
        "status": "Pending post-crawl check",
        "raw_data": {
            "reason": "Duplicate detection runs post-crawl via TF-IDF + FAISS across all URLs."
        },
    }

# 16b. META DESCRIPTION

async def check_meta_description(url: str, html: str) -> Dict[str, Any]:
    """Check meta description presence and length (<= 160 characters)."""
    if not html:
        return {
            "status": "No",
            "raw_data": {"reason": "No HTML to analyze", "description": "", "length": 0, "within_limit": False},
        }

    soup = BeautifulSoup(html, "html.parser")
    desc_el = soup.find("meta", attrs={"name": "description"})
    description = desc_el.get("content", "").strip() if desc_el else ""
    length = len(description)
    within_limit = bool(description) and length <= 160

    if not description:
        reason = "Missing meta description"
    elif length > 160:
        reason = "Meta description exceeds 160 characters"
    else:
        reason = "Meta description within 160-character limit"

    return {
        "status": "Yes" if within_limit else "No",
        "raw_data": {
            "description": description,
            "length": length,
            "within_limit": within_limit,
            "reason": reason,
        },
    }

# 16c. AVOID CRAWL TRAPS

async def check_avoid_crawl_traps(url: str, html: str) -> Dict[str, Any]:
    """Detect common crawl trap signals: faceted params, infinite scroll, and calendar-style URLs."""
    indicators = []
    score = 0

    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    param_keys = [k.lower() for k in params.keys()]

    if params:
        indicators.append(f"Query parameters present: {', '.join(param_keys[:8])}")
        score += min(40, 5 * len(param_keys))

    trap_param_prefixes = ("utm_", "gclid", "fbclid", "session", "sid", "ref", "sort", "filter", "facet")
    trap_params = [k for k in param_keys if any(k.startswith(p) for p in trap_param_prefixes)]
    if trap_params:
        indicators.append(f"Potential trap parameters: {', '.join(trap_params[:8])}")
        score += 20

    path = parsed.path.lower()
    if re.search(r"/page/\\d+/?", path):
        indicators.append("Pagination path pattern detected (/page/\\d+)")
        score += 15
    if re.search(r"/\\d{4}/\\d{2}/", path):
        indicators.append("Calendar-style path detected (/YYYY/MM/)")
        score += 15

    if html:
        soup = BeautifulSoup(html, "html.parser")
        if soup.select_one("[class*='infinite-scroll'], [data-infinite-scroll], [id*='infinite-scroll']"):
            indicators.append("Infinite scroll markup detected")
            score += 30
        if soup.select_one("[class*='facet'], [class*='filter'], [class*='pagination'], [rel='next'], [rel='prev']"):
            indicators.append("Faceted navigation or pagination detected")
            score += 10

    risk_score = min(100, score)
    status = "Yes" if risk_score < 40 else "No"

    return {
        "status": status,
        "raw_data": {
            "risk_score": risk_score,
            "indicators": indicators,
            "param_count": len(param_keys),
            "path": parsed.path,
        },
    }

# 17. HEADING TAGS (H1/H2/H3)

async def check_heading_tags(url: str, html: str) -> Dict[str, Any]:
    """Check heading tag structure (V3 logic: all of h1, h2, h3 must be present)."""
    if not html:
        return {"status": "No", "raw_data": {"reason": "No HTML to analyze"}}

    soup = BeautifulSoup(html, "html.parser")
    headings = {}
    for tag in ("h1", "h2", "h3"):
        found = soup.find_all(tag)
        headings[tag] = {
            "count": len(found),
            "texts": [h.get_text(strip=True) for h in found[:10]],
        }

    all_present = all(headings[h]["count"] > 0 for h in ("h1", "h2", "h3"))
    missing = [h for h in ("h1", "h2", "h3") if headings[h]["count"] == 0]

    # Additional quality check (V3): exactly 1 H1 and non-generic text
    h1_count = headings["h1"]["count"]
    h1_texts = headings["h1"]["texts"]

    if all_present and h1_count == 1:
        status = "Yes"
        reason = (
            f"Heading structure is correct: 1 H1, {headings['h2']['count']} H2s, "
            f"{headings['h3']['count']} H3s."
        )
    elif all_present:
        status = "Needs Improvement"
        reason = (
            f"All heading levels present, but {h1_count} H1 tags found (should be exactly 1). "
            f"H2s: {headings['h2']['count']}, H3s: {headings['h3']['count']}."
        )
    else:
        status = "No"
        reason = f"Missing heading tags: {', '.join(missing)}."

    return {
        "status": status,
        "raw_data": {
            "headings": headings,
            "all_present": all_present,
            "missing_tags": missing,
            "reason": reason,
        },
    }

# 18. HIDDEN CONTENT

async def check_hidden_content(url: str, html: str) -> Dict[str, Any]:
    """Multi-layer hidden content detection (V3 logic).
    Checks: display:none, visibility:hidden, off-screen positioning, white-on-white.
    Legitimacy filter: accordions/collapsibles with <80 hidden words → OK.
    Advanced signals: keyword stuffing, SEO spam terms, suspicious hidden links.
    """
    if not html:
        return {"status": "No", "raw_data": {"reason": "No HTML to analyze"}}

    html_lower = html.lower()
    issues = []

    if "display:none" in html_lower or "display: none" in html_lower:
        issues.append("display:none")
    if "visibility:hidden" in html_lower or "visibility: hidden" in html_lower:
        issues.append("visibility:hidden")
    if re.search(r"left:\s*-\d{4,}px", html_lower) or "top:-9999" in html_lower:
        issues.append("off-screen positioning")
    if (
        ("color:#fff" in html_lower or "color:#ffffff" in html_lower or "color: #fff" in html_lower)
        and ("background:#fff" in html_lower or "background:#ffffff" in html_lower or "background: #fff" in html_lower)
    ):
        issues.append("white-on-white text")

    # Extract hidden text via regex (avoid lxml dependency)
    hidden_text = ""
    soup = BeautifulSoup(html, "html.parser")
    for el in soup.find_all(style=re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)):
        hidden_text += " " + el.get_text(separator=" ", strip=True)
    hidden_words = len(hidden_text.split()) if hidden_text.strip() else 0

    # Legitimacy filter: accordion/collapse/toggle patterns
    accordion_markers = ["accordion", "collapse", "toggle", "tab-content", "tabpanel"]
    is_legit_ui = any(m in html_lower for m in accordion_markers)

    # Advanced spam signal detection
    advanced_signals = 0
    if hidden_words > 300:
        advanced_signals += 1

    # Keyword stuffing
    if hidden_text.strip():
        words_list = re.findall(r"\b\w+\b", hidden_text.lower())
        if len(words_list) >= 50:
            freq = {}
            for w in words_list:
                if len(w) >= 3:
                    freq[w] = freq.get(w, 0) + 1
            for count_val in freq.values():
                if count_val >= 8 or (count_val / len(words_list) > 0.45):
                    advanced_signals += 1
                    break

    # SEO spam keywords
    spam_terms = [
        "buy now", "cheap", "best price", "discount", "order now",
        "seo services", "digital marketing", "buy backlinks",
        "rank higher", "increase traffic", "viagra", "casino", "poker",
    ]
    spam_hits = sum(1 for t in spam_terms if t in hidden_text.lower())
    if spam_hits >= 2:
        advanced_signals += 1

    if not issues:
        status = "No"
        reason = "No hidden content patterns detected."
    elif is_legit_ui and hidden_words < 80:
        status = "No"
        reason = (
            f"Hidden content patterns found ({', '.join(issues)}) but appear to be "
            f"legitimate UI elements (accordion/tab) with only {hidden_words} hidden words."
        )
    elif hidden_words > 120 and advanced_signals >= 2:
        status = "Yes"
        reason = (
            f"Suspicious hidden content detected: {', '.join(issues)}. "
            f"{hidden_words} hidden words with {advanced_signals} spam signal(s)."
        )
    else:
        status = "No"
        reason = (
            f"Hidden content patterns found ({', '.join(issues)}) with "
            f"{hidden_words} hidden words, but no strong spam signals detected."
        )

    return {
        "status": status,
        "raw_data": {
            "issues": issues,
            "hidden_word_count": hidden_words,
            "is_legit_ui": is_legit_ui,
            "advanced_signals": advanced_signals,
            "reason": reason,
        },
    }

# 19. REDIRECT CHAINS/LOOPS

async def check_redirect_chains(url: str, html: str) -> Dict[str, Any]:
    """Check for redirect chains/loops (V3 logic: uses aiohttp redirect history)."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=CRAWL_TIMEOUT),
                allow_redirects=True,
                ssl=False,
            ) as response:
                chain = [str(r.url) for r in response.history]
                final_url = str(response.url)
                has_chain = len(chain) > 1
                has_loop = final_url.rstrip("/") == url.rstrip("/") and len(chain) > 0

                if has_chain or has_loop:
                    status = "No"
                    reason = (
                        f"Redirect chain detected with {len(chain)} hop(s): "
                        f"{' → '.join(chain[:5])} → {final_url}"
                    )
                else:
                    status = "Yes"
                    reason = "No redirect chains or loops detected."

                return {
                    "status": status,
                    "raw_data": {
                        "redirect_count": len(chain),
                        "redirect_chain": chain[:10],
                        "final_url": final_url,
                        "has_chain": has_chain,
                        "has_loop": has_loop,
                        "reason": reason,
                    },
                }
    except Exception as e:
        return {
            "status": "No",
            "raw_data": {"reason": f"Error checking redirects: {e}"},
        }

# 20. SCHEMA MARKUP

async def check_schema_markup(url: str, html: str) -> Dict[str, Any]:
    """Check for structured data: JSON-LD, Microdata, RDFa (V3 logic)."""
    if not html:
        return {"status": "No", "raw_data": {"reason": "No HTML to analyze"}}

    import json as _json
    # Fresh parse to preserve <script> tags
    soup = BeautifulSoup(html, "html.parser")
    schema_types = []

    # 1. JSON-LD
    json_ld_schemas = []
    for script in soup.find_all("script", type="application/ld+json"):
        if not script.string:
            continue
        try:
            data = _json.loads(script.string)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict):
                    # Handle @graph
                    if "@graph" in item:
                        for g in item["@graph"]:
                            if isinstance(g, dict):
                                json_ld_schemas.append(g)
                                t = g.get("@type", "Unknown")
                                if isinstance(t, list):
                                    schema_types.extend(t)
                                else:
                                    schema_types.append(t)
                    else:
                        json_ld_schemas.append(item)
                        t = item.get("@type", "Unknown")
                        if isinstance(t, list):
                            schema_types.extend(t)
                        else:
                            schema_types.append(t)
        except Exception:
            continue

    # 2. Microdata
    microdata_types = []
    for item in soup.find_all(attrs={"itemscope": True}):
        itemtype = item.get("itemtype", "")
        if itemtype:
            t = itemtype.rstrip("/").split("/")[-1]
            if t:
                microdata_types.append(t)
    microdata_types = list(set(microdata_types))
    schema_types.extend(microdata_types)

    # 3. RDFa
    rdfa_types = []
    for el in soup.find_all(attrs={"typeof": True}):
        t = el.get("typeof", "")
        if t:
            rdfa_types.append(t)
    rdfa_types = list(set(rdfa_types))
    schema_types.extend(rdfa_types)

    has_schema = bool(json_ld_schemas or microdata_types or rdfa_types)

    # Validate against known schema.org types
    valid_types = {
        "Article", "BlogPosting", "NewsArticle", "Book", "Movie", "Recipe",
        "Review", "VideoObject", "WebPage", "WebSite", "Organization",
        "LocalBusiness", "Person", "Product", "Offer", "Event", "Place",
        "FAQPage", "HowTo", "BreadcrumbList", "ItemList", "JobPosting",
        "Course", "Service", "SoftwareApplication", "ImageObject",
    }
    validated = any(t in valid_types for t in schema_types)

    if has_schema:
        status = "Yes"
        reason = f"Schema markup found: {', '.join(set(schema_types))}."
    else:
        status = "No"
        reason = "No schema markup (JSON-LD, Microdata, or RDFa) detected."

    return {
        "status": status,
        "raw_data": {
            "has_schema": has_schema,
            "json_ld_count": len(json_ld_schemas),
            "json_ld_types": [s.get("@type", "Unknown") for s in json_ld_schemas],
            "microdata_types": microdata_types,
            "rdfa_types": rdfa_types,
            "all_types": list(set(schema_types)),
            "validation_passed": validated,
            "reason": reason,
        },
    }
    
# 21. HREFLANG TAGS

async def check_hreflang_tags(url: str, html: str) -> Dict[str, Any]:
    """Check if hreflang tags are implemented (V3 logic)."""
    if not html:
        return {"status": "No", "raw_data": {"reason": "No HTML to analyze"}}

    soup = BeautifulSoup(html, "html.parser")
    hreflang_links = soup.find_all("link", rel="alternate", hreflang=True)
    hreflang_present = len(hreflang_links) > 0

    # Also check html lang attribute
    html_tag = soup.find("html")
    html_lang = html_tag.get("lang", "") if html_tag else ""

    tags_data = [
        {"hreflang": t.get("hreflang", ""), "href": t.get("href", "")}
        for t in hreflang_links[:20]
    ]

    if hreflang_present:
        status = "Yes"
        reason = f"Hreflang tags found: {len(hreflang_links)} alternate language link(s)."
    else:
        status = "No"
        reason = "No hreflang tags found. Page only targets a single language."

    return {
        "status": status,
        "raw_data": {
            "hreflang_present": hreflang_present,
            "hreflang_count": len(hreflang_links),
            "html_lang": html_lang,
            "tags": tags_data,
            "reason": reason,
        },
    }

# 22. CONSISTENT LANGUAGE TARGETING

_ISO_LANGS = {
    "en", "fr", "es", "de", "ru", "it", "zh", "ja", "ko", "ar", "pt",
    "hi", "bn", "pa", "jv", "id", "vi", "te", "fa", "pl", "uk", "ro", "nl",
}


async def check_language_targeting(url: str, html: str) -> Dict[str, Any]:
    """Check language targeting consistency (V3 logic).
    Validates: hreflang presence, ISO codes, lowercase, self-referencing tag.
    """
    if not html:
        return {"status": "No", "raw_data": {"reason": "No HTML to analyze"}}

    soup = BeautifulSoup(html, "html.parser")
    hreflang_tags = soup.find_all("link", rel="alternate", hreflang=True)

    if not hreflang_tags:
        # No hreflang → check if single-language page with html lang attribute
        html_tag = soup.find("html")
        html_lang = html_tag.get("lang", "") if html_tag else ""
        if html_lang:
            status = "Yes"
            reason = f"Single-language page with html lang='{html_lang}'. No hreflang required."
        else:
            status = "No"
            reason = "No hreflang tags and no html lang attribute found."
        return {"status": status, "raw_data": {"html_lang": html_lang, "reason": reason}}

    parsed_url = urlparse(url)
    domain = parsed_url.netloc
    current_url_clean = url.rstrip("/")
    has_self_ref = False
    issues = []

    tags_data = []
    for tag in hreflang_tags:
        hreflang_val = tag.get("hreflang", "").strip()
        href = tag.get("href", "").strip()
        tags_data.append({"hreflang": hreflang_val, "href": href})

        if hreflang_val == "x-default":
            continue

        parts = hreflang_val.split("-")
        lang_code = parts[0].lower()

        # Validate ISO language code
        if lang_code not in _ISO_LANGS:
            issues.append(f"Invalid language code: '{hreflang_val}'")

        # Check lowercase
        if hreflang_val != hreflang_val.lower():
            issues.append(f"Hreflang not lowercase: '{hreflang_val}'")

        # Self-referencing check
        href_clean = href.rstrip("/")
        if href_clean == current_url_clean or urlparse(href).netloc == domain:
            has_self_ref = True

    if not has_self_ref:
        issues.append("No self-referencing hreflang tag found")

    if issues:
        status = "No"
        reason = f"Language targeting issues: {'; '.join(issues)}."
    else:
        status = "Yes"
        reason = f"Language targeting is consistent with {len(hreflang_tags)} hreflang tag(s) and self-reference."

    return {
        "status": status,
        "raw_data": {
            "hreflang_count": len(hreflang_tags),
            "has_self_reference": has_self_ref,
            "issues": issues,
            "tags": tags_data[:20],
            "reason": reason,
        },
    }

# 23. LLMS.TXT FILE

_llms_cache: Dict[str, str] = {}


async def check_llms_txt(url: str, html: str) -> Dict[str, Any]:
    """Check for /llms.txt file at root domain (V3 logic)."""
    parsed = urlparse(url)
    root_domain = f"{parsed.scheme}://{parsed.netloc}"

    # Cache per domain
    if root_domain in _llms_cache:
        cached = _llms_cache[root_domain]
        return {
            "status": cached,
            "raw_data": {"llms_url": f"{root_domain}/llms.txt", "cached": True, "found": cached == "Yes"},
        }

    llms_url = f"{root_domain}/llms.txt"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                llms_url,
                headers={"User-Agent": USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=10),
                ssl=False,
            ) as response:
                if response.status == 200:
                    content = await response.text()
                    result = "Yes" if content and content.strip() else "No"
                else:
                    result = "No"
    except Exception as e:
        logger.debug(f"Error fetching llms.txt: {e}")
        result = "No"

    _llms_cache[root_domain] = result

    if result == "Yes":
        reason = f"llms.txt found at {llms_url}."
    else:
        reason = f"No llms.txt file found at {llms_url}."

    return {
        "status": result,
        "raw_data": {"llms_url": llms_url, "found": result == "Yes", "reason": reason},
    }

# REGISTRY: Map column names to their dedicated check functions

# Each function signature: async def check(url: str, html: str) -> Dict[str, Any]
DEDICATED_CHECKS = {
    "Robots.txt configured correctly": check_robots_txt,
    "XML Sitemap updated & submitted": check_xml_sitemap,
    "Canonical tags implemented": check_canonical_tags,
    "Logical site hierarchy": check_logical_hierarchy,
    "No intrusive interstitials": check_interstitials,
    "SSL certificate active": check_ssl_certificate,
    "No mixed content warnings": check_mixed_content,
    "Keyword Density": check_keyword_density,
    "Thin content audit": check_thin_content,
    "Broken Links": check_broken_links,
    "404 Errors": check_404_errors,
    "Google Analytics/GA4 setup": check_ga4_setup,
    "Google Search Console setup": check_gsc_setup,
    "Internal linking optimization": check_internal_linking,
    "EEAT(Expereince, Expertise, Authoritativeness, and Trustworthiness)": check_eeat,
    "Breadcrumb navigation": check_breadcrumb,
    "Duplicate content check": check_duplicate_content,
    "Meta Description <160 Characters Including Space>": check_meta_description,
    "Meta Description <160 Characters": check_meta_description,
    "Meta Description <160 Charecters Including Space>": check_meta_description,
    "Heading Tags(H1/H2/h3)": check_heading_tags,
    "Hidden Content": check_hidden_content,
    "Avoid crawl traps": check_avoid_crawl_traps,
    "Avoid Crawl Traps": check_avoid_crawl_traps,
    "Avoid redirect chains/loops": check_redirect_chains,
    "Schema markup implemented": check_schema_markup,
    "Hreflang tags implemented": check_hreflang_tags,
    "Consistent language targeting": check_language_targeting,
    "LLMS.text File": check_llms_txt,
}
