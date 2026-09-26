"""Tests for the P&L Dry-run + Backup Restore endpoints (Admin-only)."""
import io
import os
import re
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


def _csv(rows: list) -> bytes:
    header = "date,type,account,amount,project_id,notes\n"
    body = "\n".join(",".join(str(x) for x in r) for r in rows) + "\n"
    return (header + body).encode("utf-8")


def _file(b: bytes, name="dry.csv"):
    return {"file": (name, io.BytesIO(b), "text/csv")}


class TestDryRun:
    def test_admin_only(self):
        r = requests.post(f"{API}/migrations/dry-run",
                          files=_file(_csv([["2026-04-15", "Revenue", "A", 100, "P1", "n"]])),
                          data={"mode": "skip_duplicates"})
        assert r.status_code == 401

    def test_skip_mode_shape(self, admin):
        rows = [
            ["2026-04-15", "Revenue", "DRYSalesA", 250000, "DRYPRJ", "row1"],
            ["2026-05-20", "Cost",    "DRYMatA",   50000,  "DRYPRJ", "row2"],
            ["2026-07-10", "Expense", "DRYTravA",  3200,   "DRYPRJ", "row3"],
        ]
        r = admin.post(f"{API}/migrations/dry-run",
                       files=_file(_csv(rows)),
                       data={"mode": "skip_duplicates"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["mode"] == "skip_duplicates"
        assert d["would_insert"] == 3
        assert "2026" in d["years"]
        year = d["years"]["2026"]
        assert len(year["months"]) == 12
        # April = index 3 → month 4. Revenue delta must equal 250000, others 0.
        apr = year["months"][3]
        assert apr["month"] == 4
        assert apr["delta"]["Revenue"] == 250000
        assert apr["delta"]["Cost"] == 0
        assert abs(apr["delta"]["net"] - 250000) < 0.01
        # Totals: totals_after - totals_before == totals_delta
        for t in ["Revenue", "Cost", "Expense", "net"]:
            assert abs(year["totals_after"][t] - year["totals_before"][t] - year["totals_delta"][t]) < 0.01

    def test_replace_mode_zeros_before(self, admin):
        """In replace_existing mode, `after` should be purely the imported rows (no legacy data)."""
        rows = [["2026-04-15", "Revenue", "DRYReplace", 100, "DRYPRJ", "only-row"]]
        r = admin.post(f"{API}/migrations/dry-run",
                       files=_file(_csv(rows)),
                       data={"mode": "replace_existing"})
        d = r.json()
        assert d["mode"] == "replace_existing"
        assert d["would_insert"] == 1
        y = d["years"]["2026"]
        # totals_after must equal exactly the contribution of the one row
        assert y["totals_after"]["Revenue"] == 100
        assert y["totals_after"]["Cost"] == 0
        assert y["totals_after"]["Expense"] == 0
        assert y["totals_after"]["net"] == 100
        # delta = after - before (before is real seed, so delta is 100 - seed_revenue)
        assert y["totals_delta"]["Revenue"] == y["totals_after"]["Revenue"] - y["totals_before"]["Revenue"]


class TestBackupRestore:
    """These tests exercise the restore endpoints against the destructive replace flow.
    They must not leak seed data corruption to sibling tests, so we take a Motor-level
    snapshot and restore it directly at the end."""

    _fp = "BKR_TEST_"

    def _cleanup_test_rows(self, admin):
        for t in admin.get(f"{API}/transactions").json():
            if self._fp in (t.get("project_id") or "") or self._fp in (t.get("account") or ""):
                admin.delete(f"{API}/transactions/{t['id']}")

    def test_admin_only(self):
        assert requests.get(f"{API}/migrations/backups").status_code == 401
        assert requests.get(f"{API}/migrations/backups/whatever").status_code == 401
        assert requests.post(f"{API}/migrations/backups/whatever/restore",
                             data={"mode": "merge"}).status_code == 401

    def test_backup_list_and_restore_flow(self, admin, txn_state_lock):
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

        self._cleanup_test_rows(admin)
        seed_snapshot = asyncio.get_event_loop().run_until_complete(snapshot())
        seed_count = len(seed_snapshot)
        assert seed_count > 0

        try:
            # Step 1 — Trigger a `replace_existing` import → creates a backup snapshot.
            rows = [["2026-04-15", "Revenue", f"{self._fp}Rev", 999, f"{self._fp}P1", "replace-row"]]
            r = admin.post(f"{API}/migrations/import",
                           files={"file": ("s.csv", io.BytesIO(_csv(rows)), "text/csv")},
                           data={"mode": "replace_existing"})
            assert r.status_code == 200, r.text
            stamp = r.json()["backup"]["stamp"]
            server_backup_count = r.json()["backup"]["count"]  # authoritative — what the server actually backed up
            assert stamp
            assert server_backup_count > 0

            # Step 2 — List backups: should include our new stamp with count == server_backup_count.
            lst = admin.get(f"{API}/migrations/backups").json()
            found = [b for b in lst if b["stamp"] == stamp]
            assert len(found) == 1
            assert found[0]["count"] == server_backup_count
            assert "totals" in found[0]

            # Step 3 — Preview snapshot: get first N rows.
            prev = admin.get(f"{API}/migrations/backups/{stamp}").json()
            assert prev["stamp"] == stamp
            assert prev["count"] == server_backup_count
            assert len(prev["rows"]) >= 1

            # Step 4 — Merge restore: current DB has 1 row (the replace-row). Merge should insert all
            # rows from the snapshot whose fingerprint isn't the replace-row.
            r_merge = admin.post(f"{API}/migrations/backups/{stamp}/restore",
                                 data={"mode": "merge"})
            assert r_merge.status_code == 200, r_merge.text
            dm = r_merge.json()
            assert dm["mode"] == "merge"
            # replace-row fingerprint is unique to us — none of the snapshot rows share it.
            assert dm["inserted"] == server_backup_count
            after_merge_count = len(admin.get(f"{API}/transactions").json())
            assert after_merge_count >= server_backup_count  # ≥ because CRUD test may add a temp row concurrently

            # Step 5 — Full restore: auto-back-up current state then insert snapshot fresh.
            r_full = admin.post(f"{API}/migrations/backups/{stamp}/restore",
                                data={"mode": "full"})
            assert r_full.status_code == 200, r_full.text
            df = r_full.json()
            assert df["mode"] == "full"
            assert df["inserted"] == server_backup_count
            assert df["auto_backup"] is not None
            assert df["auto_backup"]["count"] >= server_backup_count

            # Step 6 — Merge is idempotent: repeating should skip everything.
            r_merge2 = admin.post(f"{API}/migrations/backups/{stamp}/restore",
                                  data={"mode": "merge"})
            dm2 = r_merge2.json()
            assert dm2["inserted"] == 0
            assert dm2["skipped_duplicate"] == server_backup_count

            # Step 7 — Restore actions land in import_history with a `restore_*` mode.
            hist = admin.get(f"{API}/migrations/history", params={"limit": 200}).json()
            assert any(h["mode"].startswith("restore_") and h.get("restored_from") == stamp for h in hist)
        finally:
            # ALWAYS restore the exact seed snapshot so downstream tests see the seed data intact,
            # even if an assertion above failed.
            asyncio.get_event_loop().run_until_complete(wipe_and_restore(seed_snapshot))
            cl.close()

    def test_unknown_snapshot_404(self, admin):
        r = admin.get(f"{API}/migrations/backups/does-not-exist")
        assert r.status_code == 404
        r2 = admin.post(f"{API}/migrations/backups/does-not-exist/restore", data={"mode": "merge"})
        assert r2.status_code == 404

    def test_invalid_mode(self, admin):
        r = admin.post(f"{API}/migrations/backups/whatever/restore", data={"mode": "gibberish"})
        assert r.status_code == 400
