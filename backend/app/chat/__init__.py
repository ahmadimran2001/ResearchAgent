"""Persistent desktop chat services."""

from .phi_eval import PHI_RESEARCH_EVAL, evaluate_phi_research
from .policy import SYSTEM_POLICY
from .service import ChatService
from .tools import ResearchToolRouter, evidence_context

__all__ = [
    "PHI_RESEARCH_EVAL",
    "SYSTEM_POLICY",
    "ChatService",
    "ResearchToolRouter",
    "evaluate_phi_research",
    "evidence_context",
]
