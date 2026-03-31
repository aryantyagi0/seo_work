import os
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engines.playwright_engine import run_playwright

# Import your engines
from engines.playwright_engine import run_playwright
from engines.serpapi_engine import run_serpapi

# 1. LOAD ENVIRONMENT VARIABLES
load_dotenv()

app = FastAPI()


class RankingRequest(BaseModel):
    keyword: str
    brand: str
    domain: str
    method: str
    latitude: float
    longitude: float
    city: str
    area: str = ""
    api_key: Optional[str] = None  # <--- NEW: Accept the key from the UI

def get_keyword_rankings(
    keyword,
    brand,
    domain,
    method,
    latitude,
    longitude,
    city,
    area="",
    api_key=None,
):
    state = {
        "keyword": keyword,
        "brand": brand,
        "domain": domain,
        "latitude": latitude,
        "longitude": longitude,
        "city": city,
        "area": area,
        "api_key": api_key,
    }

    if method.lower() == "playwright":
        return run_playwright(state)

    elif method.lower() == "serpapi":
        active_key = api_key or os.getenv("SERP_API_KEY")

        if not active_key:
            return {"error": "SerpApi Key is missing."}

        state["api_key"] = active_key
        return run_serpapi(state)

    else:
        return {"error": "Invalid ranking method selected"}
    

@app.post("/rank")
def run_ranking(data: RankingRequest):
    return get_keyword_rankings(
        keyword=data.keyword,
        brand=data.brand,
        domain=data.domain,
        method=data.method,
        latitude=data.latitude,
        longitude=data.longitude,
        city=data.city,
        area=data.area,
        api_key=data.api_key,
    )
    # 2. SELECT ENGINE
    if data.method.lower() == "playwright":
        return run_playwright(state)
    
    elif data.method.lower() == "serpapi":
        # Check logic: 1. Use key from UI, 2. Use key from .env, 3. Error
        active_key = data.api_key or os.getenv("SERP_API_KEY")
        
        if not active_key:
            return {"error": "SerpApi Key is missing. Please enter it in the sidebar or check .env"}
        
        # Ensure the engine uses the correct key
        state["api_key"] = active_key
        return run_serpapi(state)
    
    else:
        return {"error": "Invalid ranking method selected"}

@app.get("/health")
def health_check():
    key_exists = os.getenv("SERP_API_KEY") is not None
    return {
        "status": "online",
        "env_key_loaded": key_exists
    }