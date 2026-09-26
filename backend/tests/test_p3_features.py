"""Tests for AI Pending Edit + Attachments (object-storage backed)."""
import io
import os
import re
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"]).rstrip("/")
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


def _tiny_pdf() -> bytes:
    return (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 300]>>endobj\n"
            b"trailer<</Root 1 0 R>>\n%%EOF\n")


class TestEditPending:
    def test_edit_transaction_pending(self, admin):
        # Seed a pending manually via motor
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        env = dotenv_values("/app/backend/.env")
        cl = AsyncIOMotorClient(env["MONGO_URL"])
        d = cl[env["DB_NAME"]]

        async def make():
            r = await d.ai_pending_actions.insert_one({
                "kind": "transaction",
                "data": {"date": "2026-04-15", "type": "Revenue", "account": "TestAcc",
                         "amount": 1000, "project_id": "PRJ", "notes": "seed"},
                "status": "pending",
                "session_id": "test",
                "created_by": env["ADMIN_EMAIL"].lower(),
                "created_at": "2026-01-01",
            })
            return str(r.inserted_id)
        pid = asyncio.get_event_loop().run_until_complete(make())

        try:
            # Edit amount
            r = admin.put(f"{API}/ai/pending/{pid}", json={"data": {
                "date": "2026-04-16", "type": "Revenue", "account": "TestAcc",
                "amount": 2500, "project_id": "PRJ", "notes": "edited"
            }})
            assert r.status_code == 200, r.text
            assert r.json()["data"]["amount"] == 2500

            # Bad payload rejected
            bad = admin.put(f"{API}/ai/pending/{pid}", json={"data": {"amount": "not a number"}})
            assert bad.status_code == 400

            # Approve should apply the EDITED amount
            approve = admin.post(f"{API}/ai/pending/{pid}/approve")
            assert approve.status_code == 200
            txn_id = approve.json()["applied"]["id"]
            got = [t for t in admin.get(f"{API}/transactions").json() if t["id"] == txn_id]
            assert got and got[0]["amount"] == 2500 and got[0]["notes"] == "edited"

            # Second edit after approval fails
            r2 = admin.put(f"{API}/ai/pending/{pid}", json={"data": {"amount": 99}})
            assert r2.status_code == 400

            # cleanup approved txn
            admin.delete(f"{API}/transactions/{txn_id}")
        finally:
            async def rm(): await d.ai_pending_actions.delete_one({"_id": __import__("bson").ObjectId(pid)})
            asyncio.get_event_loop().run_until_complete(rm())
            cl.close()


class TestAttachments:
    def test_upload_list_download_delete(self, admin):
        # Need a real transaction to attach to
        payload = {"date": "2026-04-15", "type": "Revenue", "account": "AttachTest",
                   "amount": 1, "project_id": "ATTACH_PRJ", "notes": "attach-test"}
        c = admin.post(f"{API}/transactions", json=payload)
        assert c.status_code in (200, 201)
        tid = c.json()["id"]

        try:
            # non-PDF rejected
            bad = admin.post(f"{API}/attachments/transaction/{tid}",
                             files={"file": ("bad.txt", io.BytesIO(b"hi"), "text/plain")})
            assert bad.status_code == 400

            # unknown entity 404
            miss = admin.post(f"{API}/attachments/transaction/64b7f2c9a1b2c3d4e5f60718",
                              files={"file": ("i.pdf", io.BytesIO(_tiny_pdf()), "application/pdf")})
            assert miss.status_code == 404

            # good upload
            up = admin.post(f"{API}/attachments/transaction/{tid}",
                            files={"file": ("Invoice.pdf", io.BytesIO(_tiny_pdf()), "application/pdf")})
            assert up.status_code == 200, up.text
            aid = up.json()["id"]
            assert up.json()["filename"] == "Invoice.pdf"

            # list
            lst = admin.get(f"{API}/attachments/transaction/{tid}").json()
            assert len(lst) == 1 and lst[0]["id"] == aid

            # download
            dl = admin.get(f"{API}/attachments/{aid}/download")
            assert dl.status_code == 200
            assert dl.headers["content-type"].startswith("application/pdf")
            assert dl.content.startswith(b"%PDF")

            # unauthenticated download rejected
            assert requests.get(f"{API}/attachments/{aid}/download").status_code == 401

            # delete (soft)
            dd = admin.delete(f"{API}/attachments/{aid}")
            assert dd.status_code == 200
            # after delete: not in list + download 404
            assert admin.get(f"{API}/attachments/transaction/{tid}").json() == []
            assert admin.get(f"{API}/attachments/{aid}/download").status_code == 404

            # bad entity_type rejected
            bad_ent = admin.post(f"{API}/attachments/user/{tid}",
                                 files={"file": ("x.pdf", io.BytesIO(_tiny_pdf()), "application/pdf")})
            assert bad_ent.status_code == 400
        finally:
            admin.delete(f"{API}/transactions/{tid}")
