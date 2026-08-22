"""Regression backend tests for Rudaya Powers Finance Tracker (cookie auth)."""
import os
import re
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


@pytest.fixture(scope="session")
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


@pytest.fixture(scope="session")
def client(creds):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json=creds)
    if r.status_code != 200:
        pytest.fail(f"login failed {r.status_code}: {r.text[:300]}")
    return s


# --- Auth module ---
class TestAuth:
    def test_login_sets_httponly_cookie(self, creds):
        s = requests.Session()
        r = s.post(f"{API}/auth/login", json=creds)
        assert r.status_code == 200
        data = r.json()
        assert data["user"]["email"] == creds["email"]
        assert data["user"]["role"] == "admin"
        raw = r.headers.get("set-cookie", "")
        assert "access_token=" in raw
        assert "HttpOnly" in raw
        assert "Secure" in raw
        assert "samesite=none" in raw.lower()
        assert "access_token" in s.cookies

    def test_cors_allows_credentials_with_explicit_origin(self):
        # NOTE: the preview edge proxy rewrites CORS headers to `*` on the public URL,
        # so we assert the app-level CORS config directly on the internal port.
        r = requests.get("http://localhost:8001/api/auth/me", headers={"Origin": BASE_URL})
        assert r.headers.get("access-control-allow-credentials") == "true", dict(r.headers)
        assert r.headers.get("access-control-allow-origin") == BASE_URL, dict(r.headers)

    def test_me_with_cookie_only(self, client):
        r = client.get(f"{API}/auth/me")
        assert r.status_code == 200
        assert "@" in r.json()["user"]["email"]

    def test_me_unauthenticated(self):
        r = requests.get(f"{API}/auth/me")
        assert r.status_code == 401

    def test_bad_password(self, creds):
        r = requests.post(f"{API}/auth/login", json={"email": creds["email"], "password": "WrongPass!1"})
        assert r.status_code == 401

    def test_bcrypt_hash_format(self):
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        env = dotenv_values("/app/backend/.env")

        async def _get():
            cl = AsyncIOMotorClient(env["MONGO_URL"])
            u = await cl[env["DB_NAME"]].users.find_one({"email": env["ADMIN_EMAIL"].lower()})
            cl.close()
            return u

        u = asyncio.get_event_loop().run_until_complete(_get())
        assert u is not None  # noqa: E711 — PEP 8: use `is` for None comparisons
        assert u["password_hash"].startswith("$2b$")

    def test_brute_force_lockout(self, creds):
        """Playbook expects lockout after 5 failed attempts."""
        s = requests.Session()
        codes = []
        for _ in range(6):
            codes.append(s.post(f"{API}/auth/login", json={"email": creds["email"], "password": "Bad!123"}).status_code)
        assert 423 in codes or 429 in codes, f"no lockout, codes={codes}"

    def test_logout_clears_cookie(self, creds):
        s = requests.Session()
        s.post(f"{API}/auth/login", json=creds)
        r = s.post(f"{API}/auth/logout")
        assert r.status_code == 200
        assert not s.cookies.get("access_token")
        assert s.get(f"{API}/auth/me").status_code == 401


# --- Reports module ---
class TestReports:
    def test_summary_totals(self, client):
        r = client.get(f"{API}/reports/summary")
        assert r.status_code == 200
        d = r.json()
        assert round(d["revenue"]) == 4621778
        assert round(d["cost"]) == 3543756
        assert round(d["expense"]) == 329421
        assert round(d["gross_profit"]) == 1078022
        assert round(d["net_profit"]) == 748602

    def test_monthly(self, client):
        r = client.get(f"{API}/reports/monthly")
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list) and len(rows) >= 6

    def test_project_pnl(self, client):
        r = client.get(f"{API}/reports/project-pnl")
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) > 0
        assert "project_id" in rows[0]
        assert all("_id" not in x for x in rows)

    def test_forecast_vs_actual_12_rows(self, client):
        r = client.get(f"{API}/reports/forecast-vs-actual", params={"year": 2026})
        assert r.status_code == 200
        d = r.json()
        rows = d["rows"]
        assert len(rows) == 12
        assert d["year"] == 2026
        assert "total_forecast" in d and "total_actual" in d
        for row in rows:
            assert "month" in row and "forecast" in row and "actual" in row

    def test_reports_require_auth(self):
        for ep in ["summary", "monthly", "project-pnl", "forecast-vs-actual"]:
            assert requests.get(f"{API}/reports/{ep}").status_code == 401


