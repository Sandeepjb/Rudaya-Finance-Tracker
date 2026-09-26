"""Backend tests for the Admin-only CSV Import (Data Migration) feature."""
import os
import re
import io
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def creds():
    p = Path("/app/memory/test_credentials.md")
    if not p.exists():
        pytest.skip("missing test_credentials.md")
    c = p.read_text()
    e = re.search(r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?email(?:\*\*)?\s*:\s*`?([^`\s]+)", c)
    pw = re.search(r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?password(?:\*\*)?\s*:\s*`?([^`\s]+)", c)
    if not e or not pw:
        pytest.skip("creds not parseable")
    return {"email": e.group(1), "password": pw.group(1)}


@pytest.fixture(scope="module")
def admin(creds):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json=creds)
    if r.status_code != 200:
        pytest.fail(f"admin login failed: {r.status_code} {r.text[:200]}")
    return s


def _csv_bytes(rows: list, header=True) -> bytes:
    lines = []
    if header:
        lines.append("date,type,account,amount,project_id,notes")
    for row in rows:
        lines.append(",".join(str(x) for x in row))
    return ("\n".join(lines) + "\n").encode("utf-8")


def _file(csv_bytes: bytes, name="test.csv"):
    return {"file": (name, io.BytesIO(csv_bytes), "text/csv")}


class TestMigrationPreview:
    def test_admin_required(self):
        # unauthenticated: 401
        r = requests.post(f"{API}/migrations/preview", files=_file(_csv_bytes([["2026-04-15", "Revenue", "A", 100, "P1", "n"]])))
        assert r.status_code == 401

    def test_reject_missing_headers(self, admin):
        bad = b"date,type,account\n2026-04-15,Revenue,A\n"
        r = admin.post(f"{API}/migrations/preview", files={"file": ("b.csv", io.BytesIO(bad), "text/csv")})
        assert r.status_code == 400
        assert "column" in r.json()["detail"].lower()

    def test_validation_and_multiple_date_formats(self, admin):
        rows = [
            ["2026-04-15", "Revenue", "SalesA", 1000, "PRJ-TEST", "iso"],       # valid iso
            ["15/04/2026", "Cost", "MatA", 500, "PRJ-TEST", "dmy slash"],       # valid dmy slash
            ["15-04-2026", "Expense", "TravA", 250, "PRJ-TEST", "dmy dash"],    # valid dmy dash
            ["not-a-date", "Revenue", "X", 100, "PRJ-TEST", "bad date"],        # invalid
            ["2026-04-15", "Rubbish", "X", 100, "PRJ-TEST", "bad type"],        # invalid type
            ["2026-04-15", "Revenue", "X", -50, "PRJ-TEST", "neg amount"],      # invalid amount
            ["2026-04-15", "Revenue", "X", "abc", "PRJ-TEST", "nan amount"],    # invalid amount
            ["2026-04-15", "Revenue", "", 100, "PRJ-TEST", "no account"],       # invalid account
            ["2026-04-15", "Revenue", "X", 100, "", "no project"],              # invalid project
        ]
        r = admin.post(f"{API}/migrations/preview", files=_file(_csv_bytes(rows)))
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["total_rows"] == 9
        assert d["valid_rows"] == 3
        assert d["invalid_rows"] == 6
        # per-row status
        assert d["rows"][0]["valid"] and d["rows"][0]["parsed"]["date"] == "2026-04-15"
        assert d["rows"][1]["valid"] and d["rows"][1]["parsed"]["date"] == "2026-04-15"
        assert d["rows"][2]["valid"] and d["rows"][2]["parsed"]["date"] == "2026-04-15"
        assert not d["rows"][3]["valid"]
        assert not d["rows"][5]["valid"]
        # by_type totals
        assert d["by_type"]["Revenue"]["count"] == 1
        assert d["by_type"]["Cost"]["count"] == 1
        assert d["by_type"]["Expense"]["count"] == 1


