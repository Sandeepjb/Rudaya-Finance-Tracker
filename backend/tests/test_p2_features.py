"""Tests for Project Drilldown, Copy Last Year Forecast, and Backup P&L Impact Dry-run."""
import io
import os
import re
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or frontend_env["REACT_APP_BACKEND_URL"]).rstrip("/")
API = f"{BASE_URL}/api"


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


class TestProjectDrilldown:
    def test_requires_auth(self):
        assert requests.get(f"{API}/reports/project-detail/FRD_GJ_0002").status_code == 401

    def test_returns_scoped_data_shape(self, admin):
        # Pick a project we know exists from the seed data.
        pnl = admin.get(f"{API}/reports/project-pnl").json()
        assert len(pnl) > 0
        target = pnl[0]["project_id"]
        r = admin.get(f"{API}/reports/project-detail/{target}", params={"year": 2026})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["project_id"] == target
        assert d["year"] == 2026
        # Top-level shape
        for k in ("totals", "rows", "total_forecast", "total_actual", "transactions", "quotations", "transaction_count"):
            assert k in d
        # 12 monthly rows
        assert len(d["rows"]) == 12
        # All transactions returned MUST match the project scope
        assert all(t["project_id"] == target for t in d["transactions"])
        # Totals must reconcile with the P&L endpoint (same project, all years).
        summary = next((p for p in pnl if p["project_id"] == target), None)
        assert summary is not None
        assert abs(d["totals"]["revenue"] - summary["revenue"]) < 1
        assert abs(d["totals"]["cost"] - summary["cost"]) < 1
        assert abs(d["totals"]["expense"] - summary["expense"]) < 1


class TestCopyLastYear:
    _tag = f"CLY_TEST_{uuid.uuid4().hex[:6]}"

    def _cleanup(self, admin):
        for row in admin.get(f"{API}/sales-forecast", params={"year": 2100}).json():
            if row.get("notes", "").startswith(self._tag):
                admin.delete(f"{API}/sales-forecast/{row['id']}")
        for row in admin.get(f"{API}/sales-forecast", params={"year": 2101}).json():
            if row.get("notes", "").startswith(self._tag):
                admin.delete(f"{API}/sales-forecast/{row['id']}")

    def test_copies_all_source_rows(self, admin):
        self._cleanup(admin)
        # Seed 3 source rows in a future "last" year 2100
        seeds = [
            {"year": 2100, "month": 3, "type": "Revenue", "project_id": "", "amount": 100000, "notes": f"{self._tag}-1"},
            {"year": 2100, "month": 4, "type": "Cost",    "project_id": "", "amount": 30000,  "notes": f"{self._tag}-2"},
            {"year": 2100, "month": 5, "type": "Expense", "project_id": "", "amount": 5000,   "notes": f"{self._tag}-3"},
        ]
        for s in seeds:
            r = admin.post(f"{API}/sales-forecast", json=s)
            assert r.status_code in (200, 201), r.text

        try:
            # Copy 2100 → 2101
            r = admin.post(f"{API}/sales-forecast/copy-last-year",
                           json={"target_year": 2101, "include_quotations": False, "overwrite": False})
            assert r.status_code == 200, r.text
            d = r.json()
            assert d["target_year"] == 2101
            assert d["source_year"] == 2100
            assert d["sales_forecast"]["copied"] >= 3
            assert d["quotations"] is None

            # 2101 should now contain the copied rows
            target_rows = admin.get(f"{API}/sales-forecast", params={"year": 2101}).json()
            our_copies = [x for x in target_rows if x.get("notes", "").startswith(self._tag)]
            assert len(our_copies) == 3
            # Every copied row must retain type/month/amount but land in target year
            for tag_row in our_copies:
                src = next((s for s in seeds if s["notes"] == tag_row["notes"]), None)
                assert src is not None
                assert tag_row["year"] == 2101
                assert tag_row["month"] == src["month"]
                assert tag_row["type"] == src["type"]
                assert tag_row["amount"] == src["amount"]

            # Idempotent: a second copy should skip all 3 because of the dedup key.
            r2 = admin.post(f"{API}/sales-forecast/copy-last-year",
                            json={"target_year": 2101, "include_quotations": False, "overwrite": False})
            d2 = r2.json()
            assert d2["sales_forecast"]["skipped"] >= 3

            # Overwrite=True should insert them again (append), so the tag row count doubles for ours.
            r3 = admin.post(f"{API}/sales-forecast/copy-last-year",
                            json={"target_year": 2101, "include_quotations": False, "overwrite": True})
            d3 = r3.json()
            assert d3["sales_forecast"]["copied"] >= 3
        finally:
            self._cleanup(admin)

    def test_copy_with_quotations(self, admin):
        # Seed a source quotation in year 2100 with a unique number
        base_num = f"CLY-Q-{uuid.uuid4().hex[:6]}"
        q_payload = {
            "quotation_number": base_num,
            "client_name": "CLY Test Client",
            "project_id": "",
            "quote_date": "2100-06-15",
            "expected_year": 2100,
            "expected_month": 6,
            "status": "draft",
            "notes": f"{self._tag}-q",
            "lines": [{"description": "Test line", "type": "Revenue", "amount": 500000}],
        }
        r = admin.post(f"{API}/quotations", json=q_payload)
        assert r.status_code in (200, 201), r.text
        qid = r.json()["id"]
        try:
            resp = admin.post(f"{API}/sales-forecast/copy-last-year",
                              json={"target_year": 2101, "include_quotations": True, "overwrite": False})
            assert resp.status_code == 200, resp.text
            d = resp.json()
            assert d["quotations"] is not None
            assert d["quotations"]["copied"] >= 1

            # The copied quotation should exist in 2101 with the -COPY2101 suffix
            all_q = admin.get(f"{API}/quotations", params={"year": 2101}).json()
            copy = next((q for q in all_q if q["quotation_number"] == f"{base_num}-COPY2101"), None)
            assert copy is not None
            assert copy["status"] == "draft"
            assert copy["expected_year"] == 2101
            assert copy["expected_month"] == 6
            admin.delete(f"{API}/quotations/{copy['id']}")

            # Second run should skip (duplicate number)
            resp2 = admin.post(f"{API}/sales-forecast/copy-last-year",
                               json={"target_year": 2101, "include_quotations": True, "overwrite": False})
            d2 = resp2.json()
            # After we deleted the copy above, second run should recopy it. Then the third should skip.
            resp3 = admin.post(f"{API}/sales-forecast/copy-last-year",
                               json={"target_year": 2101, "include_quotations": True, "overwrite": False})
            assert resp3.json()["quotations"]["skipped"] >= 1
            # Cleanup all copies
            for q in admin.get(f"{API}/quotations", params={"year": 2101}).json():
                if q["quotation_number"].startswith(base_num):
                    admin.delete(f"{API}/quotations/{q['id']}")
        finally:
            admin.delete(f"{API}/quotations/{qid}")
            self._cleanup(admin)


