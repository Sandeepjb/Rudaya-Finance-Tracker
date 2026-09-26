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
    rf"^(?P<date>\d{{1,2}}[-/]\d{{1,2}}[-/]\d{{2,4}})\s+(?P<a1>{_NUM})\s+(?:(?P<a2>{_NUM})\s+)?(?P<bal>{_NUM})\s*(?P<bd>CR|DR)\b\s*(?P<rest>.*)$",
    re.IGNORECASE)
_TOTAL_RE = re.compile(rf"^(?:Grand\s+)?Total\b\D*(?P<dr>{_NUM})\s+(?P<cr>{_NUM})", re.IGNORECASE)


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
        rest = m.group("rest").strip()
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
        """Return (rows, statement_totals, opening_balance)."""
        rows, totals, prev = [], None, None
        for ln in lines:
            ob = re.search(rf"(?i)opening\s+balance\D*({_NUM})\s*(CR|DR)?", ln)
            if ob and prev is None:
                prev = parse_decimal(ob.group(1))
                continue
            t = _TOTAL_RE.match(ln.strip())
            if t:
                cb = re.search(rf"({_NUM})\s*(CR|DR)", ln[t.end():], re.IGNORECASE)
                totals = {"debit": parse_decimal(t.group("dr")), "credit": parse_decimal(t.group("cr")),
                          "closing_balance": f"{cb.group(1)} {cb.group(2).upper()}" if cb else None}
                continue
            r = SaraswatParser.parse_statement_line(ln, prev)
            if r is None:
                if rows and not re.match(r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", ln) and not re.match(r"(?i)^(date|page|statement|account)", ln):
                    rows[-1]["txn"]["narration"] = (rows[-1]["txn"]["narration"] + " " + ln.strip())[:500]
                continue
            rows.append(r)
            if r["running_balance"] is not None:
                prev = Decimal(str(r["running_balance"]))
        for i, r in enumerate(rows, 1):
            r["row"] = i
        return rows, totals, prev
