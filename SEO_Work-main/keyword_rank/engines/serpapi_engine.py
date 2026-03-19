import requests
import os
from datetime import datetime


def normalize_domain(url):
    """
    Standardizes a URL by removing protocols, 'www.', and trailing slashes.
    """
    if not url:
        return ""
    url = url.lower()
    if "://" in url:
        url = url.split("://")[-1]
    if url.startswith("www."):
        url = url[4:]
    return url.strip().strip("/")


def run_serpapi(state):

    api_key = state.get("api_key") or os.getenv("SERP_API_KEY")

    if not api_key:
        return {
            "error": "SerpApi Key missing. Please enter it in the sidebar.",
            "method": "serpapi"
        }

    target_domain = normalize_domain(state.get("domain", ""))
    target_brand = state.get("brand", "").lower().strip()

    max_pages = 5
    results_per_page = 20   # INCREASED FROM 10 → 20

    organic_rank = None
    local_rank = None

    all_organic = []
    all_local = []

    first_page_data = None  # Store page 1 response

    # -------------------------------------------------
    # SMART LOCATION HANDLING (Avoid double location)
    # -------------------------------------------------
    query_lower = state["keyword"].lower()
    city_lower = state["city"].lower()

    if city_lower in query_lower:
        location_str = None
    else:
        location_str = f"{state.get('area', '')} {state['city']}, India".strip()

    # -------------------------------------------------
    # ORGANIC PAGINATION (UP TO 5 PAGES)
    # -------------------------------------------------
    for page_number in range(max_pages):

        start_value = page_number * results_per_page

        params = {
            "engine": "google",
            "q": state["keyword"],
            "api_key": api_key,
            "gl": "in",
            "hl": "en",
            "google_domain": "google.co.in",
            "num": results_per_page,
            "start": start_value
        }

        if location_str:
            params["location"] = location_str

        try:
            response = requests.get("https://serpapi.com/search", params=params, timeout=20)
            response.raise_for_status()
            data = response.json()

            # ✅ Save first page data for visible local reuse
            if page_number == 0:
                first_page_data = data

        except Exception as e:
            return {"error": f"SerpApi Request Failed: {str(e)}", "method": "serpapi"}

        organic_results = data.get("organic_results", [])

        for result in organic_results:
            link = result.get("link")
            if link:
                if link not in all_organic:
                    all_organic.append(link)

                if organic_rank is None and target_domain:
                    if target_domain in normalize_domain(link):
                        organic_rank = len(all_organic)

        if organic_rank is not None:
            break

        if not organic_results:
            break

    # -------------------------------------------------
    # LOCAL PACK STEP 1 – Visible Pack (REUSED PAGE 1)
    # -------------------------------------------------
    if first_page_data:

        local_data = first_page_data.get("local_results", {})

        if isinstance(local_data, list):
            local_places = local_data
        else:
            local_places = local_data.get("places", [])

        for place in local_places:
            title = place.get("title")
            if title:
                if title not in all_local:
                    all_local.append(title)

                if local_rank is None and target_brand:
                    if target_brand in title.lower():
                        local_rank = len(all_local)
                        break

    # -------------------------------------------------
    # LOCAL PACK STEP 2 – Expanded (tbm=lcl)
    # Only if not found in visible pack
    # -------------------------------------------------
    if local_rank is None:

        for page_number in range(2):

            params = {
                "engine": "google",
                "q": state["keyword"],
                "api_key": api_key,
                "gl": "in",
                "hl": "en",
                "google_domain": "google.co.in",
                "tbm": "lcl",
                "start": page_number * 20
            }

            if location_str:
                params["location"] = location_str

            response = requests.get("https://serpapi.com/search", params=params, timeout=20)
            data = response.json()

            local_results = data.get("local_results", [])

            if not local_results:
                break

            for place in local_results:
                title = place.get("title")
                if title:
                    if title not in all_local:
                        all_local.append(title)

                    if local_rank is None and target_brand:
                        if target_brand in title.lower():
                            local_rank = len(all_local)
                            break

            if local_rank is not None:
                break

    now = datetime.now()

    return {
        "keyword": state["keyword"],
        "organic_rank": organic_rank,
        "local_rank": local_rank,
        "method": "serpapi",
        "date_checked": now.strftime("%Y-%m-%d"),
        "time_checked": now.strftime("%H:%M:%S"),
        "raw_organic_count": len(all_organic),
        "raw_local_count": len(all_local),
        "all_organic": all_organic,
        "all_local": all_local
    }
