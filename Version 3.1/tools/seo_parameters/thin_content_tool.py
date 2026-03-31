import re
import logging
from langchain_core.tools import tool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def check_thin_content_tool(text_content: str, min_words: int = 100) -> dict:
    """
    Analyzes content for 'thinness' based on word count.
    
    Args:
        text_content: The clean, visible text content of the page.
        min_words: The minimum number of words considered acceptable for substantial content.
                   Defaults to 250.
                   
    Returns:
        A dictionary with status, message, and the word count.
    """
    if not text_content:
        return {"status": "error", "message": "No text content provided for thin content analysis.", "word_count": 0}

    words = re.findall(r'\b\w+\b', text_content)
    word_count = len(words)
    
    if word_count < min_words:
        return {
            "status": "warning",
            "message": f"Content is thin. Only {word_count} words found. Recommended minimum: {min_words} words.",
            "word_count": word_count,
            "grammar_check": "not_evaluated",
        }
    return {
        "status": "success",
        "message": f"Content is not thin. {word_count} words found.",
        "word_count": word_count,
        "grammar_check": "not_evaluated",
    }

