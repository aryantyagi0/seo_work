from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, List, Any

class AuditStatus(Enum):
    PENDING = "pending"
    EXTRACTED = "extracted"
    VALIDATED = "validated"
    FAILED = "failed"
    FALLBACK_NEEDED = "fallback_needed"
    REQUIRES_FALLBACK_TOOL = "requires_fallback_tool"
    SKIPPED = "skipped" 

@dataclass
class AuditParameterState:
    value: Optional[str] = None
    status: AuditStatus = AuditStatus.PENDING
    validation_result: Optional[bool] = None 
    remediation_suggestion: Optional[str] = None
    llm_reasoning: Optional[str] = None 
    
    def to_dict(self):
        return {
            "value": self.value,
            "status": self.status.value,
            "validation_result": self.validation_result,
            "remediation_suggestion": self.remediation_suggestion,
            "llm_reasoning": self.llm_reasoning,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        return cls(
            value=data.get("value"),
            status=AuditStatus(data["status"]) if "status" in data else AuditStatus.PENDING,
            validation_result=data.get("validation_result"),
            remediation_suggestion=data.get("remediation_suggestion"),
            llm_reasoning=data.get("llm_reasoning"),
        )

@dataclass
class PageAuditState:
    url: str
    parameters: Dict[str, AuditParameterState] = field(default_factory=dict)

    def to_dict(self):
        return {
            "url": self.url,
            "parameters": {name: state.to_dict() for name, state in self.parameters.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        return cls(
            url=data["url"],
            parameters={name: AuditParameterState.from_dict(p_data) for name, p_data in data["parameters"].items()}
        )

@dataclass
class AuditMap:
    pages: Dict[str, PageAuditState] = field(default_factory=dict)

    def add_page(self, url: str, audit_criteria: List[str]):
        """Adds a new page to the audit map and initializes its parameters based on audit_criteria."""
        if url not in self.pages:
            self.pages[url] = PageAuditState(url=url)
            for param_name in audit_criteria:
                self.pages[url].parameters[param_name] = AuditParameterState()

    def get_page_state(self, url: str) -> Optional[PageAuditState]:
        return self.pages.get(url)

    def update_parameter_state(self, url: str, param_name: str, **kwargs):
        """Updates the state of a specific parameter for a given URL."""
        if url in self.pages and param_name in self.pages[url].parameters:
            param_state = self.pages[url].parameters[param_name]
            for key, value in kwargs.items():
                setattr(param_state, key, value)
        else:
            pass

    def get_parameter_status(self, url: str, param_name: str) -> Optional[AuditStatus]:
        if url in self.pages and param_name in self.pages[url].parameters:
            return self.pages[url].parameters[param_name].status
        return None

    def to_dict(self):
        return {
            "pages": {url: page.to_dict() for url, page in self.pages.items()}
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        return cls(
            pages={url: PageAuditState.from_dict(p_data) for url, p_data in data["pages"].items()}
        )

