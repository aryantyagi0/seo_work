import re
import logging
from langchain_core.tools import tool
from collections import Counter

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

STOPWORDS = {
    "i","me","my","myself","we","our","ours","ourselves","you","your","yours",
    "yourself","yourselves","he","him","his","himself","she","her","hers",
    "herself","it","its","itself","they","them","their","theirs","themselves",
    "what","which","who","whom","this","that","these","those","am","is","are",
    "was","were","be","been","being","have","has","had","having","do","does",
    "did","doing","a","an","the","and","but","if","or","because","as","until",
    "while","of","at","by","for","with","about","against","between","into",
    "through","during","before","after","above","below","to","from","up","down",
    "in","out","on","off","over","under","again","further","then","once","here",
    "there","when","where","why","how","all","any","both","each","few","more",
    "most","other","some","such","no","nor","not","only","own","same","so",
    "than","then","too","very","s","t","can","will","just","don","should","now"
}

@tool
async def analyze_keyword_density_tool(
    text_content: str,
    keywords: list[str] | None = None,
    min_density: float = 0.03,
    max_density: float = 0.05,
    max_keywords: int = 5,
) -> dict:
    """
    Calculates keyword density for specified keywords in a given text content.
    
    Args:
        text_content: The clean, visible text content of the page.
        keywords: A list of keywords (strings) to analyze density for.
        min_density: The minimum recommended keyword density as a float (e.g., 0.01 for 1%).
        max_density: The maximum recommended keyword density as a float (e.g., 0.05 for 5%).
        
    Returns:
        A dictionary with overall status, message, and detailed density for each keyword.
    """
    if not text_content:
        return {"status": "error", "message": "No text content provided for keyword density analysis."}

    words = re.findall(r'\b\w+\b', text_content.lower())
    non_stop_words = [w for w in words if w not in STOPWORDS]
    word_count = len(non_stop_words)
    
    if word_count == 0:
        return {"status": "info", "message": "No words found in content for density analysis.", "details": {}}

    if not keywords:
        counts = Counter(non_stop_words)
        keywords = [w for w, _ in counts.most_common(max_keywords)]

    density_results = {}
    out_of_range = 0
    
    for keyword in keywords:
        keyword_lower = keyword.lower()
        keyword_count = non_stop_words.count(keyword_lower)
        density = (keyword_count / word_count) if word_count > 0 else 0
        
        status = "success"
        message = f"Density: {density:.2%}"
        
        if density < min_density or density > max_density:
            status = "warning"
            message += f" (Outside recommended range {min_density:.2%}-{max_density:.2%})"
            out_of_range += 1
            
        density_results[keyword] = {
            "density": density,
            "status": status,
            "message": message,
            "count": keyword_count,
        }

    assessment = "no_improvement_needed" if out_of_range == 0 else "needs_improvement"
    overall_status = "success" if assessment == "no_improvement_needed" else "warning"

    return {
        "overall_status": overall_status,
        "message": "Keyword density analysis complete.",
        "details": density_results,
        "assessment": assessment,
        "word_count_non_stop": word_count,
    }

