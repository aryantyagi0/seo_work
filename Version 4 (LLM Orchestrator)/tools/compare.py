"""
COMPARE Primitive: Boolean comparisons with intelligent type handling
"""
from typing import Any
from utils.logging_config import get_logger

logger = get_logger("COMPARE")


def _extract_comparable_value(value: Any) -> Any:
    """
    Extract a comparable scalar value from complex types.
    
    Handles: dict -> return length or first numeric value
    list -> return length, str -> try to parse as number
    numeric -> return as-is
    """
    if isinstance(value, dict):
        # Try to find numeric value in dict
        for key in ["count", "length", "size", "value", "score"]:
            if key in value and isinstance(value[key], (int, float)):
                return value[key]
        # Otherwise return dict length
        return len(value)
    
    elif isinstance(value, list):
        return len(value)
    
    elif isinstance(value, str):
        # Try to parse as number
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            return value
    
    return value


async def compare(value1: Any, value2: Any, operator: str) -> bool:
    """
    Compare two values with intelligent type handling
    
    Args:
        value1: First value (can be dict, list, str, int, float)
        value2: Second value
        operator: "==", "!=", ">", "<", ">=", "<=", "contains", "startswith", "matches_regex"
    
    Returns:
        Boolean result
    """
    try:
        # String-based operators
        if operator in ["contains", "startswith", "matches_regex"]:
            if operator == "contains":
                return str(value2) in str(value1)
            elif operator == "startswith":
                return str(value1).startswith(str(value2))
            elif operator == "matches_regex":
                import re
                return bool(re.search(str(value2), str(value1)))
        
        # Numeric/scalar comparisons - extract comparable values
        v1 = _extract_comparable_value(value1)
        v2 = _extract_comparable_value(value2)
        
        # Try to ensure same types for comparison
        if isinstance(v2, (int, float)) and isinstance(v1, str):
            try:
                v1 = float(v1) if "." in v1 else int(v1)
            except ValueError:
                pass
        
        if isinstance(v1, (int, float)) and isinstance(v2, str):
            try:
                v2 = float(v2) if "." in v2 else int(v2)
            except ValueError:
                pass
        
        if operator == "==":
            return v1 == v2
        elif operator == "!=":
            return v1 != v2
        elif operator == ">":
            return v1 > v2
        elif operator == "<":
            return v1 < v2
        elif operator == ">=":
            return v1 >= v2
        elif operator == "<=":
            return v1 <= v2
        elif operator == "in":
            # Check if value1 is contained in value2 (collection membership)
            if isinstance(value2, (list, tuple, set)):
                return value1 in value2
            elif isinstance(value2, str):
                return str(value1) in value2
            elif isinstance(value2, dict):
                return value1 in value2
            return str(value1) in str(value2)
        elif operator == "not_in":
            # Check if value1 is not in value2
            if isinstance(value2, (list, tuple, set)):
                return value1 not in value2
            elif isinstance(value2, str):
                return str(value1) not in value2
            return str(value1) not in str(value2)
        else:
            logger.warning(f"Unknown operator: {operator}")
            return False
    
    except TypeError as e:
        logger.error(f"COMPARE type error: {type(value1)} {operator} {type(value2)} - {e}")
        return False
    except Exception as e:
        logger.error(f"COMPARE error: {e}")
        return False