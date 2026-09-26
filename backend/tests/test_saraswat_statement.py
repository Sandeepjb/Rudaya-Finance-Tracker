"""Saraswat Bank statement structure regression: Date | Dr Amount | Cr Amount | Total Amount | Particulars | Instruments."""
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
W = "".join(chr(65 + int(c)) if c.isdigit() else c for c in os.environ.get("PYTEST_XDIST_WORKER", "gw0").upper())
TAG = "QASAR" + W


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    cl = AsyncIOMotorClient(ENV["MONGO_URL"])
    d = cl[ENV["DB_NAME"]]

    async def run():
        await d.bank_transactions.delete_many({"narration": {"$regex": TAG}})
    asyncio.get_event_loop().run_until_complete(run())


@pytest.fixture(scope="module")
def admin():
    c = Path("/app/memory/test_credentials.md").read_text()
    e = re.search(r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?email(?:\*\*)?\s*:\s*`?([^`\s]+)", c).group(1)
    pw = re.search(r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?password(?:\*\*)?\s*:\s*`?([^`\s]+)", c).group(1)
    s = requests.Session()
    assert s.post(f"{API}/auth/login", json={"email": e, "password": pw}).status_code == 200
    return s


def saraswat_csv(tag, with_total=True, ambiguous=False):
    rows = [
        "Date,Dr Amount,Cr Amount,Total Amount,Particulars,Instruments",
        f'01-04-2025,,"336,654.00","930,345.31 CR",NEFT/N091250123/GOODYEAR INDIA {tag},',
        f'02-04-2025,"24,000.00",,"906,345.31 CR",IB/NEFT/handewadi project {tag},NEFT0001',
        f'03-04-2025,4.94,,"906,340.37 CR",SMS CHARGES {tag},',
        f'05-04-2025,,"1,740,399.71","2,646,740.08 CR",RTGS/FORD CHENNAI {tag},RTGS777',
        f'06-04-2025,"500,000.00",,"2,146,740.08 CR",TRF TO OWN ACCOUNT HDFC {tag},',
    ]
    if ambiguous:
        rows.append(f'07-04-2025,"100.00","100.00","2,146,740.08 CR",AMBIGUOUS ROW {tag},')
    if with_total:
        rows.append('Total,"524,004.94","2,077,053.71","2,146,740.08 CR",,')
    return ("\n".join(rows) + "\n").encode()


def _upload(admin, path, raw, **fields):
    return admin.post(f"{BT}/statement/{path}", files={"file": ("saraswat.csv", io.BytesIO(raw), "text/csv")}, data=fields)


