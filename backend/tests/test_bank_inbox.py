"""Bank Transaction Inbox tests: ingestion, duplicates, classification layers, approval, edit, reject, learning, audit."""
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
INGEST_KEY = ENV["BANK_INGEST_API_KEY"]
HDR = {"X-Ingest-Key": INGEST_KEY}


@pytest.fixture(scope="module", autouse=True)
def cleanup_qa_data():
    yield
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    cl = AsyncIOMotorClient(ENV["MONGO_URL"])
    d = cl[ENV["DB_NAME"]]

    async def run():
        tag_re = {"$regex": "^(ZEBRAHOSTING|GIRAFFECLOUD|CLIENTPAYIN|LEARNCO|STABLECO|RULECRUD)"}
        await d.transactions.delete_many({"$or": [{"notes": tag_re}, {"source": "bank_transaction",
                                                                        "notes": {"$regex": "^(QA NARRATION|approved via qa|edited|learn|audit|LEARNCO|STABLECO|RULECRUD)"}}]})
        await d.transactions.delete_many({"source": "bank_transaction", "created_by": {"$regex": "bankqa_"}})
        await d.bank_transactions.delete_many({"bank_name": {"$in": ["QA Bank", "FilterBank"]}})
        await d.bank_mapping_rules.delete_many({"pattern": tag_re})
        await d.users.delete_many({"email": {"$regex": "^bankqa_"}})
    asyncio.get_event_loop().run_until_complete(run())
    cl.close()


@pytest.fixture(scope="module")
def creds():
    c = Path("/app/memory/test_credentials.md").read_text()
    e = re.search(r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?email(?:\*\*)?\s*:\s*`?([^`\s]+)", c).group(1)
    pw = re.search(r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?password(?:\*\*)?\s*:\s*`?([^`\s]+)", c).group(1)
    return {"email": e, "password": pw}


@pytest.fixture(scope="module")
def admin(creds):
    s = requests.Session()
    assert s.post(f"{API}/auth/login", json=creds).status_code == 200
    return s


@pytest.fixture(scope="module")
def member():
    s = requests.Session()
    email = f"bankqa_{uuid.uuid4().hex[:8]}@example.com"
    r = s.post(f"{API}/auth/register", json={"email": email, "password": "Member@12345", "name": "QA Member"})
    assert r.status_code in (200, 201), r.text
    return s


@pytest.fixture(scope="module")
def meta(admin):
    m = admin.get(f"{API}/meta").json()
    assert m["accounts"] and m["project_ids"]
    return {"account": m["accounts"][0]["name"], "project": m["project_ids"][0]["code"], "raw": m}


def _alpha_tag(n=5):
    return "".join(chr(65 + int(c, 16) % 26) for c in uuid.uuid4().hex[:n])


def _txn(**kw):
    base = {"bank_name": "QA Bank", "bank_account": "111122223333", "transaction_date": "2026-05-10",
            "direction": "debit", "amount": 1234.5, "narration": f"QA NARRATION {uuid.uuid4().hex[:6].upper()}",
            "bank_reference": f"QAREF{uuid.uuid4().hex[:10].upper()}", "source": "power_automate"}
    base.update(kw)
    return base


def ingest(txns):
    return requests.post(f"{BT}/ingest", json={"transactions": txns}, headers=HDR)


class TestIngestion:
    def test_valid_ingestion(self):
        r = ingest([_txn()])
        assert r.status_code == 200, r.text
        res = r.json()["results"][0]
        assert res["status"] == "pending"
        assert res["suggestion"] is not None and "confidence" in res["suggestion"]
        assert res["bank_account_masked"].endswith("3333") and res["bank_account_masked"].startswith("X")
        assert res["reconciliation_status"] == "unmatched"

    def test_missing_mandatory_fields(self):
        t = _txn(); del t["narration"]
        assert ingest([t]).status_code == 422
        t = _txn(); del t["amount"]
        assert ingest([t]).status_code == 422

    def test_invalid_amount(self):
        assert ingest([_txn(amount=0)]).status_code == 422
        assert ingest([_txn(amount=-5)]).status_code == 422

    def test_invalid_direction(self):
        assert ingest([_txn(direction="sideways")]).status_code == 422

    def test_invalid_date_and_source(self):
        assert ingest([_txn(transaction_date="2026/13/01")]).status_code == 422
        assert ingest([_txn(source="carrier_pigeon")]).status_code == 422

    def test_date_formats_normalised(self):
        r = ingest([_txn(transaction_date="15/04/2026")]).json()["results"][0]
        assert r["transaction_date"] == "2026-04-15"

    def test_unauthorized_ingest(self):
        assert requests.post(f"{BT}/ingest", json={"transactions": [_txn()]}).status_code == 401
        assert requests.post(f"{BT}/ingest", json={"transactions": [_txn()]}, headers={"X-Ingest-Key": "nope"}).status_code == 401

    def test_batch_limit(self):
        r = ingest([_txn() for _ in range(101)])
        assert r.status_code == 422


