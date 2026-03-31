from typing import Dict, Any
import json

class ExplanationAgent:
    def __init__(self):
        pass

    def generate_explanation(self, url: str, param_name: str, value: Any, rule: Dict[str, Any]) -> str:
        """Formats a concise explanation for a failed parameter using structured data."""
        validation_type = rule.get("validation_type", "unknown")
        validation_params = rule.get("validation_params", {})
        static_remediation = rule.get("remediation", "No specific remediation suggestion.")
        value_str = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
        return (
            f"URL: {url}. Parameter: {param_name}. "
            f"Validation type: {validation_type}. "
            f"Extracted value: {value_str}. "
            f"Rule: {json.dumps(validation_params)}. "
            f"Remediation: {static_remediation}"
        )

    def format_parameter_detail(self, url: str, param_name: str, param_state: Any) -> str:
        """Formats a parameter detail response from structured state, enforcing zero-hallucination."""
        
        SENSITIVE_PARAMETERS = [
            "meta_title", "meta_description", "image_alt_text", 
            "heading_tags", "word_count", "canonical_tag"
        ]

        value = param_state.value
        
        # Check for missing or empty values for sensitive parameters
        is_truly_missing = value is None or (isinstance(value, (str, list, dict)) and not value) or value == "N/A"
        
        if param_name in SENSITIVE_PARAMETERS and is_truly_missing:
            # Provide an explicit 'None' to avoid LLM length hallucinations on error messages
            value_display = "None"
        else:
            value_display = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
            # Truncate long string values for readability if not already empty/missing
            if isinstance(value_display, str) and len(value_display) > 500:
                value_display = value_display[:500] + "..." # Truncate to avoid overly long responses

        lines = [
            f"Audit Details for {url}",
            f"Parameter: {param_name}",
            f"Status: {param_state.status.value.upper()}",
            f"Value: {value_display}"
        ]
        if param_state.llm_reasoning:
            lines.append(f"Insight: {param_state.llm_reasoning}")
        return "\n".join(lines)