class TestBackupDryRun:
    def test_admin_only(self):
        assert requests.post(f"{API}/migrations/backups/whatever/dry-run",
                             data={"mode": "merge"}).status_code == 401

    def test_invalid_mode(self, admin):
        r = admin.post(f"{API}/migrations/backups/whatever/dry-run", data={"mode": "invalid"})
        assert r.status_code == 400

    def test_unknown_stamp_404(self, admin):
        r = admin.post(f"{API}/migrations/backups/does-not-exist/dry-run", data={"mode": "merge"})
        assert r.status_code == 404

    def test_merge_vs_full_shape(self, admin, txn_state_lock):
        """Create a backup via replace-import, then dry-run merge and full to verify shapes and semantics."""
        from motor.motor_asyncio import AsyncIOMotorClient
        import asyncio

        env = dotenv_values("/app/backend/.env")
        cl = AsyncIOMotorClient(env["MONGO_URL"])
        d = cl[env["DB_NAME"]]

        async def snapshot():
            return await d.transactions.find({}).to_list(None)

        async def wipe_and_restore(docs):
            await d.transactions.delete_many({})
            if docs:
                await d.transactions.insert_many(docs)

        seed = asyncio.get_event_loop().run_until_complete(snapshot())
        try:
            # Trigger a replace_existing to create a fresh backup snapshot we control.
            csv = "date,type,account,amount,project_id,notes\n2099-04-15,Revenue,DryImpact,42,DRY_IMPACT,dry-impact-marker\n"
            r = admin.post(f"{API}/migrations/import",
                           files={"file": ("s.csv", io.BytesIO(csv.encode()), "text/csv")},
                           data={"mode": "replace_existing"})
            assert r.status_code == 200, r.text
            stamp = r.json()["backup"]["stamp"]

            # merge mode: `after` should be current DB + snapshot rows (not present in DB now)
            rm = admin.post(f"{API}/migrations/backups/{stamp}/dry-run", data={"mode": "merge"})
            assert rm.status_code == 200
            dm = rm.json()
            assert dm["mode"] == "merge"
            assert dm["would_insert"] > 0

            # full mode: `after` totals equal the snapshot rows exactly (no legacy).
            rf = admin.post(f"{API}/migrations/backups/{stamp}/dry-run", data={"mode": "full"})
            assert rf.status_code == 200
            df = rf.json()
            assert df["mode"] == "full"
            assert df["would_insert"] > 0

            # For any year in the response, full's `totals_after` != merge's `totals_after` in general.
            any_year = next(iter(df["years"].keys()))
            assert "months" in df["years"][any_year]
            assert len(df["years"][any_year]["months"]) == 12
            # Full-mode `before` may still be non-zero (current DB), but `after` should not include legacy rows;
            # after-Net therefore equals contribution-Net alone. Spot-check the identity delta = after - before.
            m = df["years"][any_year]["months"][0]
            for t in ("Revenue", "Cost", "Expense", "net"):
                assert abs((m["after"][t] - m["before"][t]) - m["delta"][t]) < 0.01
        finally:
            asyncio.get_event_loop().run_until_complete(wipe_and_restore(seed))
            cl.close()
