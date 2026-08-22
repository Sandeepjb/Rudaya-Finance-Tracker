"""Tests for the new /api/sales-forecast CRUD + consolidated forecast-vs-actual report."""
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
API = f"{base_url.rstrip('/')}/api"
YEAR = 2026


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
def client(creds):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json=creds)
    if r.status_code != 200:
        pytest.fail(f"login failed {r.status_code}: {r.text[:300]}")
    return s


@pytest.fixture(scope="module")
def created_ids():
    return []


@pytest.fixture(scope="module", autouse=True)
def cleanup(client, created_ids):
    yield
    for i in created_ids:
        client.delete(f"{API}/sales-forecast/{i}")


# --- Sales Forecast: seed data & listing ---
class TestSalesForecastList:
    def test_requires_auth(self):
        r = requests.get(f"{API}/sales-forecast", params={"year": YEAR})
        assert r.status_code in (401, 403), r.text[:200]

    def test_seeded_rows(self, client):
        r = client.get(f"{API}/sales-forecast", params={"year": YEAR})
        assert r.status_code == 200, r.text[:300]
        rows = r.json()
        assert isinstance(rows, list)
        # no mongo _id leaked
        assert all("_id" not in x for x in rows)
        for x in rows:
            assert set(["id", "year", "month", "project_id", "amount", "notes", "updated_at"]) <= set(x)
        jul = [x for x in rows if x["month"] == 7]
        aug = [x for x in rows if x["month"] == 8]
        assert len(jul) == 2, f"expected 2 Jul seed rows, got {jul}"
        assert sum(x["amount"] for x in jul) == 3300000, jul
        assert len(aug) == 1, f"expected 1 Aug seed row, got {aug}"
        assert sum(x["amount"] for x in aug) == 500000, aug
        codes = {x["project_id"] for x in jul}
        assert codes == {"FRD_GJ_0002", "AAM-CH_0001"}, codes

    def test_filter_by_project(self, client):
        r = client.get(f"{API}/sales-forecast", params={"year": YEAR, "project_id": "FRD_GJ_0002"})
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 1, rows
        assert rows[0]["project_id"] == "FRD_GJ_0002"
        assert rows[0]["amount"] == 2500000

    def test_sorted_by_year_month(self, client):
        rows = client.get(f"{API}/sales-forecast", params={"year": YEAR}).json()
        months = [x["month"] for x in rows]
        assert months == sorted(months)


