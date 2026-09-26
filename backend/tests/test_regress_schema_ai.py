"""Regression: typed forecast-vs-actual schema, quotation->forecast contribution, AI SSE stream."""
import json
import os
import re
import time
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or dotenv_values("/app/frontend/.env").get("REACT_APP_BACKEND_URL")).rstrip("/")


def _creds():
    p = Path("/app/memory/test_credentials.md")
    if not p.exists():
        pytest.skip("missing test_credentials.md")
    c = p.read_text()
    e = re.search(r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?email(?:\*\*)?\s*:\s*`?([^`\s]+)", c)
    pw = re.search(r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?password(?:\*\*)?\s*:\s*`?([^`\s]+)", c)
    if not e or not pw:
        pytest.skip("creds not parseable")
    return {"email": e.group(1), "password": pw.group(1)}


CREDS = _creds()
TYPES = ["Revenue", "Cost", "Expense"]


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=CREDS, timeout=30)
    if r.status_code != 200:
        pytest.fail(f"login failed {r.status_code}: {r.text[:300]}")
    assert "access_token" in s.cookies.get_dict(), s.cookies.get_dict()
    return s


# --- typed schema ---
class TestTypedSchema:
    def test_forecast_vs_actual_typed(self, client):
        r = client.get(f"{BASE_URL}/api/reports/forecast-vs-actual", params={"year": 2026}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert "_id" not in r.text
        assert len(d["rows"]) == 12
        for row in d["rows"]:
            for f in ("forecast", "actual", "variance", "achievement_pct", "line_items"):
                assert isinstance(row[f], dict), (f, row[f])
                assert set(row[f].keys()) == set(TYPES), (f, row[f].keys())
            for t in TYPES:
                assert isinstance(row["line_items"][t], int), row["line_items"]
                assert isinstance(row["forecast"][t], (int, float))
                assert abs(row["variance"][t] - (row["actual"][t] - row["forecast"][t])) < 0.01
        for k in ("total_forecast", "total_actual"):
            assert set(d[k].keys()) == set(TYPES), d[k]
        for k in ("total_forecast_all", "total_actual_all"):
            assert isinstance(d[k], (int, float)), (k, d[k])
        assert abs(d["total_forecast_all"] - sum(d["total_forecast"].values())) < 1
        assert abs(d["total_actual_all"] - sum(d["total_actual"].values())) < 1
        # months sum to totals
        for t in TYPES:
            assert abs(sum(r_["forecast"][t] for r_ in d["rows"]) - d["total_forecast"][t]) < 1

    def test_totals_types(self, client):
        r = client.get(f"{BASE_URL}/api/reports/forecast-vs-actual", params={"year": 2026}, timeout=30)
        assert r.json()["types"] == TYPES


# --- quotation CRUD + forecast contribution ---
class TestQuotationForecast:
    def test_quotation_crud_and_forecast(self, client, txn_state_lock):
        y, m = 2026, 3
        before = client.get(f"{BASE_URL}/api/reports/forecast-vs-actual",
                            params={"year": y}, timeout=30).json()
        base = before["rows"][m - 1]["forecast"]["Revenue"]
        base_all = before["total_forecast_all"]

        payload = {
            "quotation_number": f"TEST_QA_{uuid.uuid4().hex[:8]}",
            "client_name": "TEST_QA Customer",
            "quote_date": f"{y}-03-05",
            "expected_month": m,
            "expected_year": y,
            "status": "open",
            "lines": [
                {"description": "TEST item", "type": "Revenue", "amount": 12345.0},
            ],
        }
        r = client.post(f"{BASE_URL}/api/quotations", json=payload, timeout=30)
        assert r.status_code in (200, 201), f"{r.status_code} {r.text[:400]}"
        created = r.json()
        qid = created.get("id") or created.get("_id")
        assert qid, created
        assert "_id" not in created

        try:
            mid = client.get(f"{BASE_URL}/api/reports/forecast-vs-actual",
                             params={"year": y}, timeout=30).json()
            assert abs(mid["rows"][m - 1]["forecast"]["Revenue"] - (base + 12345.0)) < 1, \
                (base, mid["rows"][m - 1]["forecast"])
            assert abs(mid["total_forecast_all"] - (base_all + 12345.0)) < 1

            # edit -> amount change reflects
            payload["lines"][0]["amount"] = 20000.0
            ru = client.put(f"{BASE_URL}/api/quotations/{qid}", json=payload, timeout=30)
            assert ru.status_code == 200, ru.text[:400]
            mid2 = client.get(f"{BASE_URL}/api/reports/forecast-vs-actual",
                              params={"year": y}, timeout=30).json()
            assert abs(mid2["rows"][m - 1]["forecast"]["Revenue"] - (base + 20000.0)) < 1

            # lost status -> excluded
            payload["status"] = "lost"
            assert client.put(f"{BASE_URL}/api/quotations/{qid}", json=payload,
                              timeout=30).status_code == 200
            mid3 = client.get(f"{BASE_URL}/api/reports/forecast-vs-actual",
                              params={"year": y}, timeout=30).json()
            assert abs(mid3["rows"][m - 1]["forecast"]["Revenue"] - base) < 1, \
                "lost quotation should not contribute to forecast"
        finally:
            rd = client.delete(f"{BASE_URL}/api/quotations/{qid}", timeout=30)
            assert rd.status_code in (200, 204), rd.text[:300]

        after = client.get(f"{BASE_URL}/api/reports/forecast-vs-actual",
                           params={"year": y}, timeout=30).json()
        assert abs(after["rows"][m - 1]["forecast"]["Revenue"] - base) < 1
        assert abs(after["total_forecast_all"] - base_all) < 1


    def test_duplicate_quotation_number_not_500(self, client):
        """Unique index on quotation_number must surface as 4xx, not 500."""
        num = f"TEST_QA_DUP_{uuid.uuid4().hex[:8]}"
        payload = {"quotation_number": num, "client_name": "TEST_QA",
                   "quote_date": "2026-03-05", "expected_year": 2026,
                   "expected_month": 3, "status": "draft",
                   "lines": [{"type": "Revenue", "description": "x", "amount": 1.0}]}
        r1 = client.post(f"{BASE_URL}/api/quotations", json=payload, timeout=30)
        assert r1.status_code in (200, 201), r1.text[:300]
        qid = r1.json()["id"]
        try:
            r2 = client.post(f"{BASE_URL}/api/quotations", json=payload, timeout=30)
            assert r2.status_code in (400, 409, 422), \
                f"duplicate quotation_number returned {r2.status_code} (expected 409)"
        finally:
            client.delete(f"{BASE_URL}/api/quotations/{qid}", timeout=30)


# --- AI SSE ---
class TestAiChat:
    def test_ai_chat_streams(self, client):
        t0 = time.time()
        with client.post(f"{BASE_URL}/api/ai/chat",
                         json={"message": "What is my total actual revenue in one line?", "year": 2026},
                         stream=True, timeout=120) as r:
            assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
            assert "text/event-stream" in r.headers.get("content-type", ""), r.headers
            chunks = []
            for line in r.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if raw in ("[DONE]", ""):
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    chunks.append(raw)
                    continue
                if isinstance(obj, dict):
                    assert "error" not in obj, obj
                    for k in ("delta", "content", "text", "token"):
                        if obj.get(k):
                            chunks.append(obj[k])
                            break
                if time.time() - t0 > 90:
                    break
        text = "".join(chunks)
        print("AI reply:", text[:400], "elapsed", round(time.time() - t0, 1))
        assert len(text.strip()) > 5, f"empty AI reply, chunks={chunks[:5]}"
