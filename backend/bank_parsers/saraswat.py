import re
from decimal import Decimal
from typing import List, Optional
from .base import BaseParser, parse_any_date
from .statement import parse_decimal, balance_parts

# Real Saraswat current-account statement: Date | Dr Amount | Cr Amount | Total Amount | Particulars | Instruments
STATEMENT_COLUMNS = ["Date", "Dr Amount", "Cr Amount", "Total Amount", "Particulars", "Instruments"]
_NUM = r"\d{1,3}(?:,\d{3})*(?:\.\d{2})|\d+\.\d{2}"
# date, then one or two amounts, then balance with CR/DR, then particulars (+ optional instrument at the end)
_LINE_RE = re.compile(
    rf"^(?P<date>\d{{1,2}}[-/]\d{{1,2}}[-/]\d{{2,4}})\s+(?P<mid>.*?)\s*(?P<a1>{_NUM})\s+(?:(?P<a2>{_NUM})\s+)?(?P<bal>{_NUM})\s*(?P<bd>CR|DR)\b\s*(?P<rest>.*)$",
    re.IGNORECASE)
_TOTAL_RE = re.compile(rf"^(?:Grand\s+)?Totals?\b[^\d]*(?P<dr>{_NUM})\s+(?P<cr>{_NUM})", re.IGNORECASE)
_DATE_ONLY_BAL_RE = re.compile(rf"^(?P<date>\d{{1,2}}[-/]\d{{1,2}}[-/]\d{{2,4}})\s+(?P<rest>.*?)(?P<bal>{_NUM})\s*(?P<bd>CR|DR)\s*$", re.IGNORECASE)
_DATE_LINE_RE = re.compile(r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b")
_SKIP_RE = re.compile(r"(?i)^(date\s+particulars|statement of accounts|page\s*:|\*+\s*end of statement|closing balance|branch|address|city|phone|gst|account no|name\s*:|customer id|purpose|from date|current|limit|total sanction|joint|run date|:\s*p)")


class SaraswatParser(BaseParser):
    name = "saraswat"
    version = "1.1"
    bank_name = "Saraswat Bank"
    keywords = ("saraswat", "saraswatbank")
    sender_keywords = ("saraswat",)
    narration_patterns = (
        r"(?:for|towards|Info|Desc(?:ription)?|Particulars)\s*[:\-]?\s*([^\.]+?)(?:\.\s|\.$|\sRef|\sAvl|$)",
        r"\b(?:to|from)\s+(?!a/c|A/c|account|your)([^\.]+?)(?:\.\s|\.$|\sRef|\sAvl|$)",
    )

    @staticmethod
    def parse_statement_line(line: str, prev_balance: Optional[Decimal]) -> Optional[dict]:
        """Parse one flattened PDF statement line. Direction is confirmed by the running-balance delta, never by
        text position alone; unconfirmed rows are flagged needs_review."""
        m = _LINE_RE.match(line.strip())
        if not m:
            return None
        a1, a2 = parse_decimal(m.group("a1")), parse_decimal(m.group("a2")) if m.group("a2") else None
        bal, bd = balance_parts(f"{m.group('bal')} {m.group('bd')}")
        rest = (m.group("mid").strip() + " " + m.group("rest").strip()).strip()
        toks = rest.split()
        instrument = toks[-1] if toks and re.fullmatch(r"[A-Z0-9/-]{6,}", toks[-1]) and len(toks) > 1 else ""
        narration = " ".join(toks[:-1] if instrument else toks)
        warnings, errors, conf = [], [], 100
        amount, direction = None, None
        if a2 is not None:
            errors.append("both Dr and Cr values present on one line — ambiguous")
            conf = 20
        else:
            amount = a1
            if prev_balance is not None and bal is not None:
                if prev_balance - amount == bal:
                    direction = "debit"
                elif prev_balance + amount == bal:
                    direction = "credit"
                else:
                    errors.append("running balance does not confirm debit/credit — ambiguous column placement")
                    conf = 30
            else:
                errors.append("first row: direction cannot be confirmed without an opening balance")
                conf = 40
        return {"txn": {"bank_name": "Saraswat Bank", "transaction_date": parse_any_date(m.group("date")) or "",
                        "direction": direction or "", "amount": float(amount) if amount is not None else 0,
                        "narration": narration[:500], "bank_reference": instrument, "source": "csv",
                        "source_message_id": "", "source_raw_text": line[:4000]},
                "errors": errors, "warnings": warnings, "parse_confidence": conf if not errors else 0,
                "needs_review": bool(errors), "parsed_debit": float(amount) if direction == "debit" else None,
                "parsed_credit": float(amount) if direction == "credit" else None,
                "running_balance": float(bal) if bal is not None else None, "balance_direction": bd, "raw_row": {"line": line}}

    @staticmethod
    def parse_statement_lines(lines: List[str]) -> tuple:
        """Flattened-text fallback (real Saraswat PDF): particulars wrap onto the lines above and below the dated line.
        The line right after a dated line continues that row; remaining lines before the next dated line start the next row.
        Direction is only ever confirmed by the running-balance delta. Returns (rows, statement_totals, last_balance)."""
        rows, totals, prev, pending_prefix, last_row = [], None, None, [], None
        for ln in lines:
            ln = ln.strip()
            if not ln:
                continue
            ob = re.search(rf"(?i)opening\s+balance.*?(?:Rs\.?\s*)?({_NUM})\s*(CR|DR)", ln)
            if ob and prev is None:
                prev = parse_decimal(ob.group(1))
                continue
            t = _TOTAL_RE.match(ln)
            if t:
                cb = re.search(rf"({_NUM})\s*(CR|DR)", ln[t.end():], re.IGNORECASE)
                totals = {"debit": parse_decimal(t.group("dr")), "credit": parse_decimal(t.group("cr")),
                          "closing_balance": f"{cb.group(1)} {cb.group(2).upper()}" if cb else None}
                last_row = None
                continue
            if _SKIP_RE.match(ln) or re.fullmatch(rf"{_NUM}\s*(CR|DR)", ln, re.IGNORECASE):
                continue
            if _DATE_LINE_RE.match(ln):
                r = SaraswatParser.parse_statement_line(ln, prev)
                if r is None:
                    m = _DATE_ONLY_BAL_RE.match(ln)
                    if m:  # dated informational row with no amount (e.g. charge memo) – balance unchanged
                        prev = parse_decimal(m.group("bal")) if prev is None else prev
                        pending_prefix, last_row = [], None
                        continue
                    pending_prefix.append(ln)
                    continue
                if pending_prefix:
                    r["txn"]["narration"] = (" ".join(pending_prefix) + " " + r["txn"]["narration"]).strip()[:500]
                    pending_prefix = []
                rows.append(r)
                last_row = r
                if r["running_balance"] is not None:
                    prev = Decimal(str(r["running_balance"]))
                continue
            if last_row is not None:
                last_row["txn"]["narration"] = (last_row["txn"]["narration"] + " " + ln)[:500]
                last_row["continuation_lines"] = last_row.get("continuation_lines", 0) + 1
                last_row = None
            else:
                pending_prefix.append(ln)
        for i, r in enumerate(rows, 1):
            r["row"] = i
            r["txn"]["narration"] = re.sub(r"\s+", " ", r["txn"]["narration"]).strip()
            if not r["txn"]["narration"] and not r["errors"]:
                r["errors"].append("missing narration — particulars could not be associated with this row")
                r["needs_review"], r["parse_confidence"] = True, 0
            if not r["txn"]["bank_reference"]:
                m = re.search(r"\b([A-Z]{2,6}\d{8,}|[A-Z0-9]{12,})\b", r["txn"]["narration"])
                r["txn"]["bank_reference"] = m.group(1) if m else ""
        return rows, totals, prev
