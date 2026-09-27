"""Azure Document Intelligence statement import: provider error mapping, normalisation, reconciliation, real Saraswat benchmark."""
import asyncio
import io
import os
import re
import sys
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

sys.path.insert(0, "/app/backend")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"]).rstrip("/")
API = f"{BASE_URL}/api"
SI = f"{API}/bank-transactions/statement-imports"
ENV = dotenv_values("/app/backend/.env")
FIXTURE = Path("/app/backend/tests/fixtures/saraswat_2025_26.pdf")
W = "".join(chr(65 + int(c)) if c.isdigit() else c for c in os.environ.get("PYTEST_XDIST_WORKER", "gw0").upper())
TAG = "QAAZ" + W


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    from motor.motor_asyncio import AsyncIOMotorClient
    cl = AsyncIOMotorClient(ENV["MONGO_URL"])
    d = cl[ENV["DB_NAME"]]

    async def run():
        await d.bank_transactions.delete_many({"narration": {"$regex": TAG}})
        await d.bank_statement_imports.delete_many({"filename": {"$regex": "^" + TAG}})
    asyncio.get_event_loop().run_until_complete(run())


@pytest.fixture(scope="module")
def admin():
    c = Path("/app/memory/test_credentials.md").read_text()
    e = re.search(r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?email(?:\*\*)?\s*:\s*`?([^`\s]+)", c).group(1)
    pw = re.search(r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?password(?:\*\*)?\s*:\s*`?([^`\s]+)", c).group(1)
    s = requests.Session()
    assert s.post(f"{API}/auth/login", json={"email": e, "password": pw}).status_code == 200
    return s


