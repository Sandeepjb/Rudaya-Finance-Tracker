from .base import BaseParser


class HdfcParser(BaseParser):
    name = "hdfc"
    bank_name = "HDFC Bank"
    keywords = ("hdfc", "hdfcbank", "18002586161")
    sender_keywords = ("hdfc",)
    narration_patterns = (
        r"\bto\s+(?!your|the\b)(?:VPA\s+)?([^\.\(]+?)(?:\s*\(|\.\s|\.$|\son\s\d|$)",
        r"\b(?:by|from)\s+(?!a/c|A/c|account)([^\.\(]+?)(?:\s*\(|\.\s|\.$|\son\s\d|$)",
        r"(?:towards|for|Info)\s*[:\-]?\s*([^\.\(]+?)(?:\s*\(|\.\s|\.$|$)",
    )
