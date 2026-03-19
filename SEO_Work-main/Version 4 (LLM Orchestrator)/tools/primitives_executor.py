"""
Primitive Chain Executor
Executes a sequence of primitive operations with variable passing
"""
from typing import List, Dict, Any
from utils.logging_config import get_logger
from tools.fetch import fetch
from tools.select import select
from tools.extract import extract
from tools.measure import measure
from tools.compare import compare
from tools.transform import transform
from tools.aggregate import aggregate
from tools.search import search
from tools.validate import validate
from tools.reason import reason

logger = get_logger("PrimitivesExecutor")


PRIMITIVE_REGISTRY = {
    "FETCH": fetch,
    "SELECT": select,
    "EXTRACT": extract,
    "MEASURE": measure,
    "COMPARE": compare,
    "TRANSFORM": transform,
    "AGGREGATE": aggregate,
    "SEARCH": search,
    "VALIDATE": validate,
    "REASON": reason,
}


async def execute_primitive_chain(
    operations: List[Dict[str, Any]],
    intermediate_vars: Dict[str, Any],
    faiss_results: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Execute a chain of primitive operations
    
    operations: List of {op: "PRIMITIVE_NAME", params: {...}, output: "var_name"}
    intermediate_vars: Existing variables from previous executions
    faiss_results: Global FAISS similarity data
    
    Returns: {
        status: "...",
        raw_data: {...},
        new_vars: {...}  # New variables created during execution
    }
    """
    logger.info(f"Executing chain of {len(operations)} operations")
    
    # Local execution context (copy of intermediate vars)
    context = intermediate_vars.copy()
    context["faiss_results"] = faiss_results
    
    new_vars = {}
    results = {}
    
    for idx, operation in enumerate(operations, 1):
        op_name = operation.get("op")
        params = operation.get("params", {})
        output_var = operation.get("output")
        
        if op_name not in PRIMITIVE_REGISTRY:
            logger.error(f"Unknown primitive: {op_name}")
            results["error"] = f"Unknown primitive: {op_name}"
            break
        
        # Resolve $variable references in params
        resolved_params = _resolve_params(params, context)
        
        try:
            # Execute primitive
            primitive_func = PRIMITIVE_REGISTRY[op_name]
            result = await primitive_func(**resolved_params)
            
            # Store result in context
            if output_var:
                context[output_var] = result
                new_vars[output_var] = result
            
            logger.info(f"[{idx}/{len(operations)}] {op_name} → {output_var}")
        
        except Exception as e:
            logger.error(f"Error in {op_name}: {e}")
            results["error"] = f"{op_name}: {str(e)}"
            break
    
    # Build final result
    results["raw_data"] = {k: v for k, v in context.items() if k in new_vars}
    results["new_vars"] = new_vars
    results["status"] = "Completed" if "error" not in results else "Error"
    
    return results


def _resolve_params(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resolve $variable references in params (recursively for nested dicts).
    Example: {"text": "$title_text"} → {"text": "Actual Title"}
    Also handles URL construction with domain substitution.
    """
    resolved = {}
    current_url = context.get("current_url", "")
    
    # Extract domain from current_url for URL construction
    domain = ""
    if current_url:
        from urllib.parse import urlparse
        parsed = urlparse(current_url)
        domain = f"{parsed.scheme}://{parsed.netloc}"
    
    for key, value in params.items():
        if isinstance(value, str):
            if value.startswith("$"):
                var_name = value[1:]  # Remove $
                resolved[key] = context.get(var_name)
            elif domain and key == "url":
                # Replace placeholder domains in URLs with actual domain
                if "example.com" in value or "domain.com" in value:
                    from urllib.parse import urlparse as up2
                    parsed_val = up2(value)
                    resolved[key] = f"{domain}{parsed_val.path}"
                else:
                    resolved[key] = value
            else:
                resolved[key] = value
        elif isinstance(value, dict):
            # Recursively resolve $variables in nested dicts
            resolved[key] = _resolve_params(value, context)
        elif isinstance(value, list):
            # Resolve $variables in list items
            resolved_list = []
            for item in value:
                if isinstance(item, str) and item.startswith("$"):
                    resolved_list.append(context.get(item[1:]))
                elif isinstance(item, dict):
                    resolved_list.append(_resolve_params(item, context))
                else:
                    resolved_list.append(item)
            resolved[key] = resolved_list
        else:
            resolved[key] = value
    
    return resolved