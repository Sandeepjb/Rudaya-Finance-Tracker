"""Turn structured tables into normalized bank-statement rows (bank-specific alias dictionaries, multi-line merge,
confidence). Uses the shared Decimal-safe statement rules; never guesses debit vs credit."""
import re
from decimal import Decimal
from typing import List, Optional

from bank_parsers.statement import (HEADER_ALIASES, detect_mapping, normalize_header, normalize_row, is_total_row,
                                    parse_decimal, balance_parts)
from bank_parsers.base import parse_any_date
from .azure_document_intelligence import ExtractionResult, Table

BANK_NORMALIZERS = {
    "Saraswat Bank": {"keywords": ["saraswat"], "columns": ["date", "debit_amount", "credit_amount", "running_balance", "narration", "bank_reference"],
                      "aliases": {"debit_amount": ["dr amount"], "credit_amount": ["cr amount"], "running_balance": ["total amount"],
                                  "narration": ["particulars"], "bank_reference": ["instruments"]}},
    "ICICI Bank": {"keywords": ["icici"], "aliases": {"debit_amount": ["withdrawal amount inr", "withdrawal amount"],
                                                       "credit_amount": ["deposit amount inr", "deposit amount"], "narration": ["transaction remarks"]}},
    "HDFC Bank": {"keywords": ["hdfc"], "aliases": {"debit_amount": ["withdrawal amt"], "credit_amount": ["deposit amt"],
                                                     "running_balance": ["closing balance"], "bank_reference": ["chq ref no"]}},
    "Unknown Bank": {"keywords": [], "aliases": {}},
}
_DATE_RE = re.compile(r"^\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}$|^\d{1,2}[-/ ][A-Za-z]{3}[-/ ]\d{2,4}$|^\d{4}-\d{2}-\d{2}$")


def identify_bank(result: ExtractionResult, hint: str = "") -> str:
    if hint and hint.lower() not in ("", "auto", "auto detect"):
        return hint
    head = " ".join(result.text_lines[:120]).lower()
    if not head:
        head = " ".join(c.raw for t in result.tables[:2] for r in t.rows[:3] for c in r).lower()
    for bank, spec in BANK_NORMALIZERS.items():
        if any(k in head for k in spec["keywords"]):
            return bank
    return "Unknown Bank"


def _bank_mapping(headers: List[str], bank: str) -> dict:
    """Bank-specific aliases first, then the shared dictionary."""
    mapping = {}
    normed = [normalize_header(h) for h in headers]
    for field_name, aliases in BANK_NORMALIZERS.get(bank, {}).get("aliases", {}).items():
        for a in aliases:
            if a in normed:
                mapping[field_name] = headers[normed.index(a)]
                break
    for k, v in detect_mapping(headers).items():
        mapping.setdefault(k, v)
    return mapping


def _find_header(table: Table) -> Optional[int]:
    for i, row in enumerate(table.rows[:6]):
        m = detect_mapping([c.raw for c in row])
        if "date" in m and "narration" in m and ("debit_amount" in m or "credit_amount" in m or "amount" in m):
            return i
    return None


def _period(lines: List[str]) -> tuple:
    txt = " ".join(lines[:150])
    m = re.search(r"(\d{1,2}[-/][A-Za-z0-9]{2,3}[-/]\d{2,4})\s*(?:to|-|–|through)\s*(?:Date\s*:\s*)?(\d{1,2}[-/][A-Za-z0-9]{2,3}[-/]\d{2,4})", txt, re.IGNORECASE)
    return (parse_any_date(m.group(1)), parse_any_date(m.group(2))) if m else (None, None)


def _account(lines: List[str]) -> str:
    m = re.search(r"(?:Account\s*(?:No|Number)\.?\s*:?\s*|A/c\s*(?:No)?\.?\s*:?\s*)([A-Z]{0,6}/?)([X\*\d][X\*\d ]{5,})", " ".join(lines[:150]), re.IGNORECASE)
    return re.sub(r"\s", "", m.group(2)) if m else ""


def _row_confidence(cells: List, mapping: dict, headers: List[str]) -> Optional[float]:
    idx = {h: i for i, h in enumerate(headers)}
    vals = []
    for k in ("date", "debit_amount", "credit_amount", "amount", "narration", "bank_reference"):
        h = mapping.get(k)
        if h in idx and idx[h] < len(cells) and cells[idx[h]].confidence is not None and cells[idx[h]].raw:
            vals.append(cells[idx[h]].confidence)
    return min(vals) if vals else None