class TestSaraswatStatementCsv:
    def test_unit_normalisation(self):
        import sys
        sys.path.insert(0, "/app/backend")
        from bank_parsers.statement import detect_mapping, normalize_header, parse_decimal, normalize_row, balance_parts
        from decimal import Decimal
        assert normalize_header("  Dr\nAmount ") == "dr amount" and normalize_header("Chq./Ref.No.") == "chq ref no"
        m = detect_mapping(["Date", "Dr Amount", "Cr Amount", "Total Amount", "Particulars", "Instruments"])
        assert m == {"date": "Date", "debit_amount": "Dr Amount", "credit_amount": "Cr Amount", "running_balance": "Total Amount",
                     "narration": "Particulars", "bank_reference": "Instruments"}
        assert parse_decimal("1,740,399.71") == Decimal("1740399.71") and parse_decimal("4.94") == Decimal("4.94")
        assert parse_decimal("336654.00") == Decimal("336654.00") and balance_parts("930345.31 CR") == (Decimal("930345.31"), "CR")
        r = normalize_row({"Date": "01-04-2025", "Dr Amount": "", "Cr Amount": "336,654.00", "Total Amount": "930,345.31 CR",
                           "Particulars": "NEFT/GOODYEAR", "Instruments": ""}, m, "Saraswat Bank", "", lambda v: "2025-04-01")
        assert r["txn"]["amount"] == 336654.0 and r["txn"]["direction"] == "credit" and r["running_balance"] == 930345.31
        assert r["balance_direction"] == "CR" and not r["needs_review"] and r["parse_confidence"] == 100
        r2 = normalize_row({"Date": "02-04-2025", "Dr Amount": "24,000.00", "Cr Amount": "", "Total Amount": "906,346.31 CR",
                            "Particulars": "IB/NEFT/handewadi project", "Instruments": ""}, m, "Saraswat Bank", "", lambda v: "2025-04-02")
        assert r2["txn"]["amount"] == 24000.0 and r2["txn"]["direction"] == "debit" and r2["parsed_debit"] == 24000.0
        r3 = normalize_row({"Date": "03-04-2025", "Dr Amount": "", "Cr Amount": "", "Total Amount": "906,346.31 CR",
                            "Particulars": "x", "Instruments": ""}, m, "Saraswat Bank", "", lambda v: "2025-04-03")
        assert r3["needs_review"] and "no transaction amount" in r3["errors"][0]

    def test_preview_real_structure(self, admin):
        t = TAG + uuid.uuid4().hex[:4].upper()
        p = _upload(admin, "preview", saraswat_csv(t)).json()
        assert p["bank_name"] == "Saraswat Bank"
        assert p["mapping"]["debit_amount"] == "Dr Amount" and p["mapping"]["credit_amount"] == "Cr Amount"
        assert p["mapping"]["running_balance"] == "Total Amount" and p["mapping"]["narration"] == "Particulars"
        assert p["total"] == 5 and p["valid"] == 5 and p["needs_review"] == 0, p["rows"]
        by = {r["row"]: r for r in p["rows"]}
        assert by[1]["txn"]["direction"] == "credit" and by[1]["txn"]["amount"] == 336654.0 and by[1]["running_balance"] == 930345.31
        assert by[2]["txn"]["direction"] == "debit" and by[2]["txn"]["amount"] == 24000.0 and by[2]["txn"]["bank_reference"] == "NEFT0001"
        assert by[3]["txn"]["amount"] == 4.94 and by[4]["txn"]["amount"] == 1740399.71
        for r in p["rows"]:
            assert r["txn"]["amount"] != r["running_balance"], "Total Amount must never be the transaction amount"
        assert by[1]["txn"]["narration"].startswith("NEFT/N091250123/GOODYEAR INDIA")
        assert "suggestion" not in by[5]["txn"]  # internal transfer: unclassified until pipeline runs
        tot = p["totals"]
        assert tot["parsed_debit_total"] == 524004.94 and tot["parsed_credit_total"] == 2077053.71
        assert tot["statement_debit_total"] == 524004.94 and tot["debit_difference"] == 0.0 and tot["credit_difference"] == 0.0
        assert tot["closing_balance"].startswith("2146740.08") and tot["warnings"] == []

    def test_ambiguous_row_needs_review_and_totals_warning(self, admin):
        t = TAG + uuid.uuid4().hex[:4].upper()
        p = _upload(admin, "preview", saraswat_csv(t, ambiguous=True)).json()
        assert p["needs_review"] == 1
        amb = [r for r in p["rows"] if "AMBIGUOUS" in r["txn"]["narration"]][0]
        assert amb["needs_review"] and "ambiguous" in amb["errors"][0] and amb["parse_confidence"] == 0
        assert p["totals"]["warnings"] and any("review" in w for w in p["totals"]["warnings"])

    def test_import_goes_through_pipeline_not_finance(self, admin):
        t = TAG + uuid.uuid4().hex[:4].upper()
        before = len(admin.get(f"{API}/transactions", params={"search": t}).json())
        res = _upload(admin, "import", saraswat_csv(t, ambiguous=True)).json()
        assert res["ingested"] == 5 and res["pending"] == 5 and res["invalid"] == 1
        for r in res["results"]:
            assert r["status"] == "pending" and r["finance_transaction_id"] is None and r["suggestion"] is not None
            assert r["direction"] in ("debit", "credit")
        trf = next(r for r in res["results"] if "OWN ACCOUNT" in r["narration"])
        assert trf["suggestion"]["source"] in ("historical", "ai", "none", "mapping_rule")  # engine decides, not the parser
        assert len(admin.get(f"{API}/transactions", params={"search": t}).json()) == before  # parser never posts

    def test_no_total_row_still_previews(self, admin):
        p = _upload(admin, "preview", saraswat_csv(TAG + "NT", with_total=False)).json()
        assert p["valid"] == 5 and p["totals"]["statement_debit_total"] is None and p["totals"]["debit_difference"] is None


