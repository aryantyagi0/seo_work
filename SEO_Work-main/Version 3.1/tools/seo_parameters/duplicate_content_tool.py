import requests
import logging
import asyncio
import re
import faiss
import numpy as np
from typing import List, Dict, Any
from langchain_core.tools import tool
from bs4 import BeautifulSoup
from sklearn.feature_extraction.text import TfidfVectorizer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DuplicateContentTool")

def _clean_text_v4(text: str) -> str:
    """Cleaning logic from Version 4: lowercase, alphanumeric only, words > 3 chars."""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return " ".join(w for w in text.split() if len(w) > 3)

def _get_text_from_html(html_content: str):
    """Extracts visible text from HTML content."""
    if not html_content: return ""
    soup = BeautifulSoup(html_content, 'lxml')
    for script_or_style in soup(['script', 'style']): script_or_style.extract()
    return soup.get_text(separator=' ', strip=True)

def _get_severity(score: float) -> str:
    """Severity mapping from Version 4."""
    if score >= 0.80:
        return "High Risk (Probable Duplicate)"
    if score >= 0.70:
        return "Medium Risk (Partial Content Overlap)"
    return "Low Risk (Standard Template Similarity)"

@tool
async def analyze_duplicate_content_tool(
    sources: list,
    url: str = None,
    similarity_threshold: float = 0.50,
    criteria: dict = None
) -> dict:
    """
    Analyzes content from multiple sources for duplication using V4 logic (TF-IDF + FAISS).
    Checks text similarity, meta tags, and images across the batch.
    """
    if criteria is None: criteria = {}
    similarity_threshold = criteria.get("similarity_threshold", similarity_threshold)
    
    # 1. Prepare and Fetch Content
    prepared_data = []
    for i, src in enumerate(sources):
        fields = src.get("fields", {})
        source_id = src.get("name") or src.get("value") or f"Source_{i+1}"
        
        # If text_content is missing but type is url, fetch it
        if not fields.get("text_content") and src.get("type") == "url":
            try:
                response = await asyncio.to_thread(requests.get, src["value"], timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                if response.status_code == 200:
                    fields["text_content"] = _get_text_from_html(response.text)
            except Exception: pass
        
        prepared_data.append({
            "id": source_id,
            "text": fields.get("text_content", ""),
            "meta_title": fields.get("meta_title", ""),
            "meta_description": fields.get("meta_description", ""),
            "h1_tags": fields.get("h1_tags", ""),
            "images": fields.get("images", []),
            "raw_fields": fields
        })

    if len(prepared_data) < 2:
        return {"status": "info", "message": "At least two sources are needed for comparison."}

    # 2. Text Content Similarity (TF-IDF + FAISS)
    documents = [_clean_text_v4(p["text"]) for p in prepared_data]
    ids = [p["id"] for p in prepared_data]
    
    text_scores = {}
    try:
        vectorizer = TfidfVectorizer(max_features=15000, min_df=1, stop_words="english")
        tfidf = vectorizer.fit_transform(documents)
        vectors = tfidf.toarray().astype("float32")
        faiss.normalize_L2(vectors)

        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)

        for i, source_id in enumerate(ids):
            word_count = len(documents[i].split())
            if word_count < 20:
                text_scores[source_id] = []
                continue
                
            scores, indices = index.search(vectors[i].reshape(1, -1), k=min(10, len(ids)))
            matches = []
            for score, idx in zip(scores[0], indices[0]):
                if idx == i: continue
                if score >= similarity_threshold:
                    matches.append({"url": ids[idx], "score": round(float(score), 4)})
            text_scores[source_id] = sorted(matches, key=lambda x: x["score"], reverse=True)
    except Exception as e:
        logger.error(f"Similarity engine error: {e}")
        text_scores = {sid: [] for sid in ids}

    # 3. Exact Match Checks (Tags & Images)
    title_map, desc_map, h1_map, img_src_map, img_alt_map = {}, {}, {}, {}, {}
    for p in prepared_data:
        for val, m in [(p["meta_title"], title_map), (p["meta_description"], desc_map), (p["h1_tags"], h1_map)]:
            if val and str(val).strip():
                m.setdefault(str(val).strip().lower(), []).append(p["id"])
        
        for img in p.get("images", []):
            src, alt = img.get("src", "").strip(), img.get("alt", "").strip()
            if src: img_src_map.setdefault(src, []).append(p["id"])
            if alt: img_alt_map.setdefault(alt, []).append(p["id"])

    # 4. Formulate Result for Target
    # Identify target: either the requested URL or the first source
    target_id = url if url and any(p["id"] == url for p in prepared_data) else prepared_data[0]["id"]
    target_data = next(p for p in prepared_data if p["id"] == target_id)
    
    matches = text_scores.get(target_id, [])
    best_text_match = matches[0] if matches else None
    highest_score = (best_text_match["score"] * 100) if best_text_match else 0
    
    # Identify specific tag duplicates
    field_matches = []
    for field, m, val in [
        ("Meta Title", title_map, target_data["meta_title"]),
        ("Meta Description", desc_map, target_data["meta_description"]),
        ("H1 Tags", h1_map, target_data["h1_tags"])
    ]:
        if val and str(val).strip().lower() in m:
            others = [oid for oid in m[str(val).strip().lower()] if oid != target_id]
            if others: field_matches.append(field)

    # Identify image duplicates
    img_dupes = []
    seen_assets = set()
    for img in target_data.get("images", []):
        src, alt = img.get("src", "").strip(), img.get("alt", "").strip()
        if src and src not in seen_assets:
            others = [oid for oid in img_src_map.get(src, []) if oid != target_id]
            if others: img_dupes.append(f"Image Source: {src[:50]}..."); seen_assets.add(src)
        if alt and alt not in seen_assets:
            others = [oid for oid in img_alt_map.get(alt, []) if oid != target_id]
            if others: img_dupes.append(f"Image Alt: {alt[:50]}..."); seen_assets.add(alt)

    # 5. Verdict and Message
    verdict = _get_severity(highest_score / 100)
    if field_matches:
        verdict += f" - DUPLICATE SEO TAGS DETECTED: {', '.join(field_matches)}"
    if img_dupes:
        verdict += f" - {len(img_dupes)} DUPLICATE IMAGES DETECTED"

    status = "warning" if (highest_score >= (similarity_threshold * 100) or field_matches or img_dupes) else "success"
    
    if best_text_match:
        match_info = f" {highest_score:.2f}% similarity with {best_text_match['url']}"
    else:
        match_info = " No significant text overlap found"

    msg = f"Nearest Match:{match_info}. Verdict: {verdict}."
    
    return {
        "status": status,
        "message": msg,
        "details": {
            "verdict": verdict,
            "highest_score": round(highest_score, 2),
            "nearest_neighbor": best_text_match["url"] if best_text_match else None,
            "shared_seo_fields": field_matches,
            "duplicate_images_count": len(img_dupes),
            "text_matches": matches,
            "all_scores": [{"url": m["url"], "score": round(m["score"] * 100, 2)} for m in matches],
            "target_url": target_id,
            "lengths": {
                "meta_title": len(str(target_data["meta_title"])),
                "meta_description": len(str(target_data["meta_description"])),
                "h1_tags": [len(str(h)) for h in (target_data["h1_tags"] if isinstance(target_data["h1_tags"], list) else [target_data["h1_tags"]])] if target_data["h1_tags"] else []
            }
        }
    }
