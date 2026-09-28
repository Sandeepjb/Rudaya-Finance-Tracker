from typing import List, Optional
from .base import ParseContext, ParseResult
from .icici import IciciParser
from .hdfc import HdfcParser
from .saraswat import SaraswatParser
from .generic import GenericParser

PARSERS = [IciciParser(), HdfcParser(), SaraswatParser(), GenericParser()]


def select_parser(ctx: ParseContext) -> tuple:
    """Strategy: bank hint (+100) > trusted sender (+50) > subject (+15) > body keywords (+10 each) > generic (1)."""
    scored = sorted(((p.matches(ctx), p) for p in PARSERS), key=lambda t: -t[0])
    return scored[0][1], scored[0][0]


def identify_bank(ctx: ParseContext) -> str:
    """Parser name of the bank the message belongs to ('' when no bank-specific parser matches)."""
    parser, score = select_parser(ctx)
    return parser.name if parser.name != "generic" and score > 0 else ""


def selection_detail(ctx: ParseContext) -> dict:
    parser, score = select_parser(ctx)
    _, methods = parser.match_detail(ctx)
    conf = 0 if parser.name == "generic" else min(100, 40 + 20 * len(methods) + (20 if score >= 100 else 0))
    return {"selected_parser": parser.name, "selection_method": "+".join(methods) or "fallback_generic",
            "selection_confidence": conf, "parser_version": parser.version, "score": score}


def parse_alert(ctx: ParseContext) -> ParseResult:
    """Parse with the best parser; if it fails, try remaining parsers and return the one with fewest errors."""
    parser, score = select_parser(ctx)
    det = selection_detail(ctx)
    best = parser.parse(ctx)
    best.score, best.selection_method, best.selection_confidence = score, det["selection_method"], det["selection_confidence"]
    if best.ok:
        return best
    for p in PARSERS:
        if p is parser:
            continue
        r = p.parse(ctx)
        r.score = p.matches(ctx)
        if r.ok:
            r.bank_name = ctx.bank_hint or parser.bank_name if parser.name != "generic" else r.bank_name
            r.fields["bank_name"] = r.bank_name
            r.parser = f"{parser.name}->{p.name}"
            r.selection_method, r.selection_confidence = det["selection_method"] + "+parser_fallback", max(0, det["selection_confidence"] - 30)
            r.warnings.append(f"selected parser '{parser.name}' failed; '{p.name}' used")
            return r
        if len(r.errors) < len(best.errors):
            best = r
    return best


def parse_all(ctx: ParseContext) -> List[dict]:
    out = []
    for p in PARSERS:
        r = p.parse(ctx)
        out.append({"parser": p.name, "version": p.version, "bank_name": p.bank_name, "score": p.matches(ctx),
                    "fields": r.fields, "errors": r.errors, "warnings": r.warnings, "ok": r.ok})
    return sorted(out, key=lambda x: -x["score"])
