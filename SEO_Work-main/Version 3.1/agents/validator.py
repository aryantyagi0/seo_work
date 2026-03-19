import json
import os
from typing import Dict, Any, List
from graph.state import AuditMap, AuditStatus
from chatbot.explanation import ExplanationAgent 


class ValidatorAgent:
    def __init__(self, kb_path=None):
        if kb_path is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            kb_path = os.path.join(base_dir, '..', 'kb', 'criteria.json') 
        self.kb_path = kb_path
        self.criteria = self._load_criteria()
        self.explanation_agent = ExplanationAgent() 
    
    def _status_value(self, status: Any) -> str:
        if hasattr(status, "value"):
            return str(status.value)
        return str(status)

    def _load_criteria(self):
        with open(self.kb_path, 'r') as f:
            return json.load(f)


    def validate_page(self, audit_map: AuditMap, url: str):
        """
        Validates extracted parameters for a given URL. If critical data is missing
        after initial extraction, it marks the parameter for fallback.
        """
        page_state = audit_map.get_page_state(url)
        if not page_state:
            print(f"Error: Page state not found for URL: {url}. Cannot validate.")
            return

        # Define checks for critical parameters that must have a value
        # to avoid triggering fallback for non-essential missing elements.
        critical_params = {
            "meta_title", "meta_description", "heading_tags", "canonical_tag"
        }

        for param_name, param_state in page_state.parameters.items():
            if self._status_value(param_state.status) in [
                AuditStatus.VALIDATED.value,
                AuditStatus.SKIPPED.value,
                AuditStatus.REQUIRES_FALLBACK_TOOL.value,
                AuditStatus.FALLBACK_NEEDED.value,
            ]:
                continue
            
            # If the parameter is critical and its value is empty/null or status is FAILED, mark for fallback
            if param_name in critical_params:
                value = param_state.value
                is_empty = value is None or value == "" or value == [] or value == {} or value == "N/A"

                # Special check for heading_tags which might be a dict
                if param_name == "heading_tags" and isinstance(value, dict):
                    if not any(value.get(key) for key in ["h1_content", "h2_content", "h3_content"]):
                        is_empty = True
                
                if is_empty or self._status_value(param_state.status) == AuditStatus.FAILED.value:
                    print(f"Validation failed or insufficient for '{param_name}' on {url}: Status {param_state.status.value}, Value empty: {is_empty}. Marking for fallback.")
                    audit_map.update_parameter_state(
                        url, param_name,
                        status=AuditStatus.FALLBACK_NEEDED,
                        remediation_suggestion=f"Initial extraction yielded a failed status or empty value for critical parameter '{param_name}'.",
                        llm_reasoning=f"The critical SEO parameter '{param_name}' was either missing or failed during the standard HTML parse. This often happens with client-side rendered content."
                    )
                    continue

            # Placeholder for future modular validation logic
            if self._status_value(param_state.status) == AuditStatus.EXTRACTED.value and param_name in self.criteria:
                # The modular tools now handle validation internally. This block can be used for cross-parameter validation in the future.
                # For now, we accept the status from the DispatcherAgent.
                pass
        
        print(f"Validation checks completed for {url}.")
