"""
V4 Post-Crawl Duplicate Detection
Runs AFTER all URLs have been individually audited.

4 independent checks:
1. Text content similarity  (TF-IDF + FAISS cosine similarity)
2. Meta title duplicates     (exact string match)
3. Meta description duplicates (exact string match)
4. Image alt-text duplicates  (exact src/alt match)

Called from app.py after all per-URL audits complete.
"""
import re
import faiss
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from typing import List, Dict, Any
from utils.logging_config import get_logger

logger = get_logger("PostCrawlDuplicates")

SIMILARITY_THRESHOLD = 0.50


# helpers

def _clean_text(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return " ".join(w for w in text.split() if len(w) > 3)


def _severity(score: float) -> str:
    if score >= 0.80:
        return "High"
    if score >= 0.70:
        return "Medium"
    return "Low"

# 1. TEXT CONTENT — TF-IDF + FAISS

def detect_text_duplicates(pages: List[Dict]) -> Dict[str, Dict]:
    """
    TF-IDF vectorisation → FAISS cosine similarity across all pages.

    pages: [{"url": str, "text": str}]
    Returns: {url: {"duplicate_content": "No"|"Yes (0.XX)", "similar_urls": "url1 (0.XX – High) | url2 ..."}}
    """
    if len(pages) < 2:
        return {p["url"]: {"duplicate_content": "No", "similar_urls": ""} for p in pages}

    urls = [p["url"] for p in pages]
    documents = [_clean_text(p.get("text", "")) for p in pages]

    # If all pages have very short content, skip
    if all(len(doc.split()) < 20 for doc in documents):
        return {u: {"duplicate_content": "No", "similar_urls": ""} for u in urls}

    try:
        vectorizer = TfidfVectorizer(max_features=15000, min_df=1, stop_words="english")
        tfidf = vectorizer.fit_transform(documents)
        vectors = tfidf.toarray().astype("float32")
        faiss.normalize_L2(vectors)

        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)
    except Exception as e:
        logger.error(f"TF-IDF/FAISS init error: {e}")
        return {u: {"duplicate_content": "No", "similar_urls": ""} for u in urls}

    results = {}
    for i, url in enumerate(urls):
        word_count = len(documents[i].split())
        if word_count < 20:
            results[url] = {"duplicate_content": "No", "similar_urls": ""}
            continue

        scores, indices = index.search(vectors[i].reshape(1, -1), k=min(10, len(urls)))

        cluster = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == i:
                continue
            if score >= SIMILARITY_THRESHOLD:
                cluster.append((idx, round(float(score), 2)))

        if not cluster:
            results[url] = {"duplicate_content": "No", "similar_urls": ""}
            continue

        best_score = max(s for _, s in cluster)
        similar_urls = [
            f"{urls[idx]} ({score:.2f} – {_severity(score)})"
            for idx, score in cluster
        ]

        results[url] = {
            "duplicate_content": f"Yes ({best_score:.2f})",
            "similar_urls": " | ".join(similar_urls),
        }

    logger.info(f"Text duplicate detection: {sum(1 for r in results.values() if r['duplicate_content'].startswith('Yes'))} pages with duplicates")
    return results

# 2. META TITLE DUPLICATES

def detect_title_duplicates(pages: List[Dict]) -> Dict[str, Dict]:
    """
    Exact-match meta title duplicate detection.

    pages: [{"url": str, "meta_title": str}]
    Returns: {url: {"has_duplicate": bool, "duplicate_urls": [...], "duplicate_count": int}}
    """
    if len(pages) < 2:
        return {}

    title_map: Dict[str, List[str]] = {}
    for page in pages:
        title = page.get("meta_title", "").strip()
        if title:
            title_map.setdefault(title, []).append(page["url"])

    results = {}
    for page in pages:
        url = page["url"]
        title = page.get("meta_title", "").strip()
        if not title:
            results[url] = {"has_duplicate": False, "duplicate_urls": [], "duplicate_count": 0}
            continue

        others = [u for u in title_map.get(title, []) if u != url]
        results[url] = {
            "has_duplicate": len(others) > 0,
            "duplicate_urls": others,
            "duplicate_count": len(others),
        }

    logger.info(f"Meta title duplicates: {sum(1 for r in results.values() if r['has_duplicate'])} pages")
    return results

# 3. META DESCRIPTION DUPLICATES

def detect_description_duplicates(pages: List[Dict]) -> Dict[str, Dict]:
    """
    Exact-match meta description duplicate detection.

    pages: [{"url": str, "meta_description": str}]
    Returns: {url: {"has_duplicate": bool, "duplicate_urls": [...], "duplicate_count": int}}
    """
    if len(pages) < 2:
        return {}

    desc_map: Dict[str, List[str]] = {}
    for page in pages:
        desc = page.get("meta_description", "").strip()
        if desc:
            desc_map.setdefault(desc, []).append(page["url"])

    results = {}
    for page in pages:
        url = page["url"]
        desc = page.get("meta_description", "").strip()
        if not desc:
            results[url] = {"has_duplicate": False, "duplicate_urls": [], "duplicate_count": 0}
            continue

        others = [u for u in desc_map.get(desc, []) if u != url]
        results[url] = {
            "has_duplicate": len(others) > 0,
            "duplicate_urls": others,
            "duplicate_count": len(others),
        }

    logger.info(f"Meta description duplicates: {sum(1 for r in results.values() if r['has_duplicate'])} pages")
    return results

# 4. IMAGE DUPLICATES (by src URL and alt text)