def _pdf(lines):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for ln in lines:
        c.drawString(20, y, ln)
        y -= 14
    c.save()
    return buf.getvalue()


class TestSaraswatStatementPdf:
    def test_pdf_balance_confirms_direction(self, admin):
        t = TAG + uuid.uuid4().hex[:4].upper()
        raw = _pdf(["Saraswat Co-operative Bank Ltd", "Account No: 123456789012", "Statement 01-04-2025 to 30-04-2025",
                    "Opening Balance 593,691.31 CR",
                    "Date Dr Amount Cr Amount Total Amount Particulars Instruments",
                    f"01-04-2025 336,654.00 930,345.31 CR NEFT/N091250123/GOODYEAR INDIA {t}",
                    f"02-04-2025 24,000.00 906,345.31 CR IB/NEFT/handewadi project {t} NEFT0001",
                    f"03-04-2025 4.94 906,340.37 CR SMS CHARGES {t}",
                    f"04-04-2025 999.00 1,000.00 906,340.37 CR WEIRD ROW {t}",
                    "Total 24,004.94 336,654.00 906,340.37 CR"])
        p = admin.post(f"{BT}/statement/pdf/preview", files={"file": ("s.pdf", io.BytesIO(raw), "application/pdf")}).json()
        assert p["bank_name"] == "Saraswat Bank" and p["total"] == 4 and p["valid"] == 3 and p["needs_review"] == 1
        by = {r["row"]: r for r in p["rows"]}
        assert by[1]["txn"]["direction"] == "credit" and by[1]["txn"]["amount"] == 336654.0 and by[1]["running_balance"] == 930345.31
        assert by[2]["txn"]["direction"] == "debit" and by[2]["txn"]["amount"] == 24000.0 and by[2]["txn"]["bank_reference"] == "NEFT0001"
        assert by[3]["txn"]["direction"] == "debit" and by[3]["txn"]["amount"] == 4.94
        assert by[4]["needs_review"] and "ambiguous" in by[4]["errors"][0]
        assert by[1]["source_page"] == 1 and by[1]["raw_text"].startswith("01-04-2025")
        tot = p["totals"]
        assert tot["statement_debit_total"] == 24004.94 and tot["parsed_debit_total"] == 24004.94 and tot["debit_difference"] == 0.0
        assert tot["statement_credit_total"] == 336654.0 and tot["credit_difference"] == 0.0

    def test_pdf_without_opening_balance_first_row_reviewed(self, admin):
        raw = _pdf(["Saraswat Bank", "Date Dr Amount Cr Amount Total Amount Particulars",
                    f"01-04-2025 100.00 1,100.00 CR FIRST {TAG}", f"02-04-2025 50.00 1,050.00 CR SECOND {TAG}"])
        p = admin.post(f"{BT}/statement/pdf/preview", files={"file": ("s.pdf", io.BytesIO(raw), "application/pdf")}).json()
        by = {r["row"]: r for r in p["rows"]}
        assert by[1]["needs_review"] and by[2]["txn"]["direction"] == "debit"