class TestDuplicates:
    def test_same_transaction_twice(self):
        t = _txn()
        first = ingest([t]).json()["results"][0]
        second = ingest([t]).json()["results"][0]
        assert first["status"] == "pending"
        assert second["status"] == "duplicate"
        assert second["duplicate_of"] == first["id"]
        assert second["fingerprint"] == first["fingerprint"]

    def test_duplicate_by_reference_ignores_narration_noise(self):
        t = _txn(bank_reference="QAREFSAME" + uuid.uuid4().hex[:6].upper())
        ingest([t])
        t2 = dict(t, narration=t["narration"] + " EXTRA TOKEN")
        assert ingest([t2]).json()["results"][0]["status"] == "duplicate"

    def test_duplicate_by_source_message_id(self):
        mid = "msg-" + uuid.uuid4().hex
        ingest([_txn(bank_reference="", source_message_id=mid)])
        r = ingest([_txn(bank_reference="", source_message_id=mid, amount=999)]).json()["results"][0]
        assert r["status"] == "duplicate"

    def test_no_reference_uses_narration_fingerprint(self):
        t = _txn(bank_reference="")
        ingest([t])
        assert ingest([t]).json()["results"][0]["status"] == "duplicate"
        t3 = dict(t, amount=t["amount"] + 1)
        assert ingest([t3]).json()["results"][0]["status"] == "pending"

    def test_duplicate_inspect_original(self, admin):
        t = _txn()
        first = ingest([t]).json()["results"][0]
        dup = ingest([t]).json()["results"][0]
        d = admin.get(f"{BT}/{dup['id']}").json()
        assert d["duplicate_of_txn"]["id"] == first["id"]

    def test_duplicate_cannot_be_approved(self, admin):
        t = _txn()
        ingest([t])
        dup = ingest([t]).json()["results"][0]
        assert admin.post(f"{BT}/{dup['id']}/approve").status_code == 400


class TestClassification:
    def test_historical_exact_match(self, admin, meta):
        tag = "ZEBRAHOSTING " + _alpha_tag()
        for _ in range(3):
            admin.post(f"{API}/transactions", json={"date": "2026-03-01", "type": "Cost", "account": meta["account"],
                                                    "amount": 5000, "project_id": meta["project"], "notes": f"{tag} monthly"})
        r = ingest([_txn(narration=f"{tag} MONTHLY 998877", amount=5000)]).json()["results"][0]
        s = r["suggestion"]
        assert len(r["matches"]) >= 3
        assert s["type"] == "Cost" and s["account"] == meta["account"] and s["project_id"] == meta["project"]
        assert s["source"] in ("historical", "mapping_rule")
        assert s["confidence"] >= 70
        assert any("closest matches" in x for x in s["reasons"])
        assert any("Exact amount" in x for x in s["reasons"])

    def test_historical_similarity_match_different_amount(self, admin, meta):
        tag = "GIRAFFECLOUD " + _alpha_tag()
        admin.post(f"{API}/transactions", json={"date": "2026-03-01", "type": "Expense", "account": meta["account"],
                                                "amount": 800, "project_id": meta["project"], "notes": f"{tag} services"})
        r = ingest([_txn(narration=f"{tag} SERVICES 1234567", amount=3200)]).json()["results"][0]
        assert r["matches"] and r["matches"][0]["similarity"] > 0.3
        assert r["suggestion"]["account"] == meta["account"]

    def test_debit_not_assumed_expense(self, admin, meta):
        tag = "CLIENTPAYIN " + _alpha_tag()
        for _ in range(2):
            admin.post(f"{API}/transactions", json={"date": "2026-03-01", "type": "Revenue", "account": meta["account"],
                                                    "amount": 70000, "project_id": meta["project"], "notes": f"{tag} invoice"})
        r = ingest([_txn(narration=f"{tag} INVOICE 5566", amount=70000, direction="debit")]).json()["results"][0]
        assert r["suggestion"]["type"] == "Revenue"

    def test_low_confidence_or_ai_fallback_for_unknown(self):
        r = ingest([_txn(narration="XQZVWPLM KJHGFD 99887766", amount=77.77)]).json()["results"][0]
        s = r["suggestion"]
        assert r["matches"] == []
        assert s["source"] in ("ai", "none")
        if s["source"] == "ai":
            assert s["confidence"] <= 85 and any("AI-assisted" in x for x in s["reasons"])
        else:
            assert s["confidence"] == 0 and s["type"] is None

    def test_reclassify(self, admin):
        r = ingest([_txn()]).json()["results"][0]
        rr = admin.post(f"{BT}/{r['id']}/reclassify")
        assert rr.status_code == 200 and rr.json()["suggestion"] is not None