# --- Sales Forecast: CRUD lifecycle ---
class TestSalesForecastCrud:
    def test_create_read_update_delete(self, client, created_ids):
        payload = {"year": YEAR, "month": 3, "project_id": "", "amount": 111111.0,
                   "notes": "TEST_qa sales forecast"}
        r = client.post(f"{API}/sales-forecast", json=payload)
        assert r.status_code == 200, r.text[:300]
        row = r.json()
        assert row["id"] and isinstance(row["id"], str)
        assert row["updated_at"]
        assert row["amount"] == 111111.0
        assert row["project_id"] == ""
        created_ids.append(row["id"])

        # GET verifies persistence
        rows = client.get(f"{API}/sales-forecast", params={"year": YEAR}).json()
        got = [x for x in rows if x["id"] == row["id"]]
        assert got and got[0]["notes"] == "TEST_qa sales forecast"

        # UPDATE
        upd = {**payload, "amount": 222222.0, "notes": "TEST_qa updated"}
        r2 = client.put(f"{API}/sales-forecast/{row['id']}", json=upd)
        assert r2.status_code == 200, r2.text[:300]
        assert r2.json()["amount"] == 222222.0
        rows = client.get(f"{API}/sales-forecast", params={"year": YEAR}).json()
        got = [x for x in rows if x["id"] == row["id"]][0]
        assert got["amount"] == 222222.0 and got["notes"] == "TEST_qa updated"

        # DELETE
        r3 = client.delete(f"{API}/sales-forecast/{row['id']}")
        assert r3.status_code == 200, r3.text[:300]
        rows = client.get(f"{API}/sales-forecast", params={"year": YEAR}).json()
        assert not [x for x in rows if x["id"] == row["id"]]
        created_ids.remove(row["id"])

        # second delete -> 404
        assert client.delete(f"{API}/sales-forecast/{row['id']}").status_code == 404

    def test_create_invalid_month(self, client):
        r = client.post(f"{API}/sales-forecast",
                        json={"year": YEAR, "month": 13, "amount": 100, "notes": "TEST_qa bad"})
        assert r.status_code == 400, f"{r.status_code} {r.text[:200]}"

    def test_create_month_zero(self, client):
        r = client.post(f"{API}/sales-forecast",
                        json={"year": YEAR, "month": 0, "amount": 100, "notes": "TEST_qa bad"})
        assert r.status_code == 400, f"{r.status_code} {r.text[:200]}"

    def test_create_missing_amount_422(self, client):
        r = client.post(f"{API}/sales-forecast", json={"year": YEAR, "month": 5})
        assert r.status_code == 422, f"{r.status_code} {r.text[:200]}"

    def test_update_invalid_id_400(self, client):
        r = client.put(f"{API}/sales-forecast/not-an-oid",
                       json={"year": YEAR, "month": 5, "amount": 1})
        assert r.status_code == 400, f"{r.status_code} {r.text[:200]}"

    def test_update_missing_id_404(self, client):
        r = client.put(f"{API}/sales-forecast/64b7f9f1f1f1f1f1f1f1f1f1",
                       json={"year": YEAR, "month": 5, "amount": 1})
        assert r.status_code == 404, f"{r.status_code} {r.text[:200]}"

    def test_delete_invalid_id_400(self, client):
        r = client.delete(f"{API}/sales-forecast/xyz")
        assert r.status_code == 400, f"{r.status_code} {r.text[:200]}"

    def test_crud_requires_auth(self):
        r = requests.post(f"{API}/sales-forecast", json={"year": YEAR, "month": 1, "amount": 1})
        assert r.status_code in (401, 403)


