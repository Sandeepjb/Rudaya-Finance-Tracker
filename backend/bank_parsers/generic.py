from .base import BaseParser


class GenericParser(BaseParser):
    """Fallback for unknown banks: broad patterns, never scores on bank identity."""
    name = "generic"
    bank_name = "Unknown Bank"
    narration_patterns = (
        r"(?:Info|Information|Remarks?|Desc(?:ription)?|Particulars|Narration)\s*[:\-]\s*([^\.]+?)(?:\.\s|\.$|$)",
        r"(?:towards|for)\s+([^\.]+?)(?:\.\s|\.$|\sRef|\sAvl|\son\s\d|$)",
        r"\b(?:to|from|at|by)\s+(?!a/c|A/c|account|your|the\b)([^\.\(]+?)(?:\s*\(|\.\s|\.$|\son\s\d|\sRef|$)",
    )

    def matches(self, ctx):
        return 1
