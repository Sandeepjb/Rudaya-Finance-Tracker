"""Bank-statement column normalisation shared by CSV and PDF importers (Decimal-safe)."""
import re
from decimal import Decimal, InvalidOperation
from typing import Optional, List

HEADER_ALIASES = {
    "date": ["date", "transaction date", "txn date", "tran date", "value date", "posting date", "txn posted date"],
    "debit_amount": ["debit", "debit amount", "dr", "dr amount", "withdrawal", "withdrawal amount", "withdrawal amt",
                     "withdrawals", "debit amt"],
    "credit_amount": ["credit", "credit amount", "cr", "cr amount", "deposit", "deposit amount", "deposit amt",
                      "deposits", "credit amt"],
    "running_balance": ["balance", "closing balance", "running balance", "total amount", "available balance", "bal"],
    "amount": ["amount", "transaction amount", "txn amount", "amount inr"],
    "direction": ["dr cr", "cr dr", "type", "transaction type", "dr/cr", "cr/dr"],
    "narration": ["description", "narration", "particulars", "transaction details", "remarks", "transaction remarks",
                  "details", "transaction description"],
    "bank_reference": ["instrument", "instruments", "reference", "reference no", "transaction reference", "utr", "utr no",
                       "chq ref no", "chq ref no", "ref no", "cheque no", "chq no", "transaction id", "tran id",
                       "instrument no"],
}
_STATEMENT_TOTAL_RE = re.compile(r"^(grand\s+)?total\b|^closing\s+balance|^opening\s+balance", re.IGNORECASE)


def normalize_header(h: str) -> str:
    s = (h or "").replace("\n", " ").replace("\r", " ").strip().lower()
    s = re.sub(r"[^\w\s]", " ", s).replace("_", " ")
    return re.sub(r"\s+", " ", s).strip()


def detect_mapping(headers: List[str]) -> dict:
    """Map canonical field → original header. Exact alias match first, then prefix, then containment."""
    normed = [normalize_header(h) for h in headers]
    mapping = {}
    for field, aliases in HEADER_ALIASES.items():
        for a in aliases:
            hit = next((i for i, h in enumerate(normed) if h == normalize_header(a)), None)
            if hit is None:
                hit = next((i for i, h in enumerate(normed) if h.startswith(a + " ") and len(a) > 2), None)
            if hit is not None and headers[hit] not in mapping.values():
                mapping[field] = headers[hit]
                break
    if "amount" in mapping and (mapping.get("debit_amount") or mapping.get("credit_amount")):
        mapping.pop("amount")
    return mapping


def parse_decimal(v) -> Optional[Decimal]:
    """'336,654.00' / '1,740,399.71' / '4.94' / '930345.31 CR' → Decimal (absolute)."""
    s = str(v or "").strip()
    s = re.sub(r"(?i)\b(cr|dr)\b\.?", "", s)
    s = re.sub(r"[^\d.\-]", "", s.replace(",", ""))
    if not s or s in ("-", ".", "-."):
        return None
    try:
        return abs(Decimal(s))
    except InvalidOperation:
        return None


def balance_parts(v) -> tuple:
    """'930345.31 CR' → (Decimal, 'CR')."""
    s = str(v or "")
    m = re.search(r"(?i)\b(cr|dr)\b", s)
    return parse_decimal(s), (m.group(1).upper() if m else "")


def is_total_row(row: dict, mapping: dict) -> bool:
    text = " ".join(str(v) for v in row.values() if v)
    nar = str(row.get(mapping.get("narration", ""), "") or "")
    date = str(row.get(mapping.get("date", ""), "") or "")
    return bool(_STATEMENT_TOTAL_RE.search(nar.strip()) or _STATEMENT_TOTAL_RE.search(date.strip())
                or (_STATEMENT_TOTAL_RE.search(text.strip()) and not date.strip()))


