import logging
import re
from langchain_core.tools import tool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def analyze_heading_text_tool(h1_content: list[str], h2_content: list[str], h3_content: list[str], llm_model_name: str | None = None) -> dict:
    """
    Rule-based analysis of heading text quality:
    - Question-based headings (presence of '?')
    - Keyword + intent alignment (H2/H3 sharing terms with H1)
    """
    all_headings = h1_content + h2_content + h3_content
    if not all_headings:
        return {"status": "info", "message": "No heading tags provided for analysis."}

    def _tokens(text: str) -> set:
        return set(re.findall(r"\b\w+\b", text.lower()))

    question_based = any(h.strip().endswith("?") for h in all_headings)

    h1_tokens = _tokens(h1_content[0]) if h1_content else set()
    supporting = 0
    total_supporting = len(h2_content) + len(h3_content)

    if h1_tokens:
        for h in h2_content + h3_content:
            if _tokens(h) & h1_tokens:
                supporting += 1

    alignment_ratio = (supporting / total_supporting) if total_supporting else 0.0
    aligned = alignment_ratio >= 0.3 if total_supporting else bool(h1_tokens)

    status = "pass" if question_based and aligned else "needs_improvement"
    message_parts = []
    message_parts.append("Question-based headings detected." if question_based else "No question-based headings detected.")
    message_parts.append(
        f"Heading alignment ratio: {alignment_ratio:.0%}."
        if total_supporting
        else "No H2/H3 headings available to assess alignment."
    )

    return {
        "status": status,
        "message": " ".join(message_parts),
        "details": {
            "question_based": question_based,
            "alignment_ratio": alignment_ratio,
            "h1_count": len(h1_content),
            "h1_content": h1_content,
            "h2_count": len(h2_content),
            "h2_content": h2_content,
            "h3_count": len(h3_content),
            "h3_content": h3_content,
        },
    }

