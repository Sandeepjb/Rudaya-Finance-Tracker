"""Routes: /api/bank-transactions/statement-imports (Azure DI analyze → preview → correct → send to inbox)."""
import hashlib
import os
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, Depends, UploadFile, File, Form

from server import db, require_admin
from bank_inbox import router, BankTxnIn, ingest_one, now_iso, audit, _oid, bank_fingerprint, mask_account
from bank_statements import get_provider, ExtractionError, normalize_statement, identify_bank, reconcile, AzureDocumentIntelligenceProvider
from bank_statements.statement_models import RowCorrectionIn, SendIn

MAX_BYTES = int(os.environ.get("BANK_STATEMENT_MAX_MB", "15")) * 1024 * 1024
COL = db.bank_statement_imports


def _safe_name(n: str) -> str:
    return re.sub(r"[^A-Za-z0-9._ -]", "_", os.path.basename(n or "statement.pdf"))[:120]


def _row_out(r: dict) -> dict:
    return {k: v for k, v in r.items() if k not in ("raw_row",)} | {"fingerprint": r.get("fingerprint")}


def _out(d: dict, rows: bool = True) -> dict:
    o = {"statement_import_id": str(d["_id"]), **{k: d.get(k) for k in (
        "filename", "bank_name", "statement_account_masked", "statement_period_from", "statement_period_to", "extraction_provider",
        "model_id", "analysis_timestamp", "processing_status", "page_count", "transactions_detected", "transactions_valid",
        "transactions_ambiguous", "transactions_duplicate", "reconciliation", "reconciliation_status", "created_by", "created_at",
        "document_fingerprint", "sent_count", "sent_at", "error", "mapping", "headers")}}
    if rows:
        o["rows"] = [_row_out(r) for r in d.get("rows", [])]
    return o


async def _mark_duplicates(rows: list):
    fps = {}
    for r in rows:
        if r["errors"]:
            r["fingerprint"], r["status"] = None, "needs_review"
            continue
        fp = bank_fingerprint(r["txn"])
        if fp in fps:
            r["fingerprint"], r["status"], r["duplicate_of_row"] = None, "duplicate", fps[fp]
            r["errors"] = ["duplicate within statement"]
            continue
        fps[fp] = r["row"]
        r["fingerprint"], r["status"] = fp, "valid"
    existing = {}
    if fps:
        async for d in db.bank_transactions.find({"fingerprint": {"$in": list(fps)}, "status": {"$ne": "duplicate"}}, {"fingerprint": 1}):
            existing[d["fingerprint"]] = str(d["_id"])
    for r in rows:
        if r.get("fingerprint") in existing:
            r["status"], r["duplicate_of_bank_transaction_id"] = "duplicate", existing[r["fingerprint"]]


async def _rebuild(doc: dict, actor: str):
    rows = doc["rows"]
    await _mark_duplicates(rows)
    rec = reconcile(rows, doc.get("statement_totals"), doc.get("opening_balance"))
    doc.update(reconciliation=rec, reconciliation_status=rec["status"], transactions_detected=len(rows),
               transactions_valid=sum(1 for r in rows if r["status"] == "valid"),
               transactions_ambiguous=sum(1 for r in rows if r["needs_review"]),
               transactions_duplicate=sum(1 for r in rows if r["status"] == "duplicate"))
    await audit("statement_reconciliation_completed" if rec["status"] == "MATCHED" else "statement_reconciliation_warning", actor, None,
                new={"status": rec["status"], "messages": rec["messages"]}, extra={"statement_import_id": str(doc["_id"])})