def normalize_row(row: dict, mapping: dict, bank_name: str, bank_account: str, parse_date) -> dict:
    """Return a normalized statement row. `needs_review` rows must not be imported silently."""
    warnings, errors = [], []
    g = lambda k: str(row.get(mapping.get(k, ""), "") or "").strip()  # noqa: E731
    date = parse_date(g("date"))
    if not date:
        errors.append("unparseable date")
    narration = re.sub(r"\s+", " ", g("narration"))
    if not narration:
        errors.append("missing narration")
    dr, cr = parse_decimal(g("debit_amount")), parse_decimal(g("credit_amount"))
    bal, bal_dir = balance_parts(g("running_balance"))
    amount, direction, confidence = None, None, 100
    if mapping.get("debit_amount") or mapping.get("credit_amount"):
        if dr and dr > 0 and cr and cr > 0:
            errors.append("both Dr and Cr amounts present — ambiguous")
            confidence = 20
        elif dr and dr > 0:
            amount, direction = dr, "debit"
        elif cr and cr > 0:
            amount, direction = cr, "credit"
        else:
            errors.append("no transaction amount (Dr/Cr both empty)")
    elif mapping.get("amount"):
        amount = parse_decimal(g("amount"))
        dv = g("direction").lower()
        raw = g("amount")
        if dv.startswith(("dr", "debit", "withdraw")) or raw.startswith("-"):
            direction = "debit"
        elif dv.startswith(("cr", "credit", "deposit")):
            direction = "credit"
        elif amount:
            errors.append("direction column missing — ambiguous")
            confidence = 30
        if not amount:
            errors.append("missing amount")
    else:
        errors.append("no amount columns detected")
    if bal is not None and mapping.get("running_balance") and amount is not None and bal == amount:
        warnings.append("running balance equals amount — verify column mapping")
        confidence = min(confidence, 60)
    ref = g("bank_reference")
    txn = {"bank_name": bank_name, "bank_account": bank_account or "", "transaction_date": date or "",
           "direction": direction or "", "amount": float(amount) if amount is not None else 0, "narration": narration[:500],
           "bank_reference": ref[:80], "source": "csv", "source_message_id": "", "source_raw_text": str(row)[:4000]}
    return {"txn": txn, "errors": errors, "warnings": warnings, "parse_confidence": confidence if not errors else 0,
            "needs_review": bool(errors), "parsed_debit": float(dr) if dr is not None else None,
            "parsed_credit": float(cr) if cr is not None else None,
            "running_balance": float(bal) if bal is not None else None, "balance_direction": bal_dir, "raw_row": row}


def totals_report(rows: List[dict], statement_totals: Optional[dict]) -> dict:
    pd = sum((Decimal(str(r["txn"]["amount"])) for r in rows if not r["errors"] and r["txn"]["direction"] == "debit"), Decimal("0"))
    pc = sum((Decimal(str(r["txn"]["amount"])) for r in rows if not r["errors"] and r["txn"]["direction"] == "credit"), Decimal("0"))
    out = {"parsed_debit_total": float(pd), "parsed_credit_total": float(pc),
           "statement_debit_total": None, "statement_credit_total": None, "debit_difference": None,
           "credit_difference": None, "closing_balance": None, "warnings": []}
    st = statement_totals or {}
    if st.get("debit") is not None:
        out["statement_debit_total"] = float(st["debit"])
        out["debit_difference"] = float(Decimal(str(st["debit"])) - pd)
    if st.get("credit") is not None:
        out["statement_credit_total"] = float(st["credit"])
        out["credit_difference"] = float(Decimal(str(st["credit"])) - pc)
    if st.get("closing_balance") is not None:
        out["closing_balance"] = st["closing_balance"]
    if out["debit_difference"] not in (None, 0.0) or out["credit_difference"] not in (None, 0.0):
        out["warnings"].append("Parsed totals differ from statement totals — statement is NOT fully parsed; review invalid/ambiguous rows")
    if any(r["needs_review"] for r in rows):
        out["warnings"].append(f"{sum(1 for r in rows if r['needs_review'])} row(s) need parsing review and were excluded from totals")
    return out


def extract_statement_totals(rows: List[dict], mapping: dict) -> Optional[dict]:
    """Pick totals from a 'Total' footer row if the statement has one."""
    for row in rows:
        if is_total_row(row, mapping):
            dr = parse_decimal(row.get(mapping.get("debit_amount", ""), ""))
            cr = parse_decimal(row.get(mapping.get("credit_amount", ""), ""))
            bal, bd = balance_parts(row.get(mapping.get("running_balance", ""), ""))
            if dr is not None or cr is not None:
                return {"debit": dr, "credit": cr, "closing_balance": f"{bal} {bd}".strip() if bal is not None else None}
    return None
