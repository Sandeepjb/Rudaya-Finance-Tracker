"""Duplicate review (human-in-the-loop): compare, approve-as-new, reject-as-duplicate, idempotency, audit, counters."""
import os
import re
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"]).rstrip("/")
API = f"{BASE_URL}/api"
BT = f"{API}/bank-transactions"
ENV = dotenv_values("/app/backend/.env")
HDR = {"X-Ingest-Key": ENV["BANK_INGEST_API_KEY"]}
W = "".join(chr(65 + int(c)) if c.isdigit() else c for c in os.environ.get("PYTEST_XDIST_WORKER", "gw0").upper())
BANK = "DupQA Bank " + W


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    from bson import ObjectId
    cl = AsyncIOMotorClient(ENV["MONGO_URL"])
    d = cl[ENV["DB_NAME"]]

    async def run():
        fin = [ObjectId(x["finance_transaction_id"]) async for x in d.bank_transactions.find({"bank_name": BANK}, {"finance_transaction_id": 1})
               if x.get("finance_transaction_id")]
        if fin:
            await d.transactions.delete_many({"_id": {"$in": fin}})
        ids = [str(x["_id"]) async for x in d.bank_transactions.find({"bank_name": BANK}, {"_id": 1})]
        await d.bank_transactions.delete_many({"bank_name": BANK})
        await d.bank_audit_log.delete_many({"bank_transaction_id": {"$in": ids}})
        await d.bank_mapping_rules.delete_many({"pattern": {"$regex": "^DUPQA" + W}})
    asyncio.get_event_loop().run_until_complete(run())
    cl.close()


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


def _txn(**kw):
    base = {"bank_name": BANK, "bank_account": "999900001234", "transaction_date": "2026-09-18", "transaction_time": "17:48",
            "direction": "credit", "amount": 4250.0, "narration": f"DUPQA{W} RAZAGIONE TECHNOLOGIES {uuid.uuid4().hex[:5].upper()}",
            "bank_reference": f"DQ{uuid.uuid4().hex[:10].upper()}", "source": "power_automate"}
    base.update(kw)
    return base


def ingest(t):
    return requests.post(f"{BT}/ingest", json={"transactions": [t]}, headers=HDR).json()["results"][0]


def make_pair():
    t = _txn()
    first = ingest(t)
    dup = ingest(t)
    assert first["status"] == "pending" and dup["status"] == "duplicate" and dup["duplicate_of"] == first["id"]
    return first, dup


def edit(admin, tid, meta):
    return admin.put(f"{BT}/{tid}", json={"type": "Revenue", "account": meta["account"], "project_id": meta["project"],
                                          "amount": 4250.0, "date": "2026-09-18", "notes": "dup review qa"})


def finance_count(admin, bank_txn_id):
    """Count accounting entries linked to a bank transaction — read straight from MongoDB (the real invariant)."""
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    cl = AsyncIOMotorClient(ENV["MONGO_URL"])
    n = asyncio.get_event_loop().run_until_complete(cl[ENV["DB_NAME"]].transactions.count_documents({"bank_transaction_id": bank_txn_id}))
    cl.close()
    return n


class TestDetectionMetadata:
    def test_duplicate_has_score_and_reasons(self, admin):
        first, dup = make_pair()
        assert dup["duplicate_score"] >= 80
        assert "Same amount" in dup["duplicate_detection_reason"] and any("reference" in r for r in dup["duplicate_detection_reason"])
        c = admin.get(f"{BT}/{dup['id']}/duplicate").json()
        assert c["transaction"]["id"] == dup["id"] and c["match"]["id"] == first["id"]
        assert c["reviewable"] is True and c["score"] == dup["duplicate_score"] and c["date_diff_days"] == 0

    def test_compare_on_non_duplicate_is_400(self, admin):
        t = ingest(_txn())
        assert admin.get(f"{BT}/{t['id']}/duplicate").status_code == 400

    def test_legacy_duplicate_without_metadata_is_reviewable(self, admin):
        """Records created before this release have no score/reasons stored — analysis is computed on the fly."""
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        from bson import ObjectId
        first, dup = make_pair()
        cl = AsyncIOMotorClient(ENV["MONGO_URL"])
        asyncio.get_event_loop().run_until_complete(cl[ENV["DB_NAME"]].bank_transactions.update_one(
            {"_id": ObjectId(dup["id"])}, {"$unset": {"duplicate_score": "", "duplicate_detection_reason": ""}}))
        cl.close()
        c = admin.get(f"{BT}/{dup['id']}/duplicate").json()
        assert c["score"] > 0 and c["reasons"] and c["reviewable"]
        r = admin.post(f"{BT}/{dup['id']}/duplicate/reject", json={"note": "legacy"})
        assert r.status_code == 200 and r.json()["transaction"]["status"] == "duplicate_rejected"


