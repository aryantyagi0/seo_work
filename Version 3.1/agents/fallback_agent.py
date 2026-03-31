from graph.state import AuditMap, AuditStatus

class FallbackAgent:
    def __init__(self):
        pass

    def _status_value(self, status):
        if hasattr(status, "value"):
            return str(status.value)
        return str(status)

    def check_for_fallback(self, audit_map: AuditMap):
        """
        Identifies parameters marked as FALLBACK_NEEDED and updates their status.
        For the boilerplate, this is a simple placeholder.
        """
        print("\n--- FallbackAgent checking for required fallbacks ---")
        for url, page_state in audit_map.pages.items():
            for param_name, param_state in page_state.parameters.items():
                status_val = self._status_value(param_state.status)
                remediation = (param_state.remediation_suggestion or "").lower()
                failed_fetch = status_val == AuditStatus.FAILED.value and any(
                    phrase in remediation for phrase in ["failed to fetch html", "error fetching url", "failed to fetch", "timeout"]
                )
                if status_val == AuditStatus.FALLBACK_NEEDED.value or failed_fetch:
                    print(f"  Fallback identified for '{param_name}' on {url}. "
                          f"Reason: {param_state.remediation_suggestion}")
                    
                    audit_map.update_parameter_state(
                        url, param_name,
                        status=AuditStatus.REQUIRES_FALLBACK_TOOL,
                        remediation_suggestion=f"Advanced tool needed. Original reason: {param_state.remediation_suggestion}"
                    )
                    print(f"  -> Marked '{param_name}' as REQUIRES_FALLBACK_TOOL.")
        print("--- FallbackAgent finished ---")
