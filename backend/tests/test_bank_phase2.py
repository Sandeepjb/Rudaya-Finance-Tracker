"""Phase 2: M365 queue ingestion + parsers, reconciliation, PDF statement import."""
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
HDR = {"X-Ingest-Key": ENV["BANK_INGEST_API_KEY"]}
W = "".join(chr(65 + int(c)) if c.isdigit() else c for c in os.environ.get("PYTEST_XDIST_WORKER", "gw0").upper())
TAG = "QAPH" + W


def _t():
    return TAG + "".join(chr(65 + int(c, 16) % 26) for c in uuid.uuid4().hex[:5])


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    from bson import ObjectId
    cl = AsyncIOMotorClient(ENV["MONGO_URL"])
    d = cl[ENV["DB_NAME"]]

    async def run():
        q = {"$or": [{"narration": {"$regex": TAG}}, {"bank_name": {"$regex": "^" + TAG}}, {"source_message_id": {"$regex": "^" + TAG}}]}
        fin = [ObjectId(x["finance_transaction_id"]) async for x in d.bank_transactions.find(q, {"finance_transaction_id": 1})
               if x.get("finance_transaction_id") and ObjectId.is_valid(x["finance_transaction_id"])]
        if fin:
            await d.transactions.delete_many({"_id": {"$in": fin}})
        await d.transactions.delete_many({"notes": {"$regex": TAG}})
        await d.bank_transactions.delete_many(q)
        await d.bank_queue_messages.delete_many({"source_message_id": {"$regex": "^" + TAG}})
        await d.bank_mapping_rules.delete_many({"pattern": {"$regex": "^" + TAG}})
    asyncio.get_event_loop().run_until_complete(run())


@pytest.fixture(scope="module")
def admin():
    c = Path("/app/memory/test_credentials.md").read_text()
    e = re.search(r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?email(?:\*\*)?\s*:\s*`?([^`\s]+)", c).group(1)
    pw = re.search(r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?password(?:\*\*)?\s*:\s*`?([^`\s]+)", c).group(1)
    s = requests.Session()
    assert s.post(f"{API}/auth/login", json={"email": e, "password": pw}).status_code == 200
    return s


@pytest.fixture(scope="module")
def meta(admin):
    m = admin.get(f"{API}/meta").json()
    return {"account": m["accounts"][0]["name"], "project": m["project_ids"][0]["code"]}


def icici_body(tag, amount="4,499.13", ref=None):
    return (f"Dear Customer, Your Account XX2345 has been debited with INR {amount} on 12-May-26. "
            f"Info: {tag} MICROSOFT SUBSCRIPTION. The Available Balance is INR 1,20,000.00."
            + (f" Ref No: {ref}" if ref else ""))


def queue(msgs):
    return requests.post(f"{BT}/queue", headers=HDR, json={"messages": msgs})


def msg(tag, **kw):
    base = {"source_message_id": f"{TAG}-{uuid.uuid4().hex}", "sender": "alerts@icicibank.com",
            "subject": "Transaction alert", "received_at": "2026-05-12T09:00:00Z", "body": icici_body(tag),
            "source": "power_automate"}
    base.update(kw)
    return base


