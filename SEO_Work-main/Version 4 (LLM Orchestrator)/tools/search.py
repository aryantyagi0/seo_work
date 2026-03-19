"""
SEARCH Primitive (P8): Query the FAISS Knowledge Base for similar content.

Uses the pre-built FAISS Central Truth index from KnowledgeBase (Node 1).
Falls back gracefully when KB isn't available yet.
"""
from typing import Any, List, Dict
from utils.logging_config import get_logger

logger = get_logger("SEARCH")


async def search(query: Any, corpus: str = "all_texts", method: str = "semantic",
                 **kwargs) -> List[Dict[str, Any]]:
    """
    Search the FAISS Knowledge Base for similar content.

    Args:
        query:  Text to search for (str, list, or dict)
        corpus: Ignored — FAISS indexes all content
        method: "semantic" (cosine ≥ 0.50) or "exact" (cosine ≥ 0.80)
        **kwargs: Optional 'exclude_url' to skip current page

    Returns:
        List of matches: [{"url": ..., "score": ..., "similarity_pct": ...}]
    """
    try:
        from tools.knowledge_base import get_knowledge_base
        kb = get_knowledge_base()

        if not kb or not kb.faiss_index:
            logger.info("SEARCH: No FAISS index available yet")
            return []

        # Convert query to text
        if isinstance(query, str):
            query_text = query
        elif isinstance(query, list):
            query_text = " ".join(str(q) for q in query if q)
        elif isinstance(query, dict):
            query_text = str(query)
        else:
            query_text = str(query) if query else ""

        if not query_text.strip():
            return []

        # Threshold depends on method
        threshold = 0.50 if method == "semantic" else 0.80
        exclude_url = kwargs.get("exclude_url")

        matches = kb.query_similar(
            text=query_text,
            top_k=10,
            threshold=threshold,
            exclude_url=exclude_url,
        )

        logger.info(
            f"SEARCH FAISS: {method} → {len(matches)} matches "
            f"(threshold={threshold})"
        )
        return matches

    except Exception as e:
        logger.error(f"SEARCH error: {e}")
        return []