@router.get("/statement-imports/azure/status")
async def azure_status(user: dict = Depends(require_admin)):
    ep = os.environ.get("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", "")
    return {"configured": AzureDocumentIntelligenceProvider.configured(), "endpoint_host": re.sub(r"^https?://", "", ep).split("/")[0] if ep else None,
            "key_present": bool(os.environ.get("AZURE_DOCUMENT_INTELLIGENCE_KEY")), "extraction_provider": get_provider().name,
            "model_id": AzureDocumentIntelligenceProvider.model_id, "max_upload_mb": MAX_BYTES // (1024 * 1024)}


@router.post("/statement-imports/azure/test")
async def azure_test(user: dict = Depends(require_admin)):
    if not AzureDocumentIntelligenceProvider.configured():
        return {"configured": False, "reachable": False, "message": "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT / _KEY not set on the server"}
    from reportlab.pdfgen import canvas
    import io
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(50, 780, "Rudaya Finance Tracker connectivity test")
    c.save()
    try:
        res = await AzureDocumentIntelligenceProvider().analyze(buf.getvalue())
        return {"configured": True, "reachable": True, "message": f"Azure responded: {res.page_count} page(s) analysed with {res.model_id}"}
    except ExtractionError as e:
        return {"configured": True, "reachable": e.code not in ("auth", "network", "timeout"), "error_code": e.code, "message": e.message}


@router.post("/statement-imports/analyze")
async def analyze_statement(file: UploadFile = File(...), bank_name: str = Form(""), provider: str = Form("auto"),
                            user: dict = Depends(require_admin)):
    raw = await file.read()
    if not raw or not raw.strip():
        raise HTTPException(422, "Empty file")
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, f"File exceeds {MAX_BYTES // (1024 * 1024)} MB limit")
    if not raw.lstrip()[:5].startswith(b"%PDF-"):
        raise HTTPException(422, "Not a valid PDF (signature check failed)")
    fname = _safe_name(file.filename)
    doc_fp = hashlib.sha256(raw).hexdigest()
    prev = await COL.find_one({"document_fingerprint": doc_fp, "processing_status": {"$in": ["analyzed", "sent"]}})
    if prev:
        return {"previously_analyzed": True, "message": "Statement previously analyzed/imported", "previous": _out(prev, rows=False)}
    doc = {"filename": fname, "document_fingerprint": doc_fp, "size_bytes": len(raw), "processing_status": "uploaded",
           "created_by": user["email"], "created_at": now_iso(), "bank_hint": bank_name}
    r = await COL.insert_one(doc)
    doc["_id"] = r.inserted_id
    sid = str(r.inserted_id)
    await audit("statement_pdf_uploaded", user["email"], None, new={"filename": fname, "size": len(raw)}, extra={"statement_import_id": sid})
    try:
        prov = get_provider(provider)
    except ExtractionError as e:
        raise HTTPException(e.http_status, e.message)
    await COL.update_one({"_id": r.inserted_id}, {"$set": {"processing_status": "analyzing", "extraction_provider": prov.name, "model_id": prov.model_id}})
    await audit("statement_analysis_started", user["email"], None, new={"provider": prov.name}, extra={"statement_import_id": sid})
    try:
        result = await prov.analyze(raw)
    except ExtractionError as e:
        await COL.update_one({"_id": r.inserted_id}, {"$set": {"processing_status": "failed", "error": {"code": e.code, "message": e.message}}})
        await audit("statement_extraction_failed", user["email"], None, new={"code": e.code}, extra={"statement_import_id": sid})
        raise HTTPException(e.http_status, {"message": e.message, "code": e.code, "statement_import_id": sid})
    await audit("statement_analysis_completed", user["email"], None, new={"pages": result.page_count, "tables": len(result.tables)},
                extra={"statement_import_id": sid})
    bank = identify_bank(result, bank_name)
    norm = normalize_statement(result, bank, "")
    if not norm["rows"]:
        await COL.update_one({"_id": r.inserted_id}, {"$set": {"processing_status": "failed", "error": {"code": "no_table", "message": "No transaction table detected"}}})
        raise HTTPException(422, {"message": "No transaction table detected in the statement", "code": "no_table", "statement_import_id": sid})
    doc.update(bank_name=bank, statement_account_masked=mask_account(norm["account"]), statement_period_from=norm["period"][0],
               statement_period_to=norm["period"][1], extraction_provider=result.provider, model_id=result.model_id,
               analysis_timestamp=now_iso(), page_count=result.page_count, rows=norm["rows"], mapping=norm["mapping"],
               headers=norm["headers"], statement_totals={k: (str(v) if v is not None else None) for k, v in (norm["statement_totals"] or {}).items()} or None,
               opening_balance=norm["opening_balance"], processing_status="analyzed", extraction_tables=len(result.tables))
    for row in doc["rows"]:
        row["txn"]["bank_account"] = norm["account"]
    await _rebuild(doc, user["email"])
    await audit("statement_normalized", user["email"], None, new={"rows": len(doc["rows"]), "bank": bank}, extra={"statement_import_id": sid})
    await COL.update_one({"_id": r.inserted_id}, {"$set": {k: v for k, v in doc.items() if k != "_id"}})
    return _out(doc)


@router.get("/statement-imports")
async def list_imports(user: dict = Depends(require_admin), limit: int = 100):
    docs = await COL.find({}).sort("created_at", -1).to_list(min(limit, 500))
    return [_out(d, rows=False) for d in docs]