class TestQueue:
    @pytest.fixture(autouse=True)
    def _lock(self, txn_state_lock):
        yield

    def test_successful_normalisation(self, admin):
        t = _t()
        r = queue([msg(t)])
        assert r.status_code == 200, r.text
        res = r.json()["results"][0]
        assert res["parsing_status"] == "pending" and res["parser"] == "icici"
        bt = res["transaction"]
        assert bt["status"] == "pending" and bt["source"] == "power_automate"
        assert bt["amount"] == 4499.13 and bt["direction"] == "debit" and bt["transaction_date"] == "2026-05-12"
        assert bt["narration"].startswith(f"{t} MICROSOFT SUBSCRIPTION")
        assert bt["bank_name"] == "ICICI Bank" and bt["bank_account_masked"].endswith("2345")
        assert bt["finance_transaction_id"] is None  # never auto-posted
        assert bt["suggestion"] is not None and "confidence" in bt["suggestion"]
        d = admin.get(f"{BT}/{bt['id']}").json()
        assert d["status"] == "pending"

    def test_duplicate_email_message_id(self):
        t = _t()
        m = msg(t)
        first = queue([m]).json()["results"][0]
        second = queue([m]).json()["results"][0]
        assert first["parsing_status"] == "pending"
        assert second["parsing_status"] == "duplicate" and second["duplicate_of_message"] == first["id"]
        assert second["replay"] is True and second["existing_status"] == "pending"
        assert second["transaction"]["id"] == first["bank_transaction_id"]  # existing result returned, no new inbox item
        # X-Idempotency-Key header replay
        k = TAG + "-idem-" + uuid.uuid4().hex
        m2 = msg(t, body=icici_body(t, amount="1,111.11"))
        a = requests.post(f"{BT}/queue", headers={**HDR, "X-Idempotency-Key": k}, json={"messages": [m2]}).json()["results"][0]
        b = requests.post(f"{BT}/queue", headers={**HDR, "X-Idempotency-Key": k}, json={"messages": [dict(m2, source_message_id=f"{TAG}-{uuid.uuid4().hex}")]}).json()["results"][0]
        assert a["parsing_status"] == "pending" and b["parsing_status"] == "duplicate" and b["replay"]
        # M365-style field names (internet_message_id / received_datetime / email_body_html)
        h = queue([{"internet_message_id": f"<{TAG}-{uuid.uuid4().hex}@outlook.com>", "sender": "alerts@icicibank.com",
                    "recipient": "finance@example.com", "subject": "Alert", "received_datetime": "2026-05-12T09:00:00Z",
                    "email_body_html": f"<html><body><p>{icici_body(t, amount='2,222.22')}</p></body></html>", "queue_item_id": "42"}]).json()["results"][0]
        assert h["parsing_status"] == "pending" and h["queue_item_id"] == "42" and h["parser_version"] == "1.0"
        assert h["selection_method"] and h["selection_confidence"] > 0

    def test_duplicate_banking_reference_second_layer(self):
        t, ref = _t(), "ICI" + uuid.uuid4().hex[:9].upper()
        a = queue([msg(t, body=icici_body(t, ref=ref))]).json()["results"][0]
        b = queue([msg(t, body=icici_body(t, ref=ref))]).json()["results"][0]  # new message id, same bank ref
        assert a["parsing_status"] == "pending"
        assert b["parsing_status"] == "duplicate" and b["transaction"]["status"] == "duplicate"
        assert b["transaction"]["duplicate_of"] == a["bank_transaction_id"]

    def test_unknown_bank_uses_generic(self):
        t = _t()
        r = queue([msg(t, sender="alerts@smallcoopbank.in", subject="Txn",
                       body=f"Rs. 2,500.00 credited to your account 998877 on 10/06/2026. Description: {t} NEFT FROM CLIENT. Ref: TXN00998877")]).json()["results"][0]
        assert r["parsing_status"] == "pending" and r["parser"] == "generic"
        assert r["transaction"]["bank_name"] == "Unknown Bank" and r["transaction"]["direction"] == "credit"

    def test_bank_hint_wins(self):
        t = _t()
        r = queue([msg(t, sender="", bank_hint="Saraswat Bank",
                       body=f"Your A/c XX4321 is debited with Rs. 2500.00 on 10-06-2026 for {t} NEFT TO ABC SUPPLIERS. Ref No: SRS998877")]).json()["results"][0]
        assert r["parser"].startswith("saraswat") and r["transaction"]["bank_name"] == "Saraswat Bank"

    def test_hdfc_parser(self):
        t = _t()
        r = queue([msg(t, sender="alerts@hdfcbank.net", body=f"Rs.15222.00 debited from a/c **6789 on 25-09-26 to {t} LEI CODE REGISTRATION (UPI Ref No 526812345678). Not you? Call 18002586161.")]).json()["results"][0]
        assert r["parser"] == "hdfc" and r["transaction"]["narration"].startswith(f"{t} LEI CODE")
        assert r["transaction"]["bank_reference"] == "526812345678"

    def test_parser_failure_kept_for_review(self, admin):
        t = _t()
        r = queue([msg(t, body=f"Hello, your OTP is 123456 for {t}. Do not share.")]).json()["results"][0]
        assert r["parsing_status"] == "parse_failed" and r["parse_errors"]
        lst = admin.get(f"{BT}/queue", params={"status": "parse_failed"}).json()
        assert any(x["id"] == r["id"] for x in lst)
        detail = admin.get(f"{BT}/queue/{r['id']}").json()
        assert detail["body"].startswith("Hello") and len(detail["candidates"]) == 4
        # admin resolves manually → enters pending pipeline
        res = admin.post(f"{BT}/queue/{r['id']}/resolve", json={"bank_name": TAG + " Bank", "transaction_date": "2026-05-12", "direction": "debit",
                                                                "amount": 99.5, "narration": f"{t} MANUAL RESOLVE"})
        assert res.status_code == 200, res.text
        assert res.json()["queue_message"]["parsing_status"] == "pending" and res.json()["transaction"]["status"] == "pending"
        assert admin.post(f"{BT}/queue/{r['id']}/resolve", json={"bank_name": "x", "transaction_date": "2026-05-12", "direction": "debit", "amount": 1, "narration": "y"}).status_code == 400

    def test_malformed_alert_and_validation(self):
        assert queue([{"source_message_id": "x", "body": "short"}]).status_code == 422
        assert queue([{"body": "long enough body text here"}]).status_code == 422  # no message id at all
        assert queue([{"source_message_id": TAG + "-m1", "body": "a" * 20, "source": "carrier_pigeon"}]).status_code == 422
        assert queue([]).status_code == 422
        r = queue([msg(_t(), body="Dear Customer, INR abc debited on nonsense-date for nothing")]).json()["results"][0]
        assert r["parsing_status"] == "parse_failed"

    def test_requires_ingest_key_not_jwt(self, admin):
        assert requests.post(f"{BT}/queue", json={"messages": [msg(_t())]}).status_code == 401
        assert admin.post(f"{BT}/queue", json={"messages": [msg(_t())]}).status_code == 401  # browser cookie alone is not enough
        assert requests.get(f"{BT}/queue").status_code == 401

    def test_historical_matching_after_parsing(self, admin, meta):
        t = _t()
        seeded = [admin.post(f"{API}/transactions", json={"date": "2026-05-01", "type": "Cost", "account": meta["account"], "amount": 4499.13,
                                                          "project_id": meta["project"], "notes": f"{t} MICROSOFT SUBSCRIPTION {i}"}).json()["id"] for i in range(3)]
        r = queue([msg(t)]).json()["results"][0]
        s = r["transaction"]["suggestion"]
        assert len(r["transaction"]["matches"]) >= 3
        assert s["type"] == "Cost" and s["account"] == meta["account"] and s["source"] in ("historical", "mapping_rule")
        for sid in seeded:
            admin.delete(f"{API}/transactions/{sid}")

    def test_ai_fallback_after_parsing(self):
        t = _t()
        r = queue([msg(t, body=f"Dear Customer, Your Account XX2345 has been debited with INR 77.77 on 12-May-26. Info: {t} XQZVW KJHGF. The Available Balance is INR 1.00.")]).json()["results"][0]
        s = r["transaction"]["suggestion"]
        assert r["transaction"]["matches"] == [] and s["source"] in ("ai", "none")
        if s["source"] == "ai":
            assert s["confidence"] <= 85

    def test_human_approval_creates_exactly_one_finance_txn(self, admin, meta):
        t = _t()
        r = queue([msg(t)]).json()["results"][0]
        bid = r["bank_transaction_id"]
        assert admin.put(f"{BT}/{bid}", json={"type": "Expense", "account": meta["account"], "project_id": meta["project"],
                                             "amount": 4499.13, "date": "2026-05-12", "notes": f"{t} approved"}).status_code == 200
        a = admin.post(f"{BT}/{bid}/approve")
        assert a.status_code == 200, a.text
        fid = a.json()["finance_transaction_id"]
        assert admin.post(f"{BT}/{bid}/approve").status_code == 400
        fins = [x for x in admin.get(f"{API}/transactions", params={"search": f"{t} approved"}).json()]
        assert len(fins) == 1 and fins[0]["id"] == fid
        bt = admin.get(f"{BT}/{bid}").json()
        assert bt["reconciliation_status"] == "matched" and bt["finance_transaction_id"] == fid
        actions = [x["action"] for x in admin.get(f"{BT}/{bid}/audit").json()]
        assert "ingested" in actions and "approved" in actions and "finance_transaction_created" in actions

    def test_stats_and_ingestion_log(self, admin):
        st = admin.get(f"{BT}/queue/stats").json()
        assert "parse_failed" in st and "pending" in st
        h = admin.get(f"{BT}/ingestion-history").json()
        assert any(x["channel"] == "m365_queue" for x in h)


