import time
import random
from datetime import datetime
from playwright.sync_api import sync_playwright
 
def normalize_domain(url):
    """Standardizes URLs by removing protocol, www, and trailing slashes."""
    if not url: return ""
    url = url.lower()
    if "://" in url: url = url.split("://")[-1]
    if url.startswith("www."): url = url[4:]
    return url.strip().strip("/")
 
def run_playwright(state):
    """Enhanced Playwright scraper with 5-page pagination + smart local logic."""
    all_organic = []
    all_local = []
    organic_rank = None
    local_rank = None
 
    # Inputs
    target_domain = normalize_domain(state.get("domain", ""))
    target_brand = state.get("brand", "").lower().strip()
    keyword = state.get("keyword", "")
    latitude = state.get("latitude", 28.5355)
    longitude = state.get("longitude", 77.3910)
    city = state.get("city", "Noida")
 
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security",
                "--disable-features=VizDisplayCompositor"
            ]
        )
       
        context = browser.new_context(
            viewport={'width': 1366, 'height': 768},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            geolocation={"latitude": latitude, "longitude": longitude},
            permissions=["geolocation"]
        )
       
        page = context.new_page()
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
        """)
 
        try:
            # ===============================
            # ORGANIC PAGINATION (UP TO 5 PAGES)
            # ===============================
            max_pages = 5
            results_per_page = 10
 
            for page_number in range(max_pages):
 
                start = page_number * results_per_page
 
                search_url = (
                    f"https://www.google.com/search?"
                    f"q={keyword.replace(' ', '+')}"
                    f"&hl=en&gl=in"
                    f"&start={start}"
                )
 
                print(f"\nChecking Page {page_number + 1}")
                page.goto(search_url, wait_until="networkidle", timeout=30000)
 
                page.wait_for_selector("h3, [data-ved], .tF2Cxc", timeout=30000)
                time.sleep(random.uniform(3, 5))
 
                organic_selectors = [
                    "h3", "h3[data-ved]", ".tF2Cxc a", "div.yuRUbf > a",
                    ".LC20lb", ".v7jaNc", "a[href*='http']"
                ]
 
                for selector in organic_selectors:
                    elements = page.query_selector_all(selector)
 
                    for el in elements[:15]:
                        try:
                            href = el.get_attribute("href") or el.evaluate("el => el.closest('a')?.href")
                           
                            if href and "google.com" not in href and href.startswith("http"):
                                if href not in all_organic:
                                    all_organic.append(href)
 
                                    if organic_rank is None and target_domain:
                                        if target_domain in normalize_domain(href):
                                            organic_rank = len(all_organic)
                                            print(f"✅ Found organic rank: {organic_rank}")
                                            break
                        except:
                            continue
 
                    if organic_rank is not None:
                        break
 
                if organic_rank is not None:
                    break
 
            # ===============================
            # SMART LOCAL PACK (SAME SELECTORS)
            # ===============================
            page.goto(
                f"https://www.google.com/search?q={keyword.replace(' ', '+')}&hl=en&gl=in",
                wait_until="networkidle",
                timeout=30000
            )
 
            time.sleep(3)
 
            local_selectors = [
                "div[data-attrid='title']", "div[role='heading']",
                ".Nv2PK", ".OSrXXb", ".qLYAZd span",
                "div[data-result-index]", ".MnRZS .rllt__details"
            ]
 
            junk_keywords = [
                "choose what",
                "customised",
                "results for",
                "places",
                "feedback",
                "rating"
            ]
 
            # -------- STEP 1: CHECK VISIBLE PACK --------
            for selector in local_selectors:
                elements = page.query_selector_all(selector)
 
                for el in elements[:10]:
                    try:
                        name = el.inner_text().strip()
 
                        if (
                            name
                            and len(name) > 2
                            and not any(j in name.lower() for j in junk_keywords)
                            and not name.startswith('"')
                        ):
                            if name not in all_local:
                                all_local.append(name)
 
                                if local_rank is None and target_brand:
                                    if target_brand in name.lower():
                                        local_rank = len(all_local)
                                        print(f"✅ Found in visible pack at rank: {local_rank}")
                                        break
                    except:
                        continue
 
                if local_rank is not None:
                    break
 
            # -------- STEP 2: IF NOT FOUND → CLICK MORE PLACES --------
            if local_rank is None:
 
                more_places = page.query_selector("a:has-text('More places')")
 
                if more_places:
                    print("Brand not in visible pack. Expanding to More places...")
                    more_places.click()
                    page.wait_for_load_state("networkidle")
                    time.sleep(3)
 
                    scrollable = page.query_selector("div[role='feed']")
                    if scrollable:
                        for _ in range(12):
                            scrollable.evaluate("(el) => el.scrollBy(0, 1000)")
                            time.sleep(1.5)
 
                    for selector in local_selectors:
                        elements = page.query_selector_all(selector)
 
                        for el in elements:
                            try:
                                name = el.inner_text().strip()
 
                                if (
                                    name
                                    and len(name) > 2
                                    and not any(j in name.lower() for j in junk_keywords)
                                    and not name.startswith('"')
                                ):
                                    if name not in all_local:
                                        all_local.append(name)
 
                                        if local_rank is None and target_brand:
                                            if target_brand in name.lower():
                                                local_rank = len(all_local)
                                                print(f"✅ Found in expanded pack at rank: {local_rank}")
                                                break
                            except:
                                continue
 
                        if local_rank is not None:
                            break
 
        except Exception as e:
            print(f"Scraper error: {e}")
           
        finally:
            time.sleep(random.uniform(1, 2))
            browser.close()
 
    result = {
        "keyword": keyword,
        "organic_rank": organic_rank,
        "local_rank": local_rank,
        "all_organic": all_organic,
        "all_local": all_local,
        "method": "playwright_enhanced",
        "raw_organic_count": len(all_organic),
        "raw_local_count": len(all_local)
    }
   
    print(f"Final result: {result}")
    return result
