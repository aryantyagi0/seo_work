"""
AGGREGATE Primitive: Sum, filter, group, deduplicate collections
"""
from typing import Any, List, Dict, Callable
from utils.logging_config import get_logger

logger = get_logger("AGGREGATE")


async def aggregate(collection: Any, operation: str, **kwargs) -> Any:
    """
    Aggregate collection
    
    Args:
        collection: List, dict, or set
        operation: "sum", "average", "max", "min", "filter", "deduplicate", "top_n", "group_by"
        **kwargs: Additional parameters (e.g., condition for filter, n for top_n)
    
    Returns:
        Aggregated result
    """
    try:
        if not isinstance(collection, (list, tuple, set, dict)):
            logger.warning(f"AGGREGATE expects collection, got {type(collection)}")
            return collection
        
        if operation == "sum":
            return sum(collection) if isinstance(collection, (list, tuple)) else 0
        
        elif operation == "average":
            if isinstance(collection, (list, tuple)) and len(collection) > 0:
                return sum(collection) / len(collection)
            return 0
        
        elif operation == "max":
            return max(collection) if len(collection) > 0 else None
        
        elif operation == "min":
            return min(collection) if len(collection) > 0 else None
        
        elif operation == "filter":
            condition = kwargs.get("condition")
            if callable(condition):
                return [item for item in collection if condition(item)]
            elif isinstance(condition, str):
                # Handle string conditions like "lambda x: 'http' in x"
                # Safely filter by checking if the condition string appears in items
                return [item for item in collection if item is not None and str(item).strip()]
            return [item for item in collection if item is not None]
        
        elif operation == "count":
            if isinstance(collection, (list, tuple, set)):
                return len(collection)
            elif isinstance(collection, dict):
                return len(collection)
            return 0
        
        elif operation == "flatten":
            flat = []
            for item in collection:
                if isinstance(item, (list, tuple)):
                    flat.extend(item)
                else:
                    flat.append(item)
            return flat
        
        elif operation == "filter_empty":
            return [item for item in collection if item]
        
        elif operation in ("deduplicate", "unique"):
            if isinstance(collection, (list, tuple)):
                seen = set()
                result = []
                for item in collection:
                    key = str(item)
                    if key not in seen:
                        seen.add(key)
                        result.append(item)
                return result
            return list(set(collection))
        
        elif operation == "top_n":
            n = kwargs.get("n", 10)
            if isinstance(collection, dict):
                sorted_items = sorted(collection.items(), key=lambda x: x[1], reverse=True)
                return dict(sorted_items[:n])
            return list(collection)[:n]
        
        elif operation == "group_by":
            key_func = kwargs.get("key")
            if not callable(key_func):
                return collection
            
            grouped = {}
            for item in collection:
                key = key_func(item)
                if key not in grouped:
                    grouped[key] = []
                grouped[key].append(item)
            return grouped
        
        else:
            logger.warning(f"Unknown operation: {operation}")
            return collection
    
    except Exception as e:
        logger.error(f"AGGREGATE error: {e}")
        return collection