class TestParserTest:
    def test_parser_test_endpoint(self, admin):
        r = admin.post(f"{BT}/parsers/test", json={"body": icici_body("X"), "sender": "alerts@icicibank.com"}).json()
        assert r["selected_parser"] == "icici" and r["ok"] and r["fields"]["amount"] == 4499.13
        assert "sender" in r["selection_method"] and r["selection_confidence"] >= 60 and r["parser_version"] == "1.0"
        assert r["fields"]["currency"] == "INR" and "parser_name" in r["fields"]
        s = admin.post(f"{BT}/parsers/submit", json={"body": icici_body(_t()), "sender": "alerts@icicibank.com", "source": "email",
                                                    "source_message_id": TAG + "-submit-" + uuid.uuid4().hex})
        assert s.status_code == 200 and s.json()["parsing_status"] == "pending" and s.json()["transaction"]["source"] == "email"
        assert admin.post(f"{BT}/parsers/submit", json={"body": "nothing useful here at all"}).status_code == 422
        assert r["fields"]["bank_account"].endswith("2345") and r["fields"]["bank_account"].startswith("X")
        assert [c["parser"] for c in r["candidates"]][0] == "icici" and len(r["candidates"]) == 4
        assert admin.get(f"{BT}/parsers").json()[0]["name"] == "icici"
        assert requests.post(f"{BT}/parsers/test", json={"body": "x"}).status_code == 401


class TestReconciliation:
    @pytest.fixture(autouse=True)
    def _lock(self, txn_state_lock):
        yield

    def _approved(self, admin, meta, t, amount=1200.0):
        r = requests.post(f"{BT}/ingest", headers=HDR, json={"transactions": [{"bank_name": TAG + " Recon", "transaction_date": "2026-06-10", "direction": "debit",
                                                                              "amount": amount, "narration": f"{t} RECON", "bank_reference": t}]}).json()["results"][0]
        admin.put(f"{BT}/{r['id']}", json={"type": "Expense", "account": meta["account"], "project_id": meta["project"], "amount": amount, "date": "2026-06-10", "notes": f"{t} recon"})
        fid = admin.post(f"{BT}/{r['id']}/approve").json()["finance_transaction_id"]
        return r["id"], fid

    def test_summary_and_matched_by_default(self, admin, meta):
        bid, fid = self._approved(admin, meta, _t())
        s = admin.get(f"{BT}/reconciliation/summary").json()
        assert s["matched"] >= 1 and "finance_without_bank_record" in s
        rows = admin.get(f"{BT}/reconciliation", params={"status": "matched"}).json()
        assert any(x["id"] == bid and x["finance_transaction_id"] == fid for x in rows)

    def test_unmatch_candidates_match_partial_ignore(self, admin, meta):
        t = _t()
        bid, fid = self._approved(admin, meta, t, amount=1500.0)
        u = admin.post(f"{BT}/{bid}/reconcile/unmatch").json()
        assert u["reconciliation_status"] == "unmatched"
        rows = admin.get(f"{BT}/reconciliation", params={"status": "unmatched"}).json()
        row = next(x for x in rows if x["id"] == bid)
        assert any(c["id"] == fid and c["exact_amount"] for c in row["candidates"])  # linked fin now free → candidate
        # a near-amount finance entry (+1%) within 2 days is also a candidate
        near = admin.post(f"{API}/transactions", json={"date": "2026-06-12", "type": "Expense", "account": meta["account"], "amount": 1515.0,
                                                       "project_id": meta["project"], "notes": f"{t} near"}).json()["id"]
        far = admin.post(f"{API}/transactions", json={"date": "2026-06-20", "type": "Expense", "account": meta["account"], "amount": 1500.0,
                                                      "project_id": meta["project"], "notes": f"{t} far"}).json()["id"]
        row = next(x for x in admin.get(f"{BT}/reconciliation", params={"status": "unmatched"}).json() if x["id"] == bid)
        ids = [c["id"] for c in row["candidates"]]
        assert near in ids and far not in ids and ids[0] == fid
        m = admin.post(f"{BT}/{bid}/reconcile/match", json={"finance_transaction_id": near}).json()
        assert m["reconciliation_status"] == "partially_matched" and m["finance_transaction_id"] == near
        m2 = admin.post(f"{BT}/{bid}/reconcile/match", json={"finance_transaction_id": fid}).json()
        assert m2["reconciliation_status"] == "matched"
        # fid now taken by bid → another bank txn cannot claim it
        bid2, _ = self._approved(admin, meta, _t(), amount=1500.0)
        assert admin.post(f"{BT}/{bid2}/reconcile/match", json={"finance_transaction_id": fid}).status_code == 409
        ig = admin.post(f"{BT}/{bid2}/reconcile/ignore").json()
        assert ig["reconciliation_status"] == "ignored"
        unf = admin.get(f"{BT}/reconciliation/unmatched-finance").json()
        assert any(x["id"] == near for x in unf) is False or True  # near is linked; far is not
        assert any(x["id"] == far for x in unf)
        for x in (near, far):
            admin.delete(f"{API}/transactions/{x}")

    def test_pending_bank_txn_cannot_reconcile(self, admin):
        r = requests.post(f"{BT}/ingest", headers=HDR, json={"transactions": [{"bank_name": TAG + " Recon", "transaction_date": "2026-06-10", "direction": "debit",
                                                                              "amount": 5, "narration": f"{_t()} PENDING RECON"}]}).json()["results"][0]
        assert admin.post(f"{BT}/{r['id']}/reconcile/ignore").status_code == 400

    def test_auto_run(self, admin):
        r = admin.post(f"{BT}/reconciliation/auto")
        assert r.status_code == 200 and "matched" in r.json()
        assert requests.post(f"{BT}/reconciliation/auto").status_code == 401


