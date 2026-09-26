"""Pluggable bank-alert parsers. Each parser exposes `matches(ctx) -> int score` and `parse(ctx) -> dict`."""
from .base import ParseContext, ParseResult, BaseParser, parse_any_date, parse_amount
from .registry import select_parser, PARSERS, parse_alert, selection_detail

__all__ = ["ParseContext", "ParseResult", "BaseParser", "parse_any_date", "parse_amount",
           "select_parser", "PARSERS", "parse_alert"]
