from .base import BaseParser


class HdfcParser(BaseParser):
    name = "hdfc"
    version = "1.1"
    bank_name = "HDFC Bank"
    keywords = ("hdfc", "hdfcbank", "18002586161")
    sender_keywords = ("hdfc",)
    narration_patterns = (
        # NEFT/IMPS/RTGS structured info: "for NEFT Cr-HDFC0000001-ACME PVT LTD-RUDAYA-HDFCN12345678"
        r"\bfor\s+((?:NEFT|IMPS|RTGS|UPI)[^\.]+?)(?:\.\s|\.$|\sRef|\sAvl|$)",
        r"\bto\s+(?!your|the\b)(?:VPA\s+)?([^\.\(]+?)(?:\s*\(|\.\s|\.$|\son\s\d|$)",
        r"\b(?:by|from)\s+(?!a/c|A/c|account)([^\.\(]+?)(?:\s*\(|\.\s|\.$|\son\s\d|$)",
        r"\bat\s+([^\.\(]+?)(?:\s*\(|\.\s|\.$|\son\s\d|$)",
        r"(?:towards|for|Info)\s*[:\-]?\s*([^\.\(]+?)(?:\s*\(|\.\s|\.$|$)",
    )