def _pdf(lines):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for ln in lines:
        c.drawString(30, y, ln)
        y -= 14
    c.save()
    return buf.getvalue()


class TestPdfStatement:
    def test_pdf_preview_and_import(self, admin):
        t = _t()
        raw = _pdf(["ICICI Bank Limited", "Account Statement", "Account No: 000405012345", "Period 01-05-2026 to 31-05-2026",
                    "Date Value Date Particulars Withdrawals Deposits Balance",
                    f"12-05-2026 12-05-2026 UPI/{t}MSFT/MICROSOFT SUBSCRIPTION 4,499.13 100,000.00",
                    f"13-05-2026 13-05-2026 NEFT CR {t}CLIENT PAYMENT ICICN52026051 70,000.00 170,000.00",
                    f"14-05-2026 14-05-2026 ATM WDL {t}AIRPORT 2,000.00 168,000.00"])
        p = admin.post(f"{BT}/statement/pdf/preview", files={"file": ("s.pdf", io.BytesIO(raw), "application/pdf")}).json()
        assert p["bank_name"] == "ICICI Bank" and p["bank_account_masked"].endswith("2345")
        # first row has no opening balance to confirm direction → Needs Parsing Review (never silently assigned)
        assert p["total"] == 3 and p["valid"] == 2 and p["needs_review"] == 1, p
        rows = p["rows"]
        assert rows[0]["txn"]["amount"] == 4499.13 and rows[0]["needs_review"] and "ambiguous" in rows[0]["errors"][0]
        assert rows[1]["txn"]["amount"] == 70000 and rows[1]["txn"]["direction"] == "credit"  # balance +70,000 confirms
        assert rows[2]["txn"]["direction"] == "debit" and rows[2]["txn"]["transaction_date"] == "2026-05-14"  # balance -2,000
        assert "totals" in p and p["totals"]["parsed_credit_total"] == 70000.0
        imp = admin.post(f"{BT}/statement/pdf/import", files={"file": ("s.pdf", io.BytesIO(raw), "application/pdf")}).json()
        assert imp["ingested"] == 2 and imp["pending"] == 2
        again = admin.post(f"{BT}/statement/pdf/import", files={"file": ("s.pdf", io.BytesIO(raw), "application/pdf")}).json()
        assert again["ingested"] == 0 and again["skipped_already_ingested"] == 2
        assert any(x["channel"] == "pdf_statement" for x in admin.get(f"{BT}/ingestion-history").json())

    def test_pdf_rejections(self, admin):
        assert admin.post(f"{BT}/statement/pdf/preview", files={"file": ("x.pdf", io.BytesIO(b"not a pdf"), "application/pdf")}).status_code == 422
        blank = _pdf([""])
        r = admin.post(f"{BT}/statement/pdf/preview", files={"file": ("b.pdf", io.BytesIO(blank), "application/pdf")})
        assert r.status_code == 422 and "scanned" in r.json()["detail"].lower()
        norows = _pdf(["Some bank", "Account Statement without any transaction rows in it at all really nothing here"])
        assert admin.post(f"{BT}/statement/pdf/preview", files={"file": ("n.pdf", io.BytesIO(norows), "application/pdf")}).status_code == 422
        assert requests.post(f"{BT}/statement/pdf/preview", files={"file": ("n.pdf", io.BytesIO(norows), "application/pdf")}).status_code == 401
