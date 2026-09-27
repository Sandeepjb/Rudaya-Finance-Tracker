"""Statement-level reconciliation: statement totals vs independently parsed totals (Decimal)."""
from decimal import Decimal
from typing import List, Optional

from bank_parsers.statement import parse_decimal, balance_parts


def _d(v) -> Decimal:
    return Decimal(str(v)).quantize(Decimal("0.01"))


def reconcile(rows: List[dict], statement_totals: Optional[dict], opening_balance: Optional[float]) -> dict:
    # rows whose direction was confirmed (by Dr/Cr cell or balance delta) count toward totals, even if flagged for
    # narration/reference review; ambiguous rows have no direction and are excluded
    valid = [r for r in rows if r["txn"].get("direction") in ("debit", "credit") and r["txn"].get("amount")]
    pd = sum((_d(r["txn"]["amount"]) for r in valid if r["txn"]["direction"] == "debit"), Decimal("0.00"))
    pc = sum((_d(r["txn"]["amount"]) for r in valid if r["txn"]["direction"] == "credit"), Decimal("0.00"))
    st = statement_totals or {}
    cb0, _ = balance_parts(st.get("closing_balance")) if st.get("closing_balance") else (None, None)
    out = {"statement_closing_balance_value": str(cb0) if cb0 is not None else None, "parsed_debit_total": str(pd), "parsed_credit_total": str(pc), "statement_debit_total": None, "statement_credit_total": None,
           "debit_difference": None, "credit_difference": None, "statement_closing_balance": None, "parsed_closing_balance": None,
           "closing_balance_difference": None, "ambiguous_rows": sum(1 for r in rows if r["needs_review"]), "status": "WARNING", "messages": []}
    if st.get("debit") is not None:
        out["statement_debit_total"] = str(_d(st["debit"]))
        out["debit_difference"] = str(_d(st["debit"]) - pd)
    if st.get("credit") is not None:
        out["statement_credit_total"] = str(_d(st["credit"]))
        out["credit_difference"] = str(_d(st["credit"]) - pc)
    last_bal = next((r["running_balance"] for r in reversed(rows) if r.get("running_balance") is not None), None)
    if last_bal is not None:
        out["parsed_closing_balance"] = str(_d(last_bal))
    elif opening_balance is not None:
        out["parsed_closing_balance"] = str(_d(opening_balance) + pc - pd)
    if st.get("closing_balance"):
        cb, _ = balance_parts(st["closing_balance"])
        if cb is not None:
            out["statement_closing_balance"] = st["closing_balance"]
            if out["parsed_closing_balance"] is not None:
                out["closing_balance_difference"] = str(cb - _d(out["parsed_closing_balance"]))
    diffs = [out[k] for k in ("debit_difference", "credit_difference", "closing_balance_difference") if out[k] is not None]
    nonzero = [x for x in diffs if _d(x) != 0]
    if out["ambiguous_rows"]:
        out["messages"].append(f"{out['ambiguous_rows']} ambiguous row(s) need parsing review (excluded from parsed totals)")
    if not diffs:
        out["messages"].append("Statement totals not found in document — parsed totals could not be cross-checked")
        out["status"] = "WARNING"
    elif nonzero:
        out["messages"].append("Material reconciliation differences remain — administrator review required")
        out["status"] = "FAILED" if any(abs(_d(x)) > Decimal("1") for x in nonzero) else "WARNING"
    elif out["ambiguous_rows"]:
        out["status"] = "WARNING"
    else:
        out["status"] = "MATCHED"
        out["messages"].append("Statement reconciliation successful.")
    return out
