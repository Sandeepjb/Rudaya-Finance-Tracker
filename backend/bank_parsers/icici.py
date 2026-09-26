from .base import BaseParser


class IciciParser(BaseParser):
    name = "icici"
    bank_name = "ICICI Bank"
    keywords = ("icici", "icicibank", "ibanking")
    sender_keywords = ("icici",)
    narration_patterns = (
        r"(?:Info|Information|Remarks?|Desc(?:ription)?)\s*[:\-]\s*([^\.]+?)(?:\.\s|\.$|\sThe\s|\sAvl|\sAvailable|$)",
        r"(?:towards|for)\s+([^\.]+?)(?:\.\s|\.$|\sThe\s|\sAvl|\sAvailable|\sRef|$)",
        r"\bto\s+(?!your|the\b)([^\.]+?)(?:\.\s|\.$|\sThe\s|\sAvl|\sRef|\son\s|$)",
    )