def _pdf(lines, pages=1):
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    per = max(1, len(lines) // pages + (1 if len(lines) % pages else 0))
    for p in range(pages):
        y = 800
        for ln in lines[p * per:(p + 1) * per]:
            c.drawString(20, y, ln)
            y -= 14
        c.showPage()
    c.save()
    return buf.getvalue()


def saraswat_lines(tag, ambiguous=False):
    ls = ["Saraswat Co-operative Bank Ltd STATEMENT OF ACCOUNTS", "Account No. : CAELT/372100100000319",
          "From Date : 01/04/2025 To Date :30/04/2025 Opening Balance As On 01/04/2025 : Rs.593,691.31 CR",
          "Date Particulars Instruments Dr Amount Cr Amount Total Amount",
          f"NEFT/CHASN5{tag}0189460416",
          "01-04-2025 336,654.00 930,345.31 CR",
          "/GOODYEAR SOUTH AS",
          f"02-04-2025 IB/TRF/VISHAL {tag}/salary 40,000.00 890,345.31 CR",
          f"03-04-2025 SMS CHARGES {tag} 4.94 890,340.37 CR",
          f"04-04-2025 NEFT/DEUTN5{tag}0351000145 1,740,399.71 2,630,740.08 CR"]
    if ambiguous:
        ls.append(f"05-04-2025 WEIRD {tag} 100.00 200.00 2,630,740.08 CR")
    ls += ["Totals / Balance :- 40,004.94 2,077,053.71 2,630,740.08 CR", "Closing Balance 2,630,740.08 CR"]
    return ls


def _post(admin, raw, name, **data):
    return admin.post(f"{SI}/analyze", files={"file": (name, io.BytesIO(raw), "application/pdf")}, data={"provider": "local", **data})


class TestProviderUnit:
    def _fake(self, exc=None, tables=True):
        from bank_statements.azure_document_intelligence import AzureDocumentIntelligenceProvider

        class R:
            def __init__(s):
                s.page_number = 1

        class C:
            def __init__(s, r, c, v, conf):
                s.row_index, s.column_index, s.content, s.confidence, s.bounding_regions = r, c, v, conf, [R()]

        class T:
            bounding_regions = [R()]
            cells = [C(0, 0, "Date", 0.99), C(0, 1, "Dr Amount", 0.99), C(0, 2, "Cr Amount", 0.99), C(0, 3, "Total Amount", 0.99), C(0, 4, "Particulars", 0.99),
                     C(1, 0, "01-04-2025", 0.98), C(1, 1, "", None), C(1, 2, "336,654.00", 0.97), C(1, 3, "930,345.31 CR", 0.96), C(1, 4, "NEFT/GOODYEAR\nSOUTH ASIA", 0.95),
                     C(2, 0, "02-04-2025", 0.98), C(2, 1, "24,000.00", 0.55), C(2, 2, "", None), C(2, 3, "906,345.31 CR", 0.96), C(2, 4, "IB/NEFT/handewadi", 0.95)]

        class Page:
            lines = []

        class Res:
            def __init__(s):
                s.tables = [T()] if tables else []
                s.pages = [Page()]

        class Poller:
            async def result(s):
                if exc:
                    raise exc
                return Res()

        class Client:
            async def begin_analyze_document(s, **kw):
                return Poller()

            async def close(s):
                pass

        prov = AzureDocumentIntelligenceProvider()
        prov._client = lambda: Client()
        prov.configured = staticmethod(lambda: True)
        return prov

    def _run(self, prov):
        return asyncio.get_event_loop().run_until_complete(prov.analyze(b"%PDF-1.4 fake"))

    def test_not_configured(self, monkeypatch):
        from bank_statements.azure_document_intelligence import AzureDocumentIntelligenceProvider, ExtractionError
        monkeypatch.delenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", raising=False)
        with pytest.raises(ExtractionError) as e:
            self._run(AzureDocumentIntelligenceProvider())
        assert e.value.code == "not_configured" and e.value.http_status == 503

    def test_auth_timeout_ratelimit_empty(self):
        from azure.core.exceptions import HttpResponseError, ClientAuthenticationError
        from bank_statements.azure_document_intelligence import ExtractionError
        for exc, code, http in ((ClientAuthenticationError("bad key"), "auth", 502), (asyncio.TimeoutError(), "timeout", 504)):
            with pytest.raises(ExtractionError) as e:
                self._run(self._fake(exc))
            assert (e.value.code, e.value.http_status) == (code, http)
        err = HttpResponseError("rate")
        err.status_code = 429
        with pytest.raises(ExtractionError) as e:
            self._run(self._fake(err))
        assert e.value.code == "rate_limit" and e.value.http_status == 503
        with pytest.raises(ExtractionError) as e:
            self._run(self._fake(tables=False))
        assert e.value.code == "empty"

    def test_table_cells_normalised_with_confidence(self):
        from bank_statements.statement_normalizer import normalize_statement
        from bank_statements.reconciliation import reconcile
        res = self._run(self._fake())
        assert res.provider == "azure_document_intelligence" and res.model_id == "prebuilt-layout"
        cell = res.tables[0].rows[1][2]
        assert (cell.page, cell.table, cell.row, cell.col, cell.raw, cell.confidence) == (1, 0, 1, 2, "336,654.00", 0.97)
        n = normalize_statement(res, "Saraswat Bank", "")
        rows = n["rows"]
        assert len(rows) == 2
        assert rows[0]["txn"]["direction"] == "credit" and rows[0]["txn"]["amount"] == 336654.0 and rows[0]["running_balance"] == 930345.31
        assert rows[0]["txn"]["narration"] == "NEFT/GOODYEAR SOUTH ASIA"  # multiline cell merged
        assert rows[0]["confidence_band"] == "High" and rows[0]["cells"][4]["header"] == "Particulars"
        assert rows[1]["needs_review"] and "low extraction confidence" in rows[1]["errors"][0] and rows[1]["confidence_band"] == "Needs Review"
        assert n["mapping"]["running_balance"] == "Total Amount" and n["mapping"]["debit_amount"] == "Dr Amount"
        rec = reconcile(rows, None, None)
        assert rec["status"] == "WARNING" and rec["parsed_credit_total"] == "336654.00" and rec["parsed_debit_total"] == "0.00"


class TestRealSaraswatBenchmark:
    @pytest.mark.skipif(not FIXTURE.exists(), reason="real statement fixture missing")
    def test_real_statement_reconciles_exactly(self):
        from bank_statements.azure_document_intelligence import LocalPdfplumberProvider
        from bank_statements.statement_normalizer import normalize_statement, identify_bank
        from bank_statements.reconciliation import reconcile
        res = asyncio.get_event_loop().run_until_complete(LocalPdfplumberProvider().analyze(FIXTURE.read_bytes()))
        assert res.page_count == 5 and identify_bank(res) == "Saraswat Bank"
        n = normalize_statement(res, "Saraswat Bank", "")
        rows = n["rows"]
        assert len(rows) >= 70 and all(not r["needs_review"] for r in rows)
        assert n["period"] == ("2025-04-01", "2026-03-31") and n["account"].endswith("0319")
        for r in rows:
            assert r["txn"]["direction"] in ("debit", "credit") and r["txn"]["amount"] > 0
            assert Decimal(str(r["txn"]["amount"])) != Decimal(str(r["running_balance"]))  # Total Amount never used as amount
        rec = reconcile(rows, n["statement_totals"], n["opening_balance"])
        # control values derived independently by the parser (not hard-coded in production code)
        assert rec["parsed_debit_total"] == "4455610.67" and rec["statement_debit_total"] == "4455610.67"
        assert rec["parsed_credit_total"] == "4560612.33" and rec["statement_credit_total"] == "4560612.33"
        assert rec["parsed_closing_balance"] == "698692.97" and rec["statement_closing_balance"] == "698,692.97 CR"
        assert rec["debit_difference"] == "0.00" and rec["credit_difference"] == "0.00" and rec["closing_balance_difference"] == "0.00"
        assert rec["status"] == "MATCHED" and "successful" in rec["messages"][0]
        assert any("handewadi" in r["txn"]["narration"] for r in rows)  # wrapped particulars merged


class TestHttpFlow:
    @pytest.fixture(autouse=True)
    def _lock(self, txn_state_lock):
        yield

    def test_upload_validation(self, admin):
        assert _post(admin, b"", TAG + "e.pdf").status_code == 422
        assert _post(admin, b"hello not a pdf", TAG + "x.pdf").status_code == 422
        big = b"%PDF-1.4" + b"0" * (16 * 1024 * 1024)
        assert _post(admin, big, TAG + "big.pdf").status_code == 413
        assert requests.post(f"{SI}/analyze", files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")}).status_code == 401
        assert requests.get(f"{SI}/azure/status").status_code == 401

    def test_azure_status_hides_key(self, admin):
        s = admin.get(f"{SI}/azure/status").json()
        assert "key_present" in s and ENV.get("AZURE_DOCUMENT_INTELLIGENCE_KEY", "zz") not in str(s)
        t = admin.post(f"{SI}/azure/test").json()
        assert "configured" in t and "reachable" in t and ENV.get("AZURE_DOCUMENT_INTELLIGENCE_KEY", "zz") not in str(t)

    def test_multipage_analyze_correct_send_audit(self, admin):
        t = TAG + uuid.uuid4().hex[:4].upper()
        raw = _pdf(saraswat_lines(t, ambiguous=True), pages=2)
        before = len(admin.get(f"{API}/transactions").json())
        r = _post(admin, raw, f"{t}.pdf")
        assert r.status_code == 200, r.text
        imp = r.json()
        sid = imp["statement_import_id"]
        assert imp["bank_name"] == "Saraswat Bank" and imp["page_count"] == 2 and imp["extraction_provider"] == "local_pdfplumber"
        assert imp["statement_account_masked"].endswith("0319") and imp["statement_period_from"] == "2025-04-01"
        assert imp["transactions_detected"] == 5 and imp["transactions_valid"] == 4 and imp["transactions_ambiguous"] == 1
        rows = {x["row"]: x for x in imp["rows"]}
        assert rows[1]["txn"]["direction"] == "credit" and rows[1]["txn"]["amount"] == 336654.0 and "GOODYEAR" in rows[1]["txn"]["narration"]
        assert rows[2]["txn"]["direction"] == "debit" and rows[2]["txn"]["amount"] == 40000.0
        assert rows[3]["txn"]["amount"] == 4.94 and rows[4]["txn"]["amount"] == 1740399.71
        assert rows[5]["status"] == "needs_review" and "ambiguous" in rows[5]["errors"][0]
        rec = imp["reconciliation"]
        assert rec["statement_debit_total"] == "40004.94" and rec["parsed_debit_total"] == "40004.94" and rec["debit_difference"] == "0.00"
        assert rec["credit_difference"] == "0.00" and rec["closing_balance_difference"] == "0.00"
        assert rec["status"] == "WARNING" and rec["ambiguous_rows"] == 1  # ambiguous row blocks "successful"
        # manual correction of the ambiguous row → becomes valid, original preserved
        c = admin.put(f"{SI}/{sid}/rows/5", json={"direction": "debit", "amount": 100.0})
        assert c.status_code == 200
        r5 = next(x for x in c.json()["rows"] if x["row"] == 5)
        assert r5["status"] == "valid" and r5["original"]["direction"] == "" and r5["corrections"][0]["after"]["amount"] == 100.0
        assert c.json()["reconciliation_status"] == "FAILED"  # 100 debit now breaks statement totals → mismatch surfaced
        assert admin.put(f"{SI}/{sid}/rows/5", json={"direction": "sideways"}).status_code == 422
        # duplicate PDF upload → previously analyzed
        again = _post(admin, raw, f"{t}.pdf").json()
        assert again["previously_analyzed"] and again["previous"]["statement_import_id"] == sid
        # send rows 1-4 (+5 corrected) to inbox → pending, no finance txns
        s = admin.post(f"{SI}/{sid}/send", json={"rows": [1, 2, 3, 4, 5]}).json()
        assert s["started"] and s["total"] == 5
        import time
        for _ in range(60):
            cur = admin.get(f"{SI}/{sid}").json()
            if cur["processing_status"] != "sending":
                break
            time.sleep(2)
        assert cur["processing_status"] == "sent" and cur["send_progress"]["sent"] == 5 and cur["send_progress"]["duplicates"] == 0
        for x in cur["rows"]:
            assert x["status"] == "sent"
            bt = admin.get(f"{API}/bank-transactions/{x['bank_transaction_id']}").json()
            assert bt["status"] == "pending" and bt["finance_transaction_id"] is None and bt["suggestion"] is not None
        assert len(admin.get(f"{API}/transactions").json()) == before
        # re-send is blocked (state = sent) and re-analysis of same doc points to previous
        assert admin.post(f"{SI}/{sid}/send", json={"rows": [1]}).status_code == 400
        # statement rows already in inbox → a fresh analysis of a different file with same rows flags duplicates
        raw2 = _pdf(saraswat_lines(t) + ["extra footer line"])
        imp2 = _post(admin, raw2, f"{t}-2.pdf").json()
        assert imp2["transactions_duplicate"] == 4 and all(x["duplicate_of_bank_transaction_id"] for x in imp2["rows"] if x["status"] == "duplicate")
        assert imp2["reconciliation"]["debit_difference"] == "0.00"  # duplicates still count toward statement totals
        actions = [a["action"] for a in admin.get(f"{SI}/{sid}/audit").json()]
        for needed in ("statement_pdf_uploaded", "statement_analysis_started", "statement_analysis_completed", "statement_normalized",
                       "statement_row_corrected", "statement_reconciliation_warning", "statement_sent_to_inbox"):
            assert needed in actions, actions
        lst = admin.get(SI).json()
        assert any(x["statement_import_id"] == sid and "rows" not in x for x in lst)

    def test_no_table_pdf(self, admin):
        r = _post(admin, _pdf(["Just a letter", "Nothing tabular here at all but long enough text to be extracted"]), TAG + "nt.pdf")
        assert r.status_code == 422 and r.json()["detail"]["code"] == "no_table"
        imps = admin.get(SI).json()
        assert any(x["processing_status"] == "failed" and x["statement_import_id"] == r.json()["detail"]["statement_import_id"] for x in imps)