class TestRejectAsDuplicate:
    def test_reject_keeps_record_no_accounting(self, admin):
        first, dup = make_pair()
        r = admin.post(f"{BT}/{dup['id']}/duplicate/reject", json={"note": "same UPI ref"})
        assert r.status_code == 200
        t = r.json()["transaction"]
        assert t["status"] == "duplicate_rejected" and t["duplicate_of"] == first["id"]
        assert t["duplicate_review_action"] == "rejected_duplicate" and t["duplicate_reviewed_by"] and t["duplicate_reviewed_at"]
        assert t["finance_transaction_id"] is None and finance_count(admin, dup["id"]) == 0
        # second decision is refused, original untouched
        assert admin.post(f"{BT}/{dup['id']}/duplicate/approve", json={"reason": "changed my mind"}).status_code == 400
        assert admin.post(f"{BT}/{dup['id']}/duplicate/reject", json={}).status_code == 400
        assert admin.get(f"{BT}/{first['id']}").json()["status"] == "pending"
        acts = [a["action"] for a in admin.get(f"{BT}/{dup['id']}/audit").json()]
        assert "duplicate_detected" in acts and "duplicate_rejected" in acts

    def test_rejected_duplicate_listed_in_duplicates_tab_not_pending(self, admin):
        _, dup = make_pair()
        admin.post(f"{BT}/{dup['id']}/duplicate/reject", json={})
        ids = {x["id"] for x in admin.get(BT, params={"status": "duplicate", "bank": BANK}).json()}
        assert dup["id"] in ids
        assert dup["id"] not in {x["id"] for x in admin.get(BT, params={"status": "pending", "bank": BANK}).json()}
        assert dup["id"] not in {x["id"] for x in admin.get(BT, params={"status": "rejected", "bank": BANK}).json()}


class TestApproveAsNew:
    def test_reason_required(self, admin):
        _, dup = make_pair()
        assert admin.post(f"{BT}/{dup['id']}/duplicate/approve", json={"reason": "no"}).status_code == 422
        assert admin.post(f"{BT}/{dup['id']}/duplicate/approve", json={}).status_code == 422
        assert admin.get(f"{BT}/{dup['id']}").json()["status"] == "duplicate"

    def test_false_positive_approve_exactly_one_entry(self, admin, meta):
        first, dup = make_pair()
        r = admin.post(f"{BT}/{dup['id']}/duplicate/approve", json={"reason": "Separate transaction with same vendor and amount"})
        assert r.status_code == 200
        t = r.json()["transaction"]
        assert t["status"] == "pending" and t["duplicate_of"] == first["id"] and t["duplicate_review_action"] == "approved_as_new"
        assert t["duplicate_override_reason"].startswith("Separate") and t["duplicate_reviewed_by"] and t["suggestion"] is not None
        # override is idempotent: second click / API retry → 400, still pending, no entry
        assert admin.post(f"{BT}/{dup['id']}/duplicate/approve", json={"reason": "retry click"}).status_code == 400
        assert admin.post(f"{BT}/{dup['id']}/duplicate/reject", json={}).status_code == 400
        assert finance_count(admin, dup["id"]) == 0
        # normal workflow: edit → approve & post → exactly one accounting entry
        assert edit(admin, dup["id"], meta).status_code == 200
        a1 = admin.post(f"{BT}/{dup['id']}/approve")
        assert a1.status_code == 200 and a1.json()["finance_transaction_id"]
        a2 = admin.post(f"{BT}/{dup['id']}/approve")
        assert a2.status_code == 400
        assert finance_count(admin, dup["id"]) == 1
        final = admin.get(f"{BT}/{dup['id']}").json()
        assert final["status"] == "approved" and final["duplicate_of"] == first["id"] and final["duplicate_score"] is not None
        # original never modified
        assert admin.get(f"{BT}/{first['id']}").json()["status"] == "pending"
        acts = [a["action"] for a in admin.get(f"{BT}/{dup['id']}/audit").json()]
        assert acts.index("duplicate_detected") < acts.index("duplicate_approved_as_new") < acts.index("approved")
        assert acts.count("finance_transaction_created") == 1

    def test_overridden_record_is_not_reimported_as_new(self, admin):
        t = _txn()
        first = ingest(t)
        dup = ingest(t)
        admin.post(f"{BT}/{dup['id']}/duplicate/approve", json={"reason": "legit second payment"})
        again = ingest(t)
        assert again["status"] == "duplicate" and again["duplicate_of"] in (first["id"], dup["id"])

    def test_already_approved_cannot_be_reviewed_again(self, admin, meta):
        _, dup = make_pair()
        admin.post(f"{BT}/{dup['id']}/duplicate/approve", json={"reason": "legit second payment"})
        edit(admin, dup["id"], meta)
        assert admin.post(f"{BT}/{dup['id']}/approve").status_code == 200
        assert admin.post(f"{BT}/{dup['id']}/duplicate/approve", json={"reason": "again please"}).status_code == 400
        assert admin.post(f"{BT}/{dup['id']}/duplicate/reject", json={}).status_code == 400
        assert finance_count(admin, dup["id"]) == 1


class TestCounters:
    def test_stats_single_primary_status(self, admin, meta):
        s0 = admin.get(f"{BT}/stats").json()
        _, d1 = make_pair()
        _, d2 = make_pair()
        _, d3 = make_pair()
        s1 = admin.get(f"{BT}/stats").json()
        assert s1["duplicate"] == s0["duplicate"] + 3 and s1["pending"] == s0["pending"] + 3 and s1["all"] == s0["all"] + 6
        admin.post(f"{BT}/{d1['id']}/duplicate/reject", json={})
        admin.post(f"{BT}/{d2['id']}/duplicate/approve", json={"reason": "separate payment"})
        s2 = admin.get(f"{BT}/stats").json()
        assert s2["duplicate"] == s1["duplicate"] - 2 and s2["duplicate_rejected"] == s1.get("duplicate_rejected", 0) + 1
        assert s2["pending"] == s1["pending"] + 1 and s2["rejected"] == s1["rejected"] and s2["all"] == s1["all"]
        assert s2["all"] == sum(v for k, v in s2.items() if k != "all")