@router.get("/statement-imports/{sid}")
async def get_import(sid: str, user: dict = Depends(require_admin)):
    d = await COL.find_one({"_id": _oid(sid)})
    if not d:
        raise HTTPException(404, "Not found")
    return _out(d)


@router.put("/statement-imports/{sid}/rows/{row}")
async def correct_row(sid: str, row: int, payload: RowCorrectionIn, user: dict = Depends(require_admin)):
    d = await COL.find_one({"_id": _oid(sid)})
    if not d or d["processing_status"] not in ("analyzed",):
        raise HTTPException(400, "Import not editable")
    target = next((r for r in d["rows"] if r["row"] == row), None)
    if not target:
        raise HTTPException(404, "Row not found")
    before = dict(target["txn"])
    upd = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "direction" in upd and upd["direction"] not in ("debit", "credit"):
        raise HTTPException(422, "direction must be debit or credit")
    if "amount" in upd and upd["amount"] <= 0:
        raise HTTPException(422, "amount must be > 0")
    if "transaction_date" in upd and not re.match(r"^\d{4}-\d{2}-\d{2}$", upd["transaction_date"]):
        raise HTTPException(422, "transaction_date must be YYYY-MM-DD")
    target["txn"].update(upd)
    target["corrections"] = target.get("corrections", []) + [{"by": user["email"], "at": now_iso(), "before": before, "after": dict(target["txn"])}]
    if target["txn"]["direction"] in ("debit", "credit") and target["txn"]["amount"] > 0 and target["txn"]["transaction_date"] and target["txn"]["narration"]:
        target["errors"], target["needs_review"], target["parse_confidence"], target["confidence_band"] = [], False, 100, "Corrected"
    await _rebuild(d, user["email"])
    await COL.update_one({"_id": d["_id"]}, {"$set": {k: v for k, v in d.items() if k != "_id"}})
    await audit("statement_row_corrected", user["email"], None, previous=before, new=target["txn"], extra={"statement_import_id": sid, "row": row})
    return _out(d)


@router.post("/statement-imports/{sid}/send")
async def send_to_inbox(sid: str, payload: SendIn, user: dict = Depends(require_admin)):
    d = await COL.find_one({"_id": _oid(sid)})
    if not d or d["processing_status"] != "analyzed":
        raise HTTPException(400, "Import is not in analyzed state")
    await _rebuild(d, user["email"])
    chosen = [r for r in d["rows"] if r["row"] in set(payload.rows)]
    results, skipped = [], []
    for r in chosen:
        if r["status"] != "valid":
            skipped.append({"row": r["row"], "reason": r["status"]})
            continue
        bt = await ingest_one(BankTxnIn(**{**r["txn"], "source": "csv", "source_message_id": f"stmt:{sid}:{r['row']}"}), user["email"])
        r["bank_transaction_id"], r["status"] = bt["id"], "sent" if bt["status"] == "pending" else "duplicate"
        results.append({"row": r["row"], "bank_transaction_id": bt["id"], "status": bt["status"]})
    sent = sum(1 for x in results if x["status"] == "pending")
    await COL.update_one({"_id": d["_id"]}, {"$set": {"rows": d["rows"], "processing_status": "sent" if sent else d["processing_status"],
                                                      "sent_count": (d.get("sent_count") or 0) + sent, "sent_at": now_iso()}})
    await db.bank_ingestion_log.insert_one({"timestamp": now_iso(), "actor": user["email"], "channel": "statement_import", "count": len(results),
                                            "pending": sent, "duplicates": len(results) - sent, "sources": ["csv"], "filename": d["filename"],
                                            "bank": d["bank_name"], "ids": [x["bank_transaction_id"] for x in results], "statement_import_id": sid})
    await audit("statement_sent_to_inbox", user["email"], None, new={"sent": sent, "duplicates": len(results) - sent, "skipped": len(skipped)},
                extra={"statement_import_id": sid})
    return {"sent": sent, "duplicates": len(results) - sent, "skipped": skipped, "results": results}


@router.get("/statement-imports/{sid}/audit")
async def import_audit(sid: str, user: dict = Depends(require_admin)):
    docs = await db.bank_audit_log.find({"statement_import_id": sid}).sort("timestamp", 1).to_list(500)
    return [{"id": str(x["_id"]), **{k: v for k, v in x.items() if k != "_id"}} for x in docs]


async def ensure_indexes():
    await COL.create_index("document_fingerprint")
    await COL.create_index([("created_at", -1)])