class TestApprovalFlow:
    def test_approve_creates_exactly_one_finance_txn(self, admin, meta):
        r = ingest([_txn()]).json()["results"][0]
        e = admin.put(f"{BT}/{r['id']}", json={"type": "Expense", "account": meta["account"], "project_id": meta["project"],
                                              "amount": r["amount"], "date": r["transaction_date"], "notes": "approved via qa"})
        assert e.status_code == 200
        a = admin.post(f"{BT}/{r['id']}/approve")
        assert a.status_code == 200, a.text
        fid = a.json()["finance_transaction_id"]
        txns = [t for t in admin.get(f"{API}/transactions", params={"search": "approved via qa"}).json() if t["id"] == fid]
        assert len(txns) == 1
        assert txns[0]["type"] == "Expense" and txns[0]["amount"] == r["amount"]
        d = admin.get(f"{BT}/{r['id']}").json()
        assert d["status"] == "approved" and d["finance_transaction_id"] == fid
        assert d["reconciliation_status"] == "matched"
        # repeated approval must not create a second one
        assert admin.post(f"{BT}/{r['id']}/approve").status_code == 400
        all_fin = admin.get(f"{API}/transactions", params={"search": "approved via qa"}).json()
        assert sum(1 for t in all_fin if t["id"] == fid) == 1

    def test_edit_before_approve_tracks_modified_fields(self, admin, meta):
        r = ingest([_txn()]).json()["results"][0]
        other_proj = meta["raw"]["project_ids"][-1]["code"]
        e = admin.put(f"{BT}/{r['id']}", json={"type": "Cost", "account": meta["account"], "project_id": other_proj,
                                              "amount": r["amount"] + 10, "date": r["transaction_date"], "notes": "edited"}).json()
        assert e["user_edits"]["type"] == "Cost"
        assert "amount" in e["modified_fields"] and "notes" in e["modified_fields"]
        a = admin.post(f"{BT}/{r['id']}/approve").json()
        assert a["transaction"]["final"]["project_id"] == other_proj
        assert "amount" in a["modified_fields"]
        fin = [t for t in admin.get(f"{API}/transactions", params={"search": "edited"}).json() if t["id"] == a["finance_transaction_id"]]
        assert fin and fin[0]["amount"] == r["amount"] + 10

    def test_edit_validation(self, admin, meta):
        r = ingest([_txn()]).json()["results"][0]
        bad = {"type": "Gift", "account": meta["account"], "project_id": meta["project"], "amount": 1, "date": "2026-01-01"}
        assert admin.put(f"{BT}/{r['id']}", json=bad).status_code == 422
        bad["type"] = "Cost"; bad["amount"] = -1
        assert admin.put(f"{BT}/{r['id']}", json=bad).status_code == 422

    def test_approve_incomplete_suggestion_blocked(self, admin):
        r = ingest([_txn(narration="QQQWWWEEE RRRTTTYYY 5544332211", amount=13.13)]).json()["results"][0]
        if r["suggestion"]["type"] is None:
            assert admin.post(f"{BT}/{r['id']}/approve").status_code == 422

    def test_approve_rejects_unknown_master_data(self, admin):
        r = ingest([_txn()]).json()["results"][0]
        admin.put(f"{BT}/{r['id']}", json={"type": "Cost", "account": "Nonexistent Acc " + uuid.uuid4().hex[:4],
                                          "project_id": "NOPE", "amount": 1, "date": "2026-01-01"})
        assert admin.post(f"{BT}/{r['id']}/approve").status_code == 422

    def test_reject_keeps_record(self, admin):
        r = ingest([_txn()]).json()["results"][0]
        assert admin.post(f"{BT}/{r['id']}/reject", json={"reason": "personal"}).status_code == 200
        d = admin.get(f"{BT}/{r['id']}").json()
        assert d["status"] == "rejected" and d["rejection_reason"] == "personal" and d["rejected_by"]
        assert admin.post(f"{BT}/{r['id']}/approve").status_code == 400
        assert admin.post(f"{BT}/{r['id']}/reject", json={"reason": "x"}).status_code == 400

    def test_audit_history(self, admin, meta):
        r = ingest([_txn()]).json()["results"][0]
        admin.put(f"{BT}/{r['id']}", json={"type": "Expense", "account": meta["account"], "project_id": meta["project"],
                                          "amount": r["amount"], "date": r["transaction_date"], "notes": "audit"})
        admin.post(f"{BT}/{r['id']}/approve")
        actions = [a["action"] for a in admin.get(f"{BT}/{r['id']}/audit").json()]
        for needed in ("ingested", "edited", "approved", "finance_transaction_created"):
            assert needed in actions, actions
        assert any(a in actions for a in ("classified", "ai_suggested", "historical_mapping_selected"))
        assert actions.index("ingested") < actions.index("approved")

    def test_ingestion_history_and_stats(self, admin):
        ingest([_txn()])
        h = admin.get(f"{BT}/ingestion-history").json()
        assert h and h[0]["channel"] == "ingest_api" and h[0]["count"] == 1
        s = admin.get(f"{BT}/stats").json()
        assert s["pending"] >= 1 and "all" in s

    def test_list_filters(self, admin):
        ingest([_txn(bank_name="FilterBank", direction="credit", amount=42424)])
        rows = admin.get(BT, params={"bank": "FilterBank", "direction": "credit", "min_amount": 42000, "max_amount": 43000}).json()
        assert rows and all(r["direction"] == "credit" and r["bank_name"] == "FilterBank" for r in rows)
        assert admin.get(BT, params={"status": "duplicate"}).status_code == 200


