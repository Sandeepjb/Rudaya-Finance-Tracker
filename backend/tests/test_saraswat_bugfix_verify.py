"""BUG FIX VERIFICATION for Saraswat CSV statement per review_request payload.
Exact CSV from the review with an ambiguous row 04-04-2025.
"""
import io
import os
import re
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"]).rstrip("/")
API = f"{BASE_URL}/api"
BT = f"{API}/bank-transactions"
ENV = dotenv_values("/app/backend/.env")
TAG = "QASV" + uuid.uuid4().hex[:4].upper()


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    cl = AsyncIOMotorClient(ENV["MONGO_URL"])
    d = cl[ENV["DB_NAME"]]

    async def run():
        await d.bank_transactions.delete_many({"narration": {"$regex": "QASV"}})
        await d.bank_inbox_messages.delete_many({"narration": {"$regex": "QASV"}})
    try:
        asyncio.get_event_loop().run_until_complete(run())
    except Exception:
        pass


@pytest.fixture(scope="module")
def admin():
    c = Path("/app/memory/test_credentials.md").read_text()
    e = re.search(r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?email(?:\*\*)?\s*:\s*`?([^`\s]+)", c).group(1)
    pw = re.search(r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?password(?:\*\*)?\s*:\s*`?([^`\s]+)", c).group(1)
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": e, "password": pw})
    assert r.status_code == 200, r.text
    return s


def review_csv():
    """Exact CSV from review_request (with ambiguous row 4)."""
    rows = [
        "Date,Dr Amount,Cr Amount,Total Amount,Particulars,Instruments",
        f'01-04-2025,,"336,654.00","930,345.31 CR",NEFT/N091250123/GOODYEAR INDIA {TAG},',
        f'02-04-2025,"24,000.00",,"906,345.31 CR",IB/NEFT/handewadi project {TAG},NEFT0001',
        f'03-04-2025,4.94,,"906,340.37 CR",SMS CHARGES {TAG},',
        f'04-04-2025,"100.00","100.00","906,340.37 CR",AMBIGUOUS {TAG},',
        'Total,"24,104.94","336,654.00","906,340.37 CR",,',
    ]
    return ("\n".join(rows) + "\n").encode()


def _upload(admin, path, raw, name="saraswat.csv"):
    return admin.post(f"{BT}/statement/{path}", files={"file": (name, io.BytesIO(raw), "text/csv")})


class TestSaraswatBugFix:
    def test_preview_matches_review_expectations(self, admin):
        r = _upload(admin, "preview", review_csv())
        assert r.status_code == 200, r.text
        p = r.json()

        # bank detection
        assert p["bank_name"] == "Saraswat Bank"

        # mapping
        m = p["mapping"]
        assert m["debit_amount"] == "Dr Amount"
        assert m["credit_amount"] == "Cr Amount"
        assert m["running_balance"] == "Total Amount"
        assert m["narration"] == "Particulars"

        by = {r["row"]: r for r in p["rows"]}
        # 4 data rows expected (Total is footer)
        assert len(by) == 4

        # row 1: credit 336654, balance 930345.31 CR
        assert by[1]["txn"]["direction"] == "credit"
        assert by[1]["txn"]["amount"] == 336654.0
        assert by[1]["running_balance"] == 930345.31
        assert by[1]["balance_direction"] == "CR"

        # row 2: debit 24000, bank_reference NEFT0001
        assert by[2]["txn"]["direction"] == "debit"
        assert by[2]["txn"]["amount"] == 24000.0
        assert by[2]["txn"]["bank_reference"] == "NEFT0001"

        # row 3: amount 4.94 debit
        assert by[3]["txn"]["amount"] == 4.94
        assert by[3]["txn"]["direction"] == "debit"

        # row 4: needs_review true with 'ambiguous' error
        assert by[4]["needs_review"] is True
        assert any("ambiguous" in e.lower() for e in by[4]["errors"])

        # amount != running_balance for any row
        for row in p["rows"]:
            assert row["txn"]["amount"] != row["running_balance"], f"row {row['row']}: amount equals balance"

        # totals
        t = p["totals"]
        assert t["parsed_debit_total"] == 24004.94
        assert t["statement_debit_total"] == 24104.94
        assert t["debit_difference"] == 100.0
        assert t["credit_difference"] == 0.0
        assert t["warnings"], "totals.warnings must be non-empty"

    def test_import_goes_to_pending_inbox_not_finance(self, admin):
        # search finance transactions for QASV before
        before = admin.get(f"{API}/transactions", params={"search": TAG})
        before_count = len(before.json()) if before.status_code == 200 else 0

        r = _upload(admin, "import", review_csv())
        assert r.status_code == 200, r.text
        res = r.json()
        # 3 valid rows should be ingested (row 4 ambiguous is invalid)
        assert res["ingested"] == 3
        assert res["invalid"] == 1
        # nothing posted to finance
        for row in res["results"]:
            assert row["finance_transaction_id"] is None
            assert row["status"] == "pending"

        # verify no QASV in finance
        after = admin.get(f"{API}/transactions", params={"search": TAG})
        assert len(after.json()) == before_count


class TestRegressionICICI:
    def test_icici_style_preview(self, admin):
        csv = (
            "Txn Date,Value Date,Transaction Remarks,Chq/Ref No,Withdrawal Amount (INR),Deposit Amount (INR),Balance\n"
            f'01-04-2025,01-04-2025,NEFT-FOO {TAG},REF001,,10000.00,50000.00\n'
            f'02-04-2025,02-04-2025,UPI-BAR {TAG},REF002,1500.00,,48500.00\n'
        ).encode()
        r = admin.post(f"{BT}/statement/preview", files={"file": ("icici.csv", io.BytesIO(csv), "text/csv")})
        assert r.status_code == 200, r.text
        p = r.json()
        m = p["mapping"]
        assert m.get("debit_amount") == "Withdrawal Amount (INR)"
        assert m.get("credit_amount") == "Deposit Amount (INR)"
        assert m.get("running_balance") == "Balance"
        by = {row["row"]: row for row in p["rows"]}
        assert by[1]["txn"]["direction"] == "credit" and by[1]["txn"]["amount"] == 10000.0
        assert by[2]["txn"]["direction"] == "debit" and by[2]["txn"]["amount"] == 1500.0
