from .base import BaseParser


class SaraswatParser(BaseParser):
    name = "saraswat"
    bank_name = "Saraswat Bank"
    keywords = ("saraswat", "saraswatbank")
    sender_keywords = ("saraswat",)
    narration_patterns = (
        r"(?:for|towards|Info|Desc(?:ription)?|Particulars)\s*[:\-]?\s*([^\.]+?)(?:\.\s|\.$|\sRef|\sAvl|$)",
        r"\b(?:to|from)\s+(?!a/c|A/c|account|your)([^\.]+?)(?:\.\s|\.$|\sRef|\sAvl|$)",
    )