class TestMigrationImport:
    _fp = "MIG_TEST_"  # marker in project_id to isolate rows for cleanup

    @classmethod
    def _cleanup(cls, admin):
        # remove all test rows by fetching + delete each
        rows = admin.get(f"{API}/transactions").json()
        for t in rows:
            if cls._fp in (t.get("project_id") or "") or cls._fp in (t.get("account") or ""):
                admin.delete(f"{API}/transactions/{t['id']}")

    def test_skip_duplicates_flow(self, admin):
        self._cleanup(admin)
        rows = [
            ["2026-04-15", "Revenue", f"{self._fp}Sales", 1000, f"{self._fp}P1", "row1"],
            ["2026-04-16", "Cost",    f"{self._fp}Mat",   500,  f"{self._fp}P1", "row2"],
        ]
        r = admin.post(f"{API}/migrations/import",
                       files=_file(_csv_bytes(rows)),
                       data={"mode": "skip_duplicates"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["inserted"] == 2
        assert d["skipped_duplicate"] == 0
        assert d["backup"] is None

        # re-import same rows → should skip both as duplicates
        r2 = admin.post(f"{API}/migrations/import",
                        files=_file(_csv_bytes(rows)),
                        data={"mode": "skip_duplicates"})
        d2 = r2.json()
        assert r2.status_code == 200
        assert d2["inserted"] == 0
        assert d2["skipped_duplicate"] == 2

        # add a new row + repeat → 1 new, 2 dup
        rows_ext = rows + [["2026-04-17", "Expense", f"{self._fp}Trav", 250, f"{self._fp}P1", "row3"]]
        r3 = admin.post(f"{API}/migrations/import",
                        files=_file(_csv_bytes(rows_ext)),
                        data={"mode": "skip_duplicates"})
        d3 = r3.json()
        assert d3["inserted"] == 1
        assert d3["skipped_duplicate"] == 2
        self._cleanup(admin)

    def test_replace_backs_up_then_wipes(self, admin, txn_state_lock):
        # Use direct MongoDB access for an exact snapshot/restore so downstream tests
        # (which assert on hard-coded seed totals) still pass after this destructive test.
        from motor.motor_asyncio import AsyncIOMotorClient
        import asyncio
        env = dotenv_values("/app/backend/.env")
        cl = AsyncIOMotorClient(env["MONGO_URL"])
        d = cl[env["DB_NAME"]]

        async def snapshot_all():
            return await d.transactions.find({}).to_list(None)

        async def wipe_and_restore(docs):
            await d.transactions.delete_many({})
            if docs:
                await d.transactions.insert_many(docs)

        self._cleanup(admin)
        snapshot = asyncio.get_event_loop().run_until_complete(snapshot_all())
        pre_count = len(snapshot)
        assert pre_count > 0, "expected seeded transactions to exist"

        rows = [["2026-04-15", "Revenue", f"{self._fp}SalesR", 1000, f"{self._fp}P1", "fresh"]]
        r = admin.post(f"{API}/migrations/import",
                       files=_file(_csv_bytes(rows)),
                       data={"mode": "replace_existing"})
        assert r.status_code == 200, r.text
        d_res = r.json()
        assert d_res["mode"] == "replace_existing"
        assert d_res["inserted"] == 1
        assert d_res["backup"] is not None
        assert d_res["backup"]["count"] == pre_count

        # transactions now should equal just the imported row
        after = admin.get(f"{API}/transactions").json()
        assert len(after) == 1
        assert after[0]["notes"] == "fresh"

        # history should record this entry with a backup_stamp
        hist = admin.get(f"{API}/migrations/history").json()
        assert any(h["backup_stamp"] == d_res["backup"]["stamp"] and h["mode"] == "replace_existing" for h in hist)

        # Restore the exact snapshot (with _id + source) so downstream tests see the seed data intact.
        asyncio.get_event_loop().run_until_complete(wipe_and_restore(snapshot))
        cl.close()
        restored = len(admin.get(f"{API}/transactions").json())
        assert restored == pre_count, f"restore failed: {restored}/{pre_count}"

    def test_invalid_rows_are_ignored(self, admin):
        rows = [
            ["2026-04-15", "Revenue", f"{self._fp}A", 1000, f"{self._fp}P1", "ok"],
            ["bad", "Revenue", "X", 100, "P1", "bad date"],
        ]
        r = admin.post(f"{API}/migrations/import",
                       files=_file(_csv_bytes(rows)),
                       data={"mode": "skip_duplicates"})
        assert r.status_code == 200
        d = r.json()
        assert d["inserted"] == 1
        assert d["invalid_rows"] == 1
        self._cleanup(admin)

    def test_import_history_endpoint(self, admin):
        r = admin.get(f"{API}/migrations/history")
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)
        if rows:
            assert "filename" in rows[0]
            assert "mode" in rows[0]
            assert "admin_email" in rows[0]
