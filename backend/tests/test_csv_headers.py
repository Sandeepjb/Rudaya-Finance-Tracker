"""CSV migration header normalisation: human-readable headers (e.g. 'Project ID') must map to project_id."""
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


@pytest.fixture(scope="module")
def admin():
    c = Path("/app/memory/test_credentials.md").read_text()
    e = re.search(r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?email(?:\*\*)?\s*:\s*`?([^`\s]+)", c).group(1)
    pw = re.search(r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?password(?:\*\*)?\s*:\s*`?([^`\s]+)", c).group(1)
    s = requests.Session()
    assert s.post(f"{API}/auth/login", json={"email": e, "password": pw}).status_code == 200
    return s


def _csv(tag: str) -> bytes:
    return (" Date , Type ,Account,  Amount , Project ID ,Notes\n"
            f"2026-04-15,Revenue,Sales - Solar,250000,PRJ-HDR-{tag},{tag} header test\n"
            f"15/04/2026,Cost,Materials,50000,PRJ-HDR-{tag},{tag} panels\n").encode()


def _post(admin, path, raw, **data):
    return admin.post(f"{API}/migrations/{path}", files={"file": ("human.csv", io.BytesIO(raw), "text/csv")}, data=data)


class TestHumanReadableHeaders:
    def test_unit_header_normalisation(self):
        import sys
        sys.path.insert(0, "/app/backend")
        from server import _parse_csv_rows
        rows, err = _parse_csv_rows(_csv("UNIT"))
        assert err is None, err
        assert len(rows) == 2 and all(r["valid"] for r in rows), rows
        assert rows[0]["parsed"]["project_id"] == "PRJ-HDR-UNIT"
        rows, err = _parse_csv_rows(b"DATE,TYPE,ACCOUNT,AMOUNT,PROJECT   ID,NOTES\n2026-01-01,Revenue,A,1,P,n\n")
        assert err is None and rows[0]["valid"]
        _, err = _parse_csv_rows(b"date,type,account,amount,notes\n")
        assert err and "project_id" in err

    def test_preview_and_import_repeatable(self, admin, txn_state_lock):
        tag = uuid.uuid4().hex[:6].upper()
        raw = _csv(tag)
        for _ in range(2):
            p = _post(admin, "preview", raw)
            assert p.status_code == 200, p.text
            assert "Missing required column" not in p.text
            assert p.json()["valid_rows"] == 2, {k: v for k, v in p.json().items() if k != "rows"}
        first = _post(admin, "import", raw, mode="skip_duplicates")
        assert first.status_code == 200, first.text
        assert first.json()["inserted"] == 2
        second = _post(admin, "import", raw, mode="skip_duplicates")
        assert second.status_code == 200, second.text
        assert second.json()["inserted"] == 0 and second.json()["skipped_duplicate"] == 2
        txns = admin.get(f"{API}/transactions", params={"search": f"{tag} "}).json()
        assert len(txns) == 2 and {t["project_id"] for t in txns} == {f"PRJ-HDR-{tag}"}
        for t in txns:
            admin.delete(f"{API}/transactions/{t['id']}")
