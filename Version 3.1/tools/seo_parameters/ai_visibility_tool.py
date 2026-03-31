import logging
import re
from langchain_core.tools import tool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def analyze_ai_visibility_tool(page_text_content: str, llm_model_name: str | None = None, criteria: dict = None) -> dict:
    """
    Rule-based AI visibility checks:
    - Conversational tone
    - Citations / statistics
    - First-hand experience signals
    """
    if criteria is None:
        criteria = {}
    if not page_text_content:
        return {"status": "error", "message": "No text content provided for AI Visibility analysis.", "details": {"reason": "missing_text"}}

    text = page_text_content.lower()

    conversational_pattern = criteria.get("conversational_pattern", r"\b(you|we|our|your)\b")
    citations_pattern = criteria.get("citations_pattern", r"\b\d+(\.\d+)?%?\b")
    first_hand_phrases = criteria.get("first_hand_phrases", ["i ", "my ", "we ", "our experience", "we tested", "we found"])
    min_score = int(criteria.get("min_score", 2))

    conversational = bool(re.search(conversational_pattern, text)) or "?" in text
    citations_or_stats = bool(re.search(citations_pattern, text)) or "http" in text or "source" in text
    first_hand = any(phrase in text for phrase in first_hand_phrases)

    score = sum([conversational, citations_or_stats, first_hand])
    status = "pass" if score >= min_score else "needs_improvement"

    return {
        "status": status,
        "message": "AI visibility checks completed.",
        "details": {
            "conversational": conversational,
            "citations_or_stats": citations_or_stats,
            "first_hand_experience": first_hand,
            "score": score,
            "min_score": min_score,
        },
    }