class TestLearning:
    def test_mapping_rule_learned_and_used(self, admin, meta):
        tag = "LEARNCO" + _alpha_tag()
        other_proj = meta["raw"]["project_ids"][-1]["code"]
        ids = []
        for _ in range(3):
            r = ingest([_txn(narration=f"{tag} PAYMENT 12345678", amount=2500)]).json()["results"][0]
            admin.put(f"{BT}/{r['id']}", json={"type": "Cost", "account": meta["account"], "project_id": other_proj,
                                              "amount": 2500, "date": r["transaction_date"], "notes": "learn"})
            assert admin.post(f"{BT}/{r['id']}/approve").status_code == 200
            ids.append(r["id"])
        rules = [x for x in admin.get(f"{BT}/rules").json() if x["pattern"].startswith(tag)]
        assert rules, "rule not learned"
        rule = rules[0]
        assert rule["uses"] == 3 and rule["corrections"] == 0 and rule["confidence"] >= 70
        assert rule["mapping"] == {"type": "Cost", "account": meta["account"], "project_id": other_proj}
        # a new incoming txn now uses the learned rule (Layer 1)
        r = ingest([_txn(narration=f"{tag} PAYMENT 87654321", amount=2600)]).json()["results"][0]
        assert r["suggestion"]["source"] == "mapping_rule"
        assert r["suggestion"]["project_id"] == other_proj
        assert any("Learned mapping rule" in x for x in r["suggestion"]["reasons"])

    def test_single_correction_does_not_override(self, admin, meta):
        tag = "STABLECO" + _alpha_tag()
        other_proj = meta["raw"]["project_ids"][-1]["code"]
        for _ in range(3):
            r = ingest([_txn(narration=f"{tag} FEE 111", amount=100)]).json()["results"][0]
            admin.put(f"{BT}/{r['id']}", json={"type": "Expense", "account": meta["account"], "project_id": meta["project"],
                                              "amount": 100, "date": r["transaction_date"]})
            admin.post(f"{BT}/{r['id']}/approve")
        r = ingest([_txn(narration=f"{tag} FEE 222", amount=100)]).json()["results"][0]
        admin.put(f"{BT}/{r['id']}", json={"type": "Cost", "account": meta["account"], "project_id": other_proj,
                                          "amount": 100, "date": r["transaction_date"]})
        admin.post(f"{BT}/{r['id']}/approve")
        rule = [x for x in admin.get(f"{BT}/rules").json() if x["pattern"].startswith(tag)][0]
        assert rule["mapping"]["type"] == "Expense" and rule["corrections"] == 1 and rule["uses"] == 3

    def test_rule_admin_crud_and_disable(self, admin, meta):
        tag = "RULECRUD" + _alpha_tag()
        for _ in range(2):
            r = ingest([_txn(narration=f"{tag} X 1", amount=50)]).json()["results"][0]
            admin.put(f"{BT}/{r['id']}", json={"type": "Expense", "account": meta["account"], "project_id": meta["project"],
                                              "amount": 50, "date": r["transaction_date"]})
            admin.post(f"{BT}/{r['id']}/approve")
        rule = [x for x in admin.get(f"{BT}/rules").json() if x["pattern"].startswith(tag)][0]
        u = admin.put(f"{BT}/rules/{rule['id']}", json={"type": "Cost"})
        assert u.status_code == 200 and u.json()["mapping"]["type"] == "Cost"
        assert admin.put(f"{BT}/rules/{rule['id']}", json={"type": "Bogus"}).status_code == 422
        d = admin.put(f"{BT}/rules/{rule['id']}", json={"enabled": False}).json()
        assert d["enabled"] is False
        r = ingest([_txn(narration=f"{tag} X 2", amount=50)]).json()["results"][0]
        assert r["suggestion"]["source"] != "mapping_rule"
        assert admin.delete(f"{BT}/rules/{rule['id']}").status_code == 200
        assert admin.delete(f"{BT}/rules/{rule['id']}").status_code == 404