def normalize_statement(result: ExtractionResult, bank: str, bank_account: str) -> dict:
    rows_out, mapping_used, statement_totals, opening = [], {}, None, None
    for table in result.tables:
        hi = _find_header(table)
        if hi is None:
            if mapping_used and table.rows:
                headers = list(mapping_used["headers"])  # continuation table on a later page without header
                body = table.rows
            else:
                continue
        else:
            headers = [c.raw.replace("\n", " ") for c in table.rows[hi]]
            body = table.rows[hi + 1:]
            mapping_used = {"mapping": _bank_mapping(headers, bank), "headers": headers}
        mapping = mapping_used["mapping"]
        hidx = {h: i for i, h in enumerate(headers)}
        for cells in body:
            vals = [c.raw.replace("\n", " ").strip() for c in cells] + [""] * (len(headers) - len(cells))
            row = {h: vals[i] for h, i in hidx.items()}
            date_txt = row.get(mapping.get("date", ""), "")
            has_amt = any(parse_decimal(row.get(mapping.get(k, ""), "")) for k in ("debit_amount", "credit_amount", "amount"))
            if is_total_row(row, mapping) or re.match(r"(?i)^(grand\s+)?total", date_txt):
                dr, cr = parse_decimal(row.get(mapping.get("debit_amount", ""), "")), parse_decimal(row.get(mapping.get("credit_amount", ""), ""))
                bal, bd = balance_parts(row.get(mapping.get("running_balance", ""), ""))
                if dr is not None or cr is not None:
                    statement_totals = {"debit": dr, "credit": cr, "closing_balance": f"{bal} {bd}".strip() if bal is not None else None}
                continue
            if re.search(r"(?i)opening\s+balance", " ".join(vals)) and opening is None:
                opening = balance_parts(row.get(mapping.get("running_balance", ""), "") or " ".join(vals))[0]
                continue
            if not _DATE_RE.match(date_txt.strip()) and not has_amt:
                if rows_out:  # multi-line continuation (wrapped particulars / reference)
                    extra = " ".join(v for v in vals if v).strip()
                    if extra:
                        prev = rows_out[-1]
                        prev["txn"]["narration"] = (prev["txn"]["narration"] + " " + extra)[:500]
                        prev["continuation_lines"] = prev.get("continuation_lines", 0) + 1
                        if not prev["txn"]["bank_reference"] and re.fullmatch(r"[A-Z0-9/-]{6,}", extra):
                            prev["txn"]["bank_reference"] = extra[:80]
                continue
            n = normalize_row(row, mapping, bank, bank_account, parse_any_date)
            conf = _row_confidence(cells, mapping, headers)
            n["extraction_confidence"] = conf
            if conf is not None and conf < 0.7 and not n["errors"]:
                n["errors"].append(f"low extraction confidence ({conf:.2f})")
                n["needs_review"] = True
                n["parse_confidence"] = 0
            n["confidence_band"] = "Needs Review" if n["needs_review"] else ("High" if (conf is None or conf >= 0.9) else "Medium")
            n["cells"] = [{"page": c.page, "table": c.table, "row": c.row, "col": c.col, "raw": c.raw, "confidence": c.confidence,
                           "header": headers[i] if i < len(headers) else ""} for i, c in enumerate(cells)]
            n["page"] = cells[0].page if cells else table.page
            n["original"] = dict(n["txn"])
            rows_out.append(n)
    if not rows_out and bank == "Saraswat Bank" and result.text_lines:
        from bank_parsers.saraswat import SaraswatParser
        rows_out, statement_totals, _ = SaraswatParser.parse_statement_lines(result.text_lines)
        ob = re.search(r"(?i)opening\s+balance.*?(?:Rs\.?\s*)?(\d[\d,]*\.\d{2})", " ".join(result.text_lines[:150]))
        opening = parse_decimal(ob.group(1)) if ob else None
        for r in rows_out:
            r.update(extraction_confidence=None, cells=[], page=None, original=dict(r["txn"]),
                     confidence_band="Needs Review" if r["needs_review"] else "Medium",
                     warnings=r.get("warnings", []) + ["derived from flattened text (no table cells) — direction confirmed by running balance"])
            r["txn"]["bank_account"] = bank_account
        mapping_used = {"mapping": {"date": "Date", "narration": "Particulars", "bank_reference": "Instruments", "debit_amount": "Dr Amount",
                                    "credit_amount": "Cr Amount", "running_balance": "Total Amount"}, "headers": list(mapping_used.get("headers") or [])}
    for i, r in enumerate(rows_out, 1):
        r["row"] = i
    return {"rows": rows_out, "mapping": mapping_used.get("mapping", {}), "headers": mapping_used.get("headers", []),
            "statement_totals": statement_totals, "opening_balance": float(opening) if opening is not None else None,
            "period": _period(result.text_lines), "account": bank_account or _account(result.text_lines)}
