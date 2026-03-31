"""
Knowledge Base — Node 1 in the Dynamic SEO Audit Workflow

Crawls ALL URLs upfront, extracts content, builds TF-IDF + FAISS index.
This is the "Central Truth" that:
  • The SEARCH primitive (P8) queries during per-URL processing
  • The Post-Crawl Reconciler uses for global similarity matrix

Mirrors V3 logic: TF-IDF (max_features=15000, stop_words="english")
                   → FAISS IndexFlatIP on L2-normalised vectors (= cosine sim)
                   → threshold ≥ 0.50 → "similar"
"""

import re
import asyncio
import aiohttp
import faiss
import numpy as np
from bs4 import BeautifulSoup
from sklearn.feature_extraction.text import TfidfVectorizer
from typing import Dict, List, Any, Optional, Callable
from utils.logging_config import get_logger
from config.settings import USER_AGENT, CRAWL_TIMEOUT, SIMILARITY_THRESHOLD

logger = get_logger("KnowledgeBase")


# Helpers

def _extract_main_text(soup: BeautifulSoup) -> str:
    """Extract main content text — tries ALL containers + body, keeps highest word count."""
    import copy
    best_text = ""
    best_wc = 0

    for selector in [
        "main", "article", "[role='main']",
        "#content", ".content",
        "#main-content", ".main-content",
        ".post-content", ".entry-content",
    ]:
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


def _clean_text(text: str) -> str:
    """Clean text for TF-IDF vectorisation."""
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

# KnowledgeBase Class