def detect_image_duplicates(pages: List[Dict]) -> Dict[str, Dict]:
    """
    Image duplicate detection across pages by exact src or exact alt text.

    pages: [{"url": str, "images": [{"src": str, "alt": str}]}]
    Returns: {url: {"duplicate_count": int, "details": [...]}}
    """
    if len(pages) < 2:
        return {}

    src_map: Dict[str, List[str]] = {}   # src → [urls]
    alt_map: Dict[str, List[str]] = {}   # alt → [urls]

    for page in pages:
        url = page["url"]
        for img in page.get("images", []):
            src = img.get("src", "").strip()
            alt = img.get("alt", "").strip()
            if src:
                src_map.setdefault(src, []).append(url)
            if alt:
                alt_map.setdefault(alt, []).append(url)

    results = {}
    for page in pages:
        url = page["url"]
        duplicate_images = []
        seen_src = set()
        seen_alt = set()

        for img in page.get("images", []):
            src = img.get("src", "").strip()
            alt = img.get("alt", "").strip()

            if src and src not in seen_src:
                others = [u for u in src_map.get(src, []) if u != url]
                if others:
                    duplicate_images.append({
                        "type": "src",
                        "value": src,
                        "found_on": list(set(others))[:3],
                    })
                    seen_src.add(src)

            if alt and alt not in seen_alt:
                others = [u for u in alt_map.get(alt, []) if u != url]
                if others:
                    duplicate_images.append({
                        "type": "alt",
                        "value": alt,
                        "found_on": list(set(others))[:3],
                    })
                    seen_alt.add(alt)

        results[url] = {
            "duplicate_count": len(duplicate_images),
            "details": duplicate_images[:5],
        }

    logger.info(f"Image duplicates: {sum(1 for r in results.values() if r['duplicate_count'] > 0)} pages")
    return results

# ORCHESTRATOR: Run all 4 checks + merge into unified result per URL

def run_postcrawl_duplicate_detection(page_data: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Run all 4 duplicate checks after all URLs have been individually audited.

    Args:
        page_data: [{
            "url": str,
            "text": str,           # main content text (from _extract_main_text)
            "meta_title": str,
            "meta_description": str,
            "images": [{"src": str, "alt": str}],
        }]

    Returns:
        {url: {
            "status": "Yes"|"No",
            "raw_data": {
                "text_similarity": {...},
                "title_duplicates": {...},
                "desc_duplicates": {...},
                "image_duplicates": {...},
                "merged_summary": str,
            }
        }}
    """
    if len(page_data) < 2:
        return {
            p["url"]: {
                "status": "Yes",
                "raw_data": {"reason": "Only one page — nothing to compare."},
            }
            for p in page_data
        }

    logger.info(f"Running post-crawl duplicate detection on {len(page_data)} pages")

    # Run all 4 checks
    text_results = detect_text_duplicates(page_data)
    title_results = detect_title_duplicates(page_data)
    desc_results = detect_description_duplicates(page_data)
    image_results = detect_image_duplicates(page_data)

    # Merge per URL
    merged = {}
    for page in page_data:
        url = page["url"]
        text_dup = text_results.get(url, {"duplicate_content": "No", "similar_urls": ""})
        title_dup = title_results.get(url, {"has_duplicate": False, "duplicate_urls": []})
        desc_dup = desc_results.get(url, {"has_duplicate": False, "duplicate_urls": []})
        img_dup = image_results.get(url, {"duplicate_count": 0, "details": []})

        summary = _build_merged_summary(text_dup, title_dup, desc_dup, img_dup)

        has_any = (
            text_dup.get("duplicate_content", "No").startswith("Yes")
            or title_dup.get("has_duplicate", False)
            or desc_dup.get("has_duplicate", False)
            or img_dup.get("duplicate_count", 0) > 0
        )

        merged[url] = {
            "status": "No" if has_any else "Yes",
            "raw_data": {
                "text_similarity": text_dup,
                "title_duplicates": title_dup,
                "desc_duplicates": desc_dup,
                "image_duplicates": img_dup,
                "merged_summary": summary,
                "reason": summary,
            },
        }

    return merged


def _build_merged_summary(text_dup, title_dup, desc_dup, img_dup) -> str:
    """Build a human-readable merged paragraph for all 4 duplicate checks."""
    parts = []

    # 1. Text content
    if text_dup.get("duplicate_content", "No").startswith("Yes"):
        parts.append(f"Text Content: {text_dup['duplicate_content']} — similar to {text_dup.get('similar_urls', '')}")
    else:
        parts.append("Text Content: Unique")

    # 2. Meta Title
    if title_dup.get("has_duplicate"):
        urls = title_dup.get("duplicate_urls", [])[:3]
        parts.append(f"Meta Title: Duplicate ({title_dup.get('duplicate_count', 0)} page(s)) — {', '.join(urls)}")
    else:
        parts.append("Meta Title: Unique")

    # 3. Meta Description
    if desc_dup.get("has_duplicate"):
        urls = desc_dup.get("duplicate_urls", [])[:3]
        parts.append(f"Meta Description: Duplicate ({desc_dup.get('duplicate_count', 0)} page(s)) — {', '.join(urls)}")
    else:
        parts.append("Meta Description: Unique")

    # 4. Images
    img_count = img_dup.get("duplicate_count", 0)
    if img_count > 0:
        details = img_dup.get("details", [])
        page_set = set()
        for d in details[:5]:
            page_set.update(d.get("found_on", []))
        if page_set:
            parts.append(f"Images: {img_count} duplicate(s) found on: {', '.join(list(page_set)[:3])}")
        else:
            parts.append(f"Images: {img_count} duplicate(s) found across other pages")
    else:
        parts.append("Images: No duplicates")

    return ". ".join(parts) + "."