# --- Transactions CRUD ---
class TestTransactions:
    def test_list_and_no_objectid(self, client):
        r = client.get(f"{API}/transactions")
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) >= 100
        assert all("_id" not in t for t in rows)
        assert "id" in rows[0]

    def test_filter_type_revenue(self, client):
        r = client.get(f"{API}/transactions", params={"type": "Revenue"})
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 9
        assert all(t["type"] == "Revenue" for t in rows)

    def test_date_range_filter(self, client):
        r = client.get(f"{API}/transactions", params={"start_date": "2026-04-01", "end_date": "2026-04-30"})
        assert r.status_code == 200
        for t in r.json():
            assert t["date"][:7] == "2026-04"

    def test_crud_lifecycle(self, client):
        payload = {"date": "2026-07-15", "type": "Revenue", "account": "TEST_Sales",
                   "amount": 12345.0, "project_id": "TEST_PRJ", "notes": "TEST_create"}
        c = client.post(f"{API}/transactions", json=payload)
        assert c.status_code in (200, 201), c.text
        tid = c.json()["id"]
        got = [t for t in client.get(f"{API}/transactions").json() if t["id"] == tid]
        assert len(got) == 1
        assert got[0]["amount"] == 12345.0
        assert got[0]["notes"] == "TEST_create"

        u = client.put(f"{API}/transactions/{tid}", json={**payload, "amount": 999.0, "notes": "TEST_upd"})
        assert u.status_code == 200
        got = [t for t in client.get(f"{API}/transactions").json() if t["id"] == tid][0]
        assert got["amount"] == 999.0 and got["notes"] == "TEST_upd"

        d = client.delete(f"{API}/transactions/{tid}")
        assert d.status_code in (200, 204)
        assert not [t for t in client.get(f"{API}/transactions").json() if t["id"] == tid]

    def test_invalid_id_404(self, client):
        r = client.delete(f"{API}/transactions/64b7f2c9a1b2c3d4e5f60718")
        assert r.status_code == 404

    def test_transactions_require_auth(self):
        assert requests.get(f"{API}/transactions").status_code == 401


# --- Forecast consolidation (sales_forecast overrides legacy /forecast) ---
class TestForecast:
    def test_legacy_upsert_is_overridden_by_sales_forecast(self, client):
        """Legacy POST /forecast still works but sales_forecast entries take precedence in the consolidation."""
        r = client.post(f"{API}/forecast", json={"year": 2026, "month": 7, "amount": 3500000, "notes": "TEST_fc"})
        assert r.status_code in (200, 201), r.text

        # If sales_forecast entries exist for Jul 2026, the report should use their sum, NOT the legacy value.
        sf_rows = client.get(f"{API}/sales-forecast", params={"year": 2026}).json()
        sf_jul_sum = sum(x["amount"] for x in sf_rows if x["month"] == 7)

        rows = client.get(f"{API}/reports/forecast-vs-actual", params={"year": 2026}).json()["rows"]
        jul = [x for x in rows if x["month"] == 7][0]
        # New typed schema — forecast is dict by type; Revenue side must at least contain the SF sum
        # (quotations may add more, so use >= rather than ==)
        if sf_jul_sum > 0:
            assert jul["forecast"]["Revenue"] >= sf_jul_sum, "sales_forecast Revenue must feed consolidation"
            assert jul["line_items"]["Revenue"] >= 1
        else:
            assert jul["forecast"]["Revenue"] == 3500000

        # Legacy /forecast is still upsert on (year, month)
        client.post(f"{API}/forecast", json={"year": 2026, "month": 7, "amount": 4000000, "notes": "TEST_fc2"})
        fcs = client.get(f"{API}/forecast", params={"year": 2026}).json()
        jul_docs = [f for f in fcs if f["month"] == 7]
        assert len(jul_docs) == 1
        assert jul_docs[0]["amount"] == 4000000
        assert all("_id" not in f for f in fcs)


# --- Meta ---
class TestMeta:
    def test_meta_lists(self, client):
        r = client.get(f"{API}/meta")
        assert r.status_code == 200
        d = r.json()
        for k in ("projects", "accounts", "project_ids"):
            assert k in d and isinstance(d[k], list)

    def test_add_project_and_account(self, client):
        code = "TEST_PRJ_QA"
        acc = "TEST_ACC_QA"
        client.post(f"{API}/meta/project-ids", json={"code": code, "description": "TEST"})
        client.post(f"{API}/meta/accounts", json={"name": acc})
        d = client.get(f"{API}/meta").json()
        assert any(p["code"] == code for p in d["project_ids"])
        assert any(a["name"] == acc for a in d["accounts"])
        # duplicate rejected
        dup = client.post(f"{API}/meta/accounts", json={"name": acc})
        assert dup.status_code == 400