class KnowledgeBase:
    """
    Central Truth Store — FAISS-indexed page content from all crawled URLs.
    Built once before per-URL auditing begins.
    """

    def __init__(self):
        self.pages: Dict[str, Dict[str, Any]] = {}   # url → page data
        self.faiss_index: Optional[faiss.IndexFlatIP] = None
        self.vectorizer: Optional[TfidfVectorizer] = None
        self.url_order: List[str] = []                # FAISS index position → url
        self.vectors: Optional[np.ndarray] = None

    # Phase 1a: Crawl all URLs

    async def crawl_all(self, urls: List[str], progress_cb: Optional[Callable] = None):
        """Crawl all URLs concurrently and extract page data."""
        logger.info(f"Crawling {len(urls)} URLs for Knowledge Base")
        semaphore = asyncio.Semaphore(10)

        async def _fetch_one(url: str) -> Dict[str, Any]:
            async with semaphore:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            url,
                            headers={"User-Agent": USER_AGENT},
                            timeout=aiohttp.ClientTimeout(total=CRAWL_TIMEOUT),
                            allow_redirects=True,
                            ssl=False,
                        ) as response:
                            html = await response.text() if response.status == 200 else ""
                            return {
                                "url": url,
                                "html": html,
                                "status_code": response.status,
                                "final_url": str(response.url),
                                "redirect_chain": [str(r.url) for r in response.history],
                            }
                except Exception as e:
                    logger.error(f"Crawl error for {url}: {e}")
                    return {
                        "url": url, "html": "", "status_code": None,
                        "final_url": url, "redirect_chain": [], "error": str(e),
                    }

        tasks = [_fetch_one(u) for u in urls]
        results = await asyncio.gather(*tasks)

        for idx, result in enumerate(results):
            url = result["url"]
            html = result.get("html", "")

            page_data: Dict[str, Any] = {
                "html": html,
                "status_code": result.get("status_code"),
                "final_url": result.get("final_url", url),
                "redirect_chain": result.get("redirect_chain", []),
                "error": result.get("error"),
            }

            if html:
                soup = BeautifulSoup(html, "html.parser")

                # Meta title
                title_el = soup.find("title")
                page_data["meta_title"] = title_el.get_text(strip=True) if title_el else ""

                # Meta description
                desc_el = soup.find("meta", attrs={"name": "description"})
                page_data["meta_description"] = (
                    desc_el.get("content", "").strip() if desc_el else ""
                )

                # Main content text (fresh parse to avoid mutation)
                page_data["main_text"] = _extract_main_text(
                    BeautifulSoup(html, "html.parser")
                )

                # Images
                page_data["images"] = [
                    {"src": img.get("src", "").strip(), "alt": img.get("alt", "").strip()}
                    for img in soup.find_all("img")
                ]
            else:
                page_data.update({
                    "meta_title": "", "meta_description": "",
                    "main_text": "", "images": [],
                })

            self.pages[url] = page_data

            if progress_cb:
                progress_cb(idx + 1, len(urls))

        logger.info(f"Knowledge Base crawled {len(self.pages)} pages")

    # Phase 1b: Build FAISS index

    def build_faiss_index(self):
        """Build TF-IDF vectors + FAISS index from all crawled page content."""
        self.url_order = list(self.pages.keys())
        documents = [_clean_text(self.pages[u].get("main_text", "")) for u in self.url_order]

        if len(documents) < 2:
            logger.info("Less than 2 pages — skipping FAISS index")
            return

        if all(len(doc.split()) < 30 for doc in documents):
            logger.info("All pages have very short content — skipping FAISS index")
            return

        try:
            self.vectorizer = TfidfVectorizer(
                max_features=15000, min_df=1, stop_words="english"
            )
            tfidf_matrix = self.vectorizer.fit_transform(documents)
            self.vectors = tfidf_matrix.toarray().astype("float32")
            faiss.normalize_L2(self.vectors)

            self.faiss_index = faiss.IndexFlatIP(self.vectors.shape[1])
            self.faiss_index.add(self.vectors)

            logger.info(
                f"FAISS index built: {self.faiss_index.ntotal} vectors, "
                f"{self.vectors.shape[1]} dimensions"
            )
        except Exception as e:
            logger.error(f"FAISS index build error: {e}")

    # Query: SEARCH primitive uses this

    def query_similar(
        self,
        text: str,
        top_k: int = 10,
        threshold: float = None,
        exclude_url: str = None,
    ) -> List[Dict[str, Any]]:
        """
        Query FAISS index for pages similar to given text.
        Returns: [{"url": ..., "score": ..., "similarity_pct": ...}]
        """
        if threshold is None:
            threshold = SIMILARITY_THRESHOLD

        if not self.faiss_index or not self.vectorizer:
            return []

        cleaned = _clean_text(text)
        if not cleaned.strip():
            return []

        try:
            query_vec = self.vectorizer.transform([cleaned]).toarray().astype("float32")
            faiss.normalize_L2(query_vec)

            k = min(top_k + 1, self.faiss_index.ntotal)
            scores, indices = self.faiss_index.search(query_vec, k)

            matches = []
            for score, idx in zip(scores[0], indices[0]):
                if idx < 0 or idx >= len(self.url_order):
                    continue
                matched_url = self.url_order[idx]
                if exclude_url and matched_url.rstrip("/") == exclude_url.rstrip("/"):
                    continue
                if score >= threshold:
                    matches.append({
                        "url": matched_url,
                        "score": round(float(score), 3),
                        "similarity_pct": round(float(score) * 100, 1),
                    })

            return matches[:top_k]
        except Exception as e:
            logger.error(f"FAISS query error: {e}")
            return []

    # Post-crawl: Global similarity matrix

    def compute_similarity_matrix(
        self, threshold: float = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Compute pairwise similarity for all pages using the pre-built FAISS.
        Used by the Post-Crawl Reconciler (Node 5) for the global duplicate check.

        Returns: {url: {"duplicate_content": "Yes (0.XX)"|"No", "similar_urls": "..."}}
        """
        if threshold is None:
            threshold = SIMILARITY_THRESHOLD

        if not self.faiss_index or self.vectors is None:
            return {
                u: {"duplicate_content": "No", "similar_urls": ""}
                for u in self.url_order
            }

        results: Dict[str, Dict[str, Any]] = {}

        for i, url in enumerate(self.url_order):
            doc = _clean_text(self.pages[url].get("main_text", ""))
            if len(doc.split()) < 20:
                results[url] = {"duplicate_content": "No", "similar_urls": ""}
                continue

            scores, indices = self.faiss_index.search(
                self.vectors[i].reshape(1, -1), min(10, len(self.url_order))
            )

            cluster = []
            for score, idx in zip(scores[0], indices[0]):
                if idx == i:
                    continue
                if score >= threshold:
                    cluster.append((idx, round(float(score), 2)))

            if not cluster:
                results[url] = {"duplicate_content": "No", "similar_urls": ""}
                continue

            best_score = max(s for _, s in cluster)
            similar = [
                f"{self.url_order[idx]} ({score:.2f} – {_severity(score)})"
                for idx, score in cluster
            ]
            results[url] = {
                "duplicate_content": f"Yes ({best_score:.2f})",
                "similar_urls": " | ".join(similar),
            }

        return results

    # Accessors

    def get_page_html(self, url: str) -> str:
        """Get pre-crawled HTML for a URL."""
        return self.pages.get(url, {}).get("html", "")

    def get_page_data(self, url: str) -> Dict[str, Any]:
        """Get all extracted data for a URL."""
        return self.pages.get(url, {})

    def get_all_page_data(self) -> List[Dict[str, Any]]:
        """Get page data for all URLs (for postcrawl duplicate detection)."""
        return [
            {
                "url": url,
                "text": data.get("main_text", ""),
                "meta_title": data.get("meta_title", ""),
                "meta_description": data.get("meta_description", ""),
                "images": data.get("images", []),
            }
            for url, data in self.pages.items()
        ]


# Global singleton

_kb: Optional[KnowledgeBase] = None


def get_knowledge_base() -> Optional[KnowledgeBase]:
    """Get the global Knowledge Base instance."""
    return _kb


def set_knowledge_base(kb: KnowledgeBase):
    """Set the global Knowledge Base instance."""
    global _kb
    _kb = kb