# --- Consolidated forecast vs actual report (typed by Revenue/Cost/Expense) ---
class TestForecastVsActual:
    def test_consolidation_from_sales_forecast(self, client):
        r = client.get(f"{API}/reports/forecast-vs-actual", params={"year": YEAR})
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert len(d["rows"]) == 12
        by_m = {x["month"]: x for x in d["rows"]}
        # Jul-2026 seed = FRD_GJ_0002 25L + AAM-CH_0001 8L (both Revenue) = 33L
        assert by_m[7]["forecast"]["Revenue"] == 3300000, by_m[7]
        assert by_m[7]["line_items"]["Revenue"] == 2
        assert by_m[8]["forecast"]["Revenue"] == 500000, by_m[8]
        assert by_m[8]["line_items"]["Revenue"] == 1
        # total_forecast is a dict-by-type; sum must equal all sales_forecast rows for the year
        sf_rows = client.get(f"{API}/sales-forecast", params={"year": YEAR}).json()
        expected_total = sum(x["amount"] for x in sf_rows)
        # NB: report also adds non-lost quotation lines, so the derived total is a lower bound.
        assert d["total_forecast_all"] >= expected_total - 1, (d["total_forecast_all"], expected_total)
        assert abs(d["total_actual"]["Revenue"] - 4621778) < 5, d["total_actual"]
        # variance / achievement math
        rev_var = by_m[7]["variance"]["Revenue"]
        assert rev_var == by_m[7]["actual"]["Revenue"] - by_m[7]["forecast"]["Revenue"]
        if by_m[7]["forecast"]["Revenue"]:
            pct = by_m[7]["achievement_pct"]["Revenue"]
            expected_pct = by_m[7]["actual"]["Revenue"] / by_m[7]["forecast"]["Revenue"] * 100
            assert abs(pct - expected_pct) < 0.01
        # months with no forecast must have None achievement + zero line_items
        assert by_m[1]["achievement_pct"]["Revenue"] is None  # noqa: E711 — PEP 8: use `is` for None
        assert by_m[1]["line_items"]["Revenue"] == 0

    def test_sales_forecast_overrides_legacy(self, client):
        """Legacy Jul-2026 forecast doc must be overridden by SF sum (Revenue side)."""
        legacy = client.get(f"{API}/forecast", params={"year": YEAR}).json()
        jul_legacy = [x for x in legacy if x["month"] == 7]
        if not jul_legacy:
            pytest.skip("no legacy Jul-2026 forecast doc present")
        assert jul_legacy[0]["amount"] != 3300000, "legacy value must differ to prove override"
        rep = client.get(f"{API}/reports/forecast-vs-actual", params={"year": YEAR}).json()
        jul = [x for x in rep["rows"] if x["month"] == 7][0]
        # sales_forecast Revenue lines for Jul sum to 33L
        sf_jul_rev = sum(x["amount"] for x in client.get(f"{API}/sales-forecast", params={"year": YEAR}).json()
                         if x["month"] == 7 and x.get("type", "Revenue") == "Revenue")
        # forecast for Jul Revenue must at least include sf sum (plus any non-lost quotation lines)
        assert jul["forecast"]["Revenue"] >= sf_jul_rev, "sales_forecast Revenue must feed into consolidated forecast"

    def test_legacy_backfill_when_no_sf_entries(self, client, created_ids):
        """Month with only a legacy forecast doc backfills into Revenue and is overridden once SF added."""
        month = 11
        client.post(f"{API}/forecast", json={"year": YEAR, "month": month,
                                            "amount": 900000, "notes": "TEST_qa legacy"})
        rep = client.get(f"{API}/reports/forecast-vs-actual", params={"year": YEAR}).json()
        row = [x for x in rep["rows"] if x["month"] == month][0]
        assert row["forecast"]["Revenue"] == 900000, row
        assert row["line_items"]["Revenue"] == 0

        sf = client.post(f"{API}/sales-forecast", json={"year": YEAR, "month": month,
                                                       "type": "Revenue", "project_id": "",
                                                       "amount": 100000, "notes": "TEST_qa override"}).json()
        created_ids.append(sf["id"])
        rep = client.get(f"{API}/reports/forecast-vs-actual", params={"year": YEAR}).json()
        row = [x for x in rep["rows"] if x["month"] == month][0]
        assert row["forecast"]["Revenue"] == 100000, f"sales_forecast should win: {row}"
        assert row["line_items"]["Revenue"] == 1

        # cleanup
        client.delete(f"{API}/sales-forecast/{sf['id']}")
        created_ids.remove(sf["id"])
        lf = [x for x in client.get(f"{API}/forecast", params={"year": YEAR}).json() if x["month"] == month]
        if lf:
            client.delete(f"{API}/forecast/{lf[0]['id']}")

    def test_report_totals_update_after_new_entry(self, client, created_ids):
        before = client.get(f"{API}/reports/forecast-vs-actual", params={"year": YEAR}).json()["total_forecast_all"]
        sf = client.post(f"{API}/sales-forecast", json={"year": YEAR, "month": 4, "type": "Revenue",
                                                       "project_id": "", "amount": 250000,
                                                       "notes": "TEST_qa delta"}).json()
        created_ids.append(sf["id"])
        after = client.get(f"{API}/reports/forecast-vs-actual", params={"year": YEAR}).json()["total_forecast_all"]
        assert after == before + 250000, (before, after)
        client.delete(f"{API}/sales-forecast/{sf['id']}")
        created_ids.remove(sf["id"])
        final = client.get(f"{API}/reports/forecast-vs-actual", params={"year": YEAR}).json()["total_forecast_all"]
        assert final == before