class TestAccess:
    def test_anonymous_blocked(self):
        assert requests.get(BT).status_code == 401
        assert requests.get(f"{BT}/rules").status_code == 401
        assert requests.post(f"{BT}/manual", json=_txn()).status_code == 401

    def test_non_admin_blocked(self, member):
        assert member.get(BT).status_code == 403
        assert member.get(f"{BT}/stats").status_code == 403
        assert member.get(f"{BT}/rules").status_code == 403
        assert member.post(f"{BT}/manual", json=_txn()).status_code == 403
        r = ingest([_txn()]).json()["results"][0]
        assert member.post(f"{BT}/{r['id']}/approve").status_code == 403
        assert member.post(f"{BT}/{r['id']}/reject", json={"reason": ""}).status_code == 403

    def test_manual_ingest_same_pipeline(self, admin):
        t = _txn(source="csv")
        r = admin.post(f"{BT}/manual", json=t)
        assert r.status_code == 200 and r.json()["source"] == "manual" and r.json()["status"] == "pending"
        assert "suggestion" in r.json() and r.json()["fingerprint"]
        dup = admin.post(f"{BT}/manual", json=t).json()
        assert dup["status"] == "duplicate"
        h = admin.get(f"{BT}/ingestion-history").json()
        assert any(x["channel"] == "manual" for x in h)

    def test_existing_transaction_create_still_works(self, admin, meta):
        r = admin.post(f"{API}/transactions", json={"date": "2026-02-02", "type": "Revenue", "account": meta["account"],
                                                    "amount": 10, "project_id": meta["project"], "notes": "regress"})
        assert r.status_code == 200 and r.json()["id"]
        admin.delete(f"{API}/transactions/{r.json()['id']}")
