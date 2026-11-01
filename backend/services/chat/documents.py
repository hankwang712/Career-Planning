"""Compatibility imports; resume parsing is owned by services.resume."""

from ..resume.documents import ResumeDocuments, redact_contacts

__all__ = ["ResumeDocuments", "redact_contacts"]
