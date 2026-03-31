from typing import Dict, Any, Union, List

def calculate_seo_length(text: Union[str, List[str]]) -> Dict[str, Any]:
    """
    Calculates the exact character count of provided string(s).
    """
    if isinstance(text, list):
        results = []
        for t in text:
            results.append({
                "text": t,
                "character_count": len(str(t))
            })
        return {
            "results": results,
            "is_batch": True,
            "status": "exact_calculation"
        }
    
    return {
        "text": text,
        "character_count": len(str(text)),
        "is_batch": False,
        "status": "exact_calculation"
    }
