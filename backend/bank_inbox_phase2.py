"""Phase 2: Microsoft 365 queue consumption (Outlook → Power Automate → SharePoint → here), reconciliation, PDF import."""
import io
import json
import re
from typing import Optional, List

from bson import ObjectId
from fastapi import HTTPException, Depends, UploadFile, File, Form, Header
from pydantic import BaseModel, Field

from server import db, require_admin
from bank_inbox import (router, BankTxnIn, ingest_one, require_ingest_key, now_iso, audit, _oid, _out,
                        bank_fingerprint, _validate_payload, mask_account, MAX_BATCH)
from bank_parsers import ParseContext, parse_alert
from bank_parsers.registry import parse_all, select_parser, selection_detail

QUEUE_SOURCES = {"power_automate", "sharepoint", "email"}
QUEUE_STATUSES = {"received", "parsed", "parse_failed", "duplicate", "pending"}


class QueueMessageIn(BaseModel):
    source_message_id: str = Field("", max_length=300)
    internet_message_id: str = Field("", max_length=300)
    sender: str = Field("", max_length=300)
    recipient: str = Field("", max_length=300)
    subject: str = Field("", max_length=500)
    received_at: str = Field("", max_length=40)
    received_datetime: str = Field("", max_length=40)
    body: str = Field("", max_length=20000)
    email_body_text: str = Field("", max_length=20000)
    email_body_html: str = Field("", max_length=60000)
    bank_hint: str = Field("", max_length=100)
    source: str = Field("power_automate", max_length=30)
    queue_item_id: str = Field("", max_length=100)
    idempotency_key: str = Field("", max_length=200)

    def normalized(self) -> "QueueMessageIn":
        from bank_parsers.base import html_to_text
        mid = (self.source_message_id or self.internet_message_id or self.idempotency_key or "").strip()
        if len(mid) < 3:
            raise HTTPException(422, "source_message_id (or internet_message_id / idempotency_key) is required")
        body = (self.body or self.email_body_text or html_to_text(self.email_body_html) or "").strip()
        if len(body) < 5:
            raise HTTPException(422, "email body is required (body, email_body_text or email_body_html)")
        return self.model_copy(update={"source_message_id": mid, "body": body,
                                       "received_at": self.received_at or self.received_datetime,
                                       "internet_message_id": self.internet_message_id or mid})


class QueueBatchIn(BaseModel):
    messages: List[QueueMessageIn] = Field(..., min_length=1, max_length=MAX_BATCH)


class ParserTestIn(BaseModel):
    body: str = Field(..., min_length=1, max_length=20000)
    subject: str = Field("", max_length=500)
    sender: str = Field("", max_length=300)
    bank_hint: str = Field("", max_length=100)
    received_at: str = Field("", max_length=40)


def _qm_out(d: dict) -> dict:
    return {"id": str(d["_id"]), "source": d.get("source"), "source_message_id": d.get("source_message_id"),
            "internet_message_id": d.get("internet_message_id"), "queue_item_id": d.get("queue_item_id", ""),
            "idempotency_key": d.get("idempotency_key", ""), "parser_version": d.get("parser_version"),
            "selection_method": d.get("selection_method"), "selection_confidence": d.get("selection_confidence"),
            "parse_warnings": d.get("parse_warnings") or [],
            "sender_masked": _mask_sender(d.get("sender", "")), "subject": d.get("subject", ""),
            "received_at": d.get("received_at", ""), "bank_hint": d.get("bank_hint", ""),
            "parsing_status": d.get("parsing_status"), "parser": d.get("parser"), "parser_score": d.get("parser_score"),
            "parse_errors": d.get("parse_errors") or [], "parsed_fields": _safe_fields(d.get("parsed_fields")),
            "bank_transaction_id": d.get("bank_transaction_id"), "duplicate_of_message": d.get("duplicate_of_message"),
            "body_preview": (d.get("body") or "")[:160], "created_at": d.get("created_at"),
            "resolved_at": d.get("resolved_at"), "resolved_by": d.get("resolved_by")}


def _mask_sender(s: str) -> str:
    if "@" not in s:
        return s[:3] + "…" if s else ""
    u, dom = s.rsplit("@", 1)
    return f"{u[:2]}…@{dom}"


def _safe_fields(f: Optional[dict]) -> Optional[dict]:
    if not f:
        return f
    return {**f, "bank_account": mask_account(f.get("bank_account"))}


async def process_queue_message(m: QueueMessageIn, actor: str, header_idem: str = "") -> dict:
    """Validate → source-dup / idempotency replay → identify bank → parse → bank txn (fingerprint dup + classify) → pending."""
    m = m.normalized()
    src = m.source.strip().lower()
    if src not in QUEUE_SOURCES:
        raise HTTPException(422, f"source must be one of {sorted(QUEUE_SOURCES)}")
    idem = (m.idempotency_key or header_idem or "").strip()
    doc = {"source": src, "source_message_id": m.source_message_id, "internet_message_id": m.internet_message_id,
           "sender": m.sender, "recipient": m.recipient, "subject": m.subject, "received_at": m.received_at,
           "body": m.body, "bank_hint": m.bank_hint, "queue_item_id": m.queue_item_id, "idempotency_key": idem,
           "parsing_status": "received", "created_at": now_iso(), "actor": actor}
    dup_or = [{"source_message_id": doc["source_message_id"]}]
    if idem:
        dup_or.append({"idempotency_key": idem})
    prior = await db.bank_queue_messages.find_one({"$or": dup_or, "parsing_status": {"$nin": ["duplicate"]}})
    if prior:
        # Replay: do NOT create another inbox item — return the existing result, audited.
        await db.bank_queue_messages.update_one({"_id": prior["_id"]}, {"$inc": {"replay_count": 1},
                                                                        "$set": {"last_replay_at": now_iso()}})
        await audit("queue_duplicate_message", actor, prior.get("bank_transaction_id"),
                    new={"source_message_id": doc["source_message_id"], "idempotency_key": idem,
                         "existing_queue_message_id": str(prior["_id"])})
        out = _qm_out(prior)
        out.update(parsing_status="duplicate", duplicate_of_message=str(prior["_id"]), replay=True,
                   existing_status=prior.get("parsing_status"))
        if prior.get("bank_transaction_id"):
            bt = await db.bank_transactions.find_one({"_id": ObjectId(prior["bank_transaction_id"])})
            if bt:
                out["transaction"] = _out(bt)
        return out
    r = await db.bank_queue_messages.insert_one(doc)
    qid = r.inserted_id
    ctx = ParseContext(body=m.body, subject=m.subject, sender=m.sender, bank_hint=m.bank_hint, received_at=m.received_at)
    det = selection_detail(ctx)
    score = det["score"]
    res = parse_alert(ctx)
    upd = {"parser": res.parser, "parser_score": score, "parsed_fields": res.fields, "parse_errors": res.errors,
           "parse_warnings": res.warnings, "parser_version": res.parser_version,
           "selection_method": res.selection_method, "selection_confidence": res.selection_confidence}
    if not res.ok:
        upd["parsing_status"] = "parse_failed"
        await db.bank_queue_messages.update_one({"_id": qid}, {"$set": upd})
        await audit("queue_parse_failed", "system", None, new={"queue_message_id": str(qid), "errors": res.errors,
                                                               "parser": res.parser})
        return _qm_out({**doc, **upd, "_id": qid})
    upd["parsing_status"] = "parsed"
    await db.bank_queue_messages.update_one({"_id": qid}, {"$set": upd})
    try:
        txn = BankTxnIn(**{**_txn_fields(res.fields), "source": src, "source_message_id": doc["source_message_id"],
                           "source_raw_text": m.body[:4000]})
        bt = await ingest_one(txn, actor)
    except HTTPException as e:
        upd.update(parsing_status="parse_failed", parse_errors=res.errors + [str(e.detail)])
        await db.bank_queue_messages.update_one({"_id": qid}, {"$set": upd})
        return _qm_out({**doc, **upd, "_id": qid})
    final = {"parsing_status": "duplicate" if bt["status"] == "duplicate" else "pending",
             "bank_transaction_id": bt["id"]}
    await db.bank_queue_messages.update_one({"_id": qid}, {"$set": final})
    await db.bank_transactions.update_one({"_id": ObjectId(bt["id"])},
                                          {"$set": {"queue_message_id": str(qid), "queue_item_id": m.queue_item_id,
                                                    "parser_name": res.parser, "parser_version": res.parser_version}})
    return {**_qm_out({**doc, **upd, **final, "_id": qid}), "transaction": bt}


BANK_TXN_KEYS = {"bank_name", "bank_account", "transaction_date", "transaction_time", "direction", "amount", "currency",
                 "narration", "merchant_name", "bank_reference", "utr_reference"}


def _txn_fields(fields: dict) -> dict:
    return {k: v for k, v in fields.items() if k in BANK_TXN_KEYS and v is not None}


@router.post("/queue")
async def queue_ingest(payload: QueueBatchIn, actor: str = Depends(require_ingest_key),
                       x_idempotency_key: Optional[str] = Header(None)):
    header_idem = (x_idempotency_key or "").strip() if len(payload.messages) == 1 else ""
    results = [await process_queue_message(m, actor, header_idem) for m in payload.messages]
    counts = {s: sum(1 for r in results if r["parsing_status"] == s) for s in QUEUE_STATUSES}
    await db.bank_ingestion_log.insert_one({
        "timestamp": now_iso(), "actor": actor, "channel": "m365_queue", "count": len(results),
        "pending": counts["pending"], "duplicates": counts["duplicate"], "failed": counts["parse_failed"],
        "sources": sorted({r["source"] for r in results}), "ids": [r.get("bank_transaction_id") for r in results if r.get("bank_transaction_id")],
        "queue_message_ids": [r["id"] for r in results]})
    return {"count": len(results), **counts, "results": results}


@router.get("/queue")
async def list_queue(user: dict = Depends(require_admin), status: Optional[str] = None, limit: int = 200):
    q = {"parsing_status": status} if status and status != "all" else {}
    docs = await db.bank_queue_messages.find(q).sort("created_at", -1).to_list(min(limit, 1000))
    return [_qm_out(d) for d in docs]


@router.get("/queue/stats")
async def queue_stats(user: dict = Depends(require_admin)):
    out = {s: 0 for s in QUEUE_STATUSES}
    async for r in db.bank_queue_messages.aggregate([{"$group": {"_id": "$parsing_status", "n": {"$sum": 1}}}]):
        out[r["_id"]] = r["n"]
    return out


@router.get("/queue/{qid}")
async def get_queue_message(qid: str, user: dict = Depends(require_admin)):
    d = await db.bank_queue_messages.find_one({"_id": _oid(qid)})
    if not d:
        raise HTTPException(404, "Not found")
    out = _qm_out(d)
    out["body"] = d.get("body", "")
    out["candidates"] = parse_all(ParseContext(body=d.get("body", ""), subject=d.get("subject", ""), sender=d.get("sender", ""),
                                               bank_hint=d.get("bank_hint", ""), received_at=d.get("received_at", "")))
    return out


class QueueResolveIn(BaseModel):
    bank_name: str = Field(..., min_length=1, max_length=100)
    bank_account: str = Field("", max_length=40)
    transaction_date: str
    direction: str
    amount: float
    narration: str = Field(..., min_length=1, max_length=500)
    bank_reference: str = ""


@router.post("/queue/{qid}/resolve")
async def resolve_queue_message(qid: str, payload: QueueResolveIn, user: dict = Depends(require_admin)):
    """Admin manually supplies the fields for a parse_failed message → enters the normal pending pipeline."""
    d = await db.bank_queue_messages.find_one({"_id": _oid(qid)})
    if not d:
        raise HTTPException(404, "Not found")
    if d["parsing_status"] != "parse_failed":
        raise HTTPException(400, f"Message is {d['parsing_status']}, not parse_failed")
    txn = BankTxnIn(**{**payload.model_dump(), "source": d["source"], "source_message_id": d["source_message_id"],
                       "source_raw_text": (d.get("body") or "")[:4000]})
    bt = await ingest_one(txn, user["email"])
    await db.bank_queue_messages.update_one({"_id": d["_id"]}, {"$set": {
        "parsing_status": "duplicate" if bt["status"] == "duplicate" else "pending", "bank_transaction_id": bt["id"],
        "parser": "manual", "parsed_fields": payload.model_dump(), "resolved_at": now_iso(), "resolved_by": user["email"]}})
    await audit("queue_manually_resolved", user["email"], bt["id"], new={"queue_message_id": qid})
    return {"queue_message": _qm_out(await db.bank_queue_messages.find_one({"_id": d["_id"]})), "transaction": bt}


@router.post("/queue/{qid}/discard")
async def discard_queue_message(qid: str, user: dict = Depends(require_admin)):
    d = await db.bank_queue_messages.find_one({"_id": _oid(qid)})
    if not d:
        raise HTTPException(404, "Not found")
    if d["parsing_status"] != "parse_failed":
        raise HTTPException(400, "Only parse_failed messages can be discarded")
    await db.bank_queue_messages.update_one({"_id": d["_id"]}, {"$set": {"parsing_status": "discarded", "resolved_at": now_iso(),
                                                                         "resolved_by": user["email"]}})
    await audit("queue_discarded", user["email"], None, new={"queue_message_id": qid})
    return {"ok": True}


@router.post("/parsers/test")
async def parsers_test(payload: ParserTestIn, user: dict = Depends(require_admin)):
    ctx = ParseContext(**payload.model_dump())
    det = selection_detail(ctx)
    best = parse_alert(ctx)
    missing = [k for k in ("bank_account", "bank_reference", "utr_reference", "transaction_time", "merchant_name") if not best.fields.get(k)]
    return {"selected_parser": det["selected_parser"], "selected_score": det["score"], "selection_method": best.selection_method,
            "selection_confidence": best.selection_confidence, "parser_version": best.parser_version,
            "result_parser": best.parser, "ok": best.ok, "bank_name": best.bank_name, "fields": _safe_fields(best.fields),
            "raw_fields": best.fields if best.ok else None, "errors": best.errors, "warnings": best.warnings,
            "missing_optional": missing, "candidates": [{**c, "fields": _safe_fields(c["fields"])} for c in parse_all(ctx)]}


class ParserSubmitIn(ParserTestIn):
    source: str = Field("email", max_length=30)
    source_message_id: str = Field("", max_length=300)


@router.post("/parsers/submit")
async def parsers_submit(payload: ParserSubmitIn, user: dict = Depends(require_admin)):
    """Admin deliberately sends a successfully parsed alert through the normal Phase 1 pipeline (pending approval)."""
    ctx = ParseContext(body=payload.body, subject=payload.subject, sender=payload.sender, bank_hint=payload.bank_hint,
                       received_at=payload.received_at)
    best = parse_alert(ctx)
    if not best.ok:
        raise HTTPException(422, {"message": "Alert did not parse", "errors": best.errors})
    mid = payload.source_message_id.strip() or f"parser-test-{now_iso()}"
    m = QueueMessageIn(source_message_id=mid, sender=payload.sender, subject=payload.subject, received_at=payload.received_at,
                       body=payload.body, bank_hint=payload.bank_hint, source=payload.source if payload.source in QUEUE_SOURCES else "email")
    return await process_queue_message(m, user["email"])


@router.get("/parsers")
async def list_parsers(user: dict = Depends(require_admin)):
    from bank_parsers import PARSERS
    return [{"name": p.name, "bank_name": p.bank_name, "keywords": list(p.keywords), "sender_keywords": list(p.sender_keywords)}
            for p in PARSERS]


# ================= Reconciliation =================
RECON_WINDOW_DAYS = 3


def _day_diff(a: str, b: str) -> int:
    from datetime import date
    try:
        return abs((date.fromisoformat(a[:10]) - date.fromisoformat(b[:10])).days)
    except Exception:
        return 999


async def _recon_candidates(bt: dict, window: int = RECON_WINDOW_DAYS) -> list:
    from datetime import date, timedelta
    d0 = date.fromisoformat(bt["transaction_date"])
    lo, hi = (d0 - timedelta(days=window)).isoformat(), (d0 + timedelta(days=window)).isoformat() + "T23:59:59"
    amt = float(bt["amount"])
    q = {"date": {"$gte": lo, "$lte": hi}, "amount": {"$gte": amt * 0.98, "$lte": amt * 1.02}}
    linked = set()
    async for x in db.bank_transactions.find({"finance_transaction_id": {"$ne": None}, "_id": {"$ne": bt["_id"]}},
                                             {"finance_transaction_id": 1}):
        linked.add(x["finance_transaction_id"])
    out = []
    async for t in db.transactions.find(q).limit(50):
        if str(t["_id"]) in linked:
            continue
        exact = abs(float(t["amount"]) - amt) < 0.01
        dd = _day_diff(t["date"], bt["transaction_date"])
        score = (60 if exact else 40) + max(0, 20 - dd * 6) + (20 if t.get("source") not in ("bank_transaction",) else 0)
        out.append({"id": str(t["_id"]), "date": t["date"][:10], "type": t["type"], "account": t["account"],
                    "project_id": t["project_id"], "amount": t["amount"], "notes": t.get("notes", ""),
                    "source": t.get("source", ""), "score": min(100, score), "exact_amount": exact, "day_diff": dd})
    out.sort(key=lambda x: -x["score"])
    return out


@router.get("/reconciliation/summary")
async def recon_summary(user: dict = Depends(require_admin)):
    out = {"matched": 0, "unmatched": 0, "partially_matched": 0, "ignored": 0}
    async for r in db.bank_transactions.aggregate([{"$match": {"status": {"$in": ["approved", "pending"]}}},
                                                   {"$group": {"_id": "$reconciliation_status", "n": {"$sum": 1}}}]):
        out[r["_id"] or "unmatched"] = r["n"]
    linked = {x["finance_transaction_id"] async for x in db.bank_transactions.find({"finance_transaction_id": {"$ne": None}},
                                                                                   {"finance_transaction_id": 1})}
    total_fin = await db.transactions.count_documents({})
    out["finance_total"] = total_fin
    out["finance_without_bank_record"] = total_fin - len(linked)
    return out


@router.get("/reconciliation")
async def recon_list(user: dict = Depends(require_admin), status: Optional[str] = None, limit: int = 300):
    q = {"status": {"$in": ["approved", "pending"]}}
    if status and status != "all":
        q["reconciliation_status"] = status
    docs = await db.bank_transactions.find(q).sort("transaction_date", -1).to_list(min(limit, 1000))
    rows = []
    for d in docs:
        row = _out(d)
        row["reconciliation"] = d.get("reconciliation") or {}
        if d.get("reconciliation_status") in (None, "unmatched", "partially_matched") and d["status"] == "approved":
            row["candidates"] = await _recon_candidates(d)
        rows.append(row)
    return rows


@router.get("/reconciliation/unmatched-finance")
async def recon_unmatched_finance(user: dict = Depends(require_admin), start_date: Optional[str] = None,
                                  end_date: Optional[str] = None, limit: int = 500):
    linked = {x["finance_transaction_id"] async for x in db.bank_transactions.find({"finance_transaction_id": {"$ne": None}},
                                                                                   {"finance_transaction_id": 1})}
    q = {}
    if start_date or end_date:
        q["date"] = {k: v for k, v in (("$gte", start_date), ("$lte", (end_date or "") + "T23:59:59")) if v and v != "T23:59:59"}
    out = []
    async for t in db.transactions.find(q).sort("date", -1).limit(5000):
        if str(t["_id"]) in linked:
            continue
        out.append({"id": str(t["_id"]), "date": t["date"][:10], "type": t["type"], "account": t["account"],
                    "project_id": t["project_id"], "amount": t["amount"], "notes": t.get("notes", ""), "source": t.get("source", "")})
        if len(out) >= limit:
            break
    return out


class ReconMatchIn(BaseModel):
    finance_transaction_id: str
    partial: bool = False
    note: str = Field("", max_length=300)


async def _bt_approved(tid: str) -> dict:
    d = await db.bank_transactions.find_one({"_id": _oid(tid)})
    if not d:
        raise HTTPException(404, "Not found")
    if d["status"] != "approved":
        raise HTTPException(400, "Only approved bank transactions can be reconciled")
    return d


@router.post("/{tid}/reconcile/match")
async def recon_match(tid: str, payload: ReconMatchIn, user: dict = Depends(require_admin)):
    d = await _bt_approved(tid)
    fin = await db.transactions.find_one({"_id": _oid(payload.finance_transaction_id)})
    if not fin:
        raise HTTPException(404, "Finance transaction not found")
    taken = await db.bank_transactions.find_one({"finance_transaction_id": payload.finance_transaction_id, "_id": {"$ne": d["_id"]}})
    if taken:
        raise HTTPException(409, "Finance transaction is already linked to another bank transaction")
    status = "partially_matched" if payload.partial or abs(float(fin["amount"]) - float(d["amount"])) >= 0.01 else "matched"
    prev = {"reconciliation_status": d.get("reconciliation_status"), "finance_transaction_id": d.get("finance_transaction_id")}
    await db.bank_transactions.update_one({"_id": d["_id"]}, {"$set": {
        "reconciliation_status": status, "finance_transaction_id": payload.finance_transaction_id,
        "reconciliation": {"method": "manual", "by": user["email"], "at": now_iso(), "note": payload.note,
                           "amount_diff": round(float(fin["amount"]) - float(d["amount"]), 2)}}})
    await audit("reconciled", user["email"], d["_id"], previous=prev, new={"reconciliation_status": status,
                                                                          "finance_transaction_id": payload.finance_transaction_id})
    return _out(await db.bank_transactions.find_one({"_id": d["_id"]}))


@router.post("/{tid}/reconcile/unmatch")
async def recon_unmatch(tid: str, user: dict = Depends(require_admin)):
    d = await _bt_approved(tid)
    prev = {"reconciliation_status": d.get("reconciliation_status"), "finance_transaction_id": d.get("finance_transaction_id")}
    await db.bank_transactions.update_one({"_id": d["_id"]}, {"$set": {
        "reconciliation_status": "unmatched", "finance_transaction_id": None,
        "unlinked_finance_transaction_id": d.get("finance_transaction_id"),
        "reconciliation": {"method": "manual_unmatch", "by": user["email"], "at": now_iso()}}})
    await audit("unreconciled", user["email"], d["_id"], previous=prev, new={"reconciliation_status": "unmatched"})
    return _out(await db.bank_transactions.find_one({"_id": d["_id"]}))


@router.post("/{tid}/reconcile/ignore")
async def recon_ignore(tid: str, user: dict = Depends(require_admin)):
    d = await _bt_approved(tid)
    await db.bank_transactions.update_one({"_id": d["_id"]}, {"$set": {
        "reconciliation_status": "ignored", "reconciliation": {"method": "ignored", "by": user["email"], "at": now_iso()}}})
    await audit("reconciliation_ignored", user["email"], d["_id"], new={"reconciliation_status": "ignored"})
    return _out(await db.bank_transactions.find_one({"_id": d["_id"]}))


@router.post("/reconciliation/auto")
async def recon_auto(user: dict = Depends(require_admin)):
    """Link-based auto match: approved bank txns whose finance link still exists → matched (legacy backfill)."""
    n_matched, n_orphan = 0, 0
    async for d in db.bank_transactions.find({"status": "approved", "reconciliation_status": {"$nin": ["matched", "ignored"]}}):
        fid = d.get("finance_transaction_id")
        fin = await db.transactions.find_one({"_id": ObjectId(fid)}) if fid and ObjectId.is_valid(fid) else None
        if fin and abs(float(fin["amount"]) - float(d["amount"])) < 0.01:
            await db.bank_transactions.update_one({"_id": d["_id"]}, {"$set": {"reconciliation_status": "matched",
                                                                               "reconciliation": {"method": "auto_link", "at": now_iso()}}})
            n_matched += 1
        elif fin:
            await db.bank_transactions.update_one({"_id": d["_id"]}, {"$set": {"reconciliation_status": "partially_matched",
                                                                               "reconciliation": {"method": "auto_link", "at": now_iso(),
                                                                                                  "amount_diff": round(float(fin["amount"]) - float(d["amount"]), 2)}}})
            n_matched += 1
        else:
            await db.bank_transactions.update_one({"_id": d["_id"]}, {"$set": {"reconciliation_status": "unmatched"}})
            n_orphan += 1
    await audit("reconciliation_auto_run", user["email"], None, new={"matched": n_matched, "orphaned": n_orphan})
    return {"matched": n_matched, "orphaned": n_orphan}


# ================= Statement PDF import =================
MAX_PDF_BYTES = 10 * 1024 * 1024
ROW_RE = re.compile(r"^(?P<date>\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{1,2}[-/ ][A-Za-z]{3}[-/ ]\d{2,4}|\d{4}-\d{2}-\d{2})\s+(?P<rest>.+)$")
AMT_TOKEN = re.compile(r"^-?[\d,]+\.\d{2}$|^-?[\d,]{4,}$")


def _pdf_lines(raw: bytes) -> List[str]:
    import pdfplumber
    lines = []
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ""
            lines.extend(ln.strip() for ln in txt.splitlines() if ln.strip())
    return lines


def parse_pdf_statement_lines(lines: List[str], bank_name: str, bank_account: str) -> List[dict]:
    """Heuristic: each row starts with a date; trailing numeric tokens = [amount, balance] or [debit, credit, balance]."""
    from bank_parsers import parse_any_date, parse_amount
    rows, buf = [], None
    for ln in lines:
        m = ROW_RE.match(ln)
        if not m:
            if buf is not None and not AMT_TOKEN.match(ln.replace(" ", "")):
                buf["narr"] += " " + ln
            continue
        if buf:
            rows.append(buf)
        buf = {"date": m.group("date"), "narr": m.group("rest")}
    if buf:
        rows.append(buf)
    out = []
    low_hint = " ".join(lines[:60]).lower()
    for i, r in enumerate(rows, 1):
        toks = r["narr"].split()
        nums = []
        while toks and AMT_TOKEN.match(toks[-1]):
            nums.insert(0, toks.pop())
        narration = " ".join(toks)
        # strip a leading value-date if present
        parts = narration.split(" ", 1)
        if parts and ROW_RE.match(parts[0] + " x") and len(parts) > 1:
            narration = parts[1]
        errors = []
        date = parse_any_date(r["date"])
        if not date:
            errors.append("unparseable date")
        amount, direction = None, None
        cr_flag = re.search(r"\b(cr|credit)\b\.?$", narration, re.IGNORECASE)
        dr_flag = re.search(r"\b(dr|debit)\b\.?$", narration, re.IGNORECASE)
        if len(nums) >= 2:
            amount = parse_amount(nums[-2])
            if nums[-2].startswith("-"):
                direction = "debit"
            elif cr_flag:
                direction = "credit"
            elif dr_flag:
                direction = "debit"
            else:
                direction = _direction_from_balance(out, nums, amount)
        elif len(nums) == 1:
            amount = parse_amount(nums[0])
            direction = "credit" if cr_flag else "debit" if dr_flag or nums[0].startswith("-") else None
        if not amount:
            errors.append("missing amount")
        if not direction:
            direction = "credit" if re.search(r"\b(neft cr|imps cr|credit|cr-|by transfer|deposit|received)\b", narration, re.IGNORECASE) else \
                "debit" if re.search(r"\b(upi|pos|atm|debit|dr-|to transfer|paid|purchase|charges|emi)\b", narration, re.IGNORECASE) else None
        if not direction:
            errors.append("direction not determinable")
        if not narration:
            errors.append("missing narration")
        ref = ""
        rm = re.search(r"\b([A-Z0-9]{10,})\b", narration)
        if rm:
            ref = rm.group(1)
        txn = {"bank_name": bank_name, "bank_account": bank_account, "transaction_date": date or "", "direction": direction or "",
               "amount": amount or 0, "narration": re.sub(r"\s+", " ", narration).strip()[:500], "bank_reference": ref,
               "source": "csv", "source_message_id": "", "source_raw_text": ln_join(r)}
        out.append({"row": i, "txn": txn, "errors": errors, "balance": parse_amount(nums[-1]) if nums else None})
    return out


def ln_join(r: dict) -> str:
    return f"{r['date']} {r['narr']}"[:4000]


def _direction_from_balance(prev_rows: list, nums: list, amount: Optional[float]) -> Optional[str]:
    from bank_parsers import parse_amount
    if not prev_rows or amount is None or len(nums) < 2:
        return None
    prev_bal = prev_rows[-1].get("balance")
    bal = parse_amount(nums[-1])
    if prev_bal is None or bal is None:
        return None
    if abs((prev_bal - amount) - bal) < 0.05:
        return "debit"
    if abs((prev_bal + amount) - bal) < 0.05:
        return "credit"
    return None


def _detect_pdf_bank(lines: List[str]) -> str:
    head = " ".join(lines[:80]).lower()
    for k, v in (("icici", "ICICI Bank"), ("hdfc", "HDFC Bank"), ("saraswat", "Saraswat Bank")):
        if k in head:
            return v
    return "Unknown Bank"


async def _pdf_preview(raw: bytes, bank_name: str, bank_account: str) -> dict:
    if len(raw) > MAX_PDF_BYTES:
        raise HTTPException(413, "PDF exceeds 10 MB")
    if not raw.startswith(b"%PDF"):
        raise HTTPException(422, "Not a PDF file")
    try:
        lines = _pdf_lines(raw)
    except Exception as e:
        raise HTTPException(422, f"Could not read PDF: {e}")
    if len(" ".join(lines)) < 40:
        raise HTTPException(422, "No extractable text — this looks like a scanned/image PDF (OCR not supported in this phase)")
    bank = bank_name or _detect_pdf_bank(lines)
    if not bank_account:
        m = re.search(r"(?:Account\s*(?:No|Number)\.?\s*:?\s*)([X\*\d ]{6,})", " ".join(lines[:80]), re.IGNORECASE)
        bank_account = re.sub(r"\s", "", m.group(1)) if m else ""
    parsed = parse_pdf_statement_lines(lines, bank, bank_account)
    if not parsed:
        raise HTTPException(422, "No transaction rows detected (expected lines starting with a date)")
    fps = set()
    for p in parsed:
        p["fingerprint"] = bank_fingerprint(p["txn"]) if not p["errors"] else None
        if p["fingerprint"] and p["fingerprint"] in fps:
            p["errors"] = ["duplicate within file"]
            p["fingerprint"] = None
        elif p["fingerprint"]:
            fps.add(p["fingerprint"])
    existing = set()
    if fps:
        async for d in db.bank_transactions.find({"fingerprint": {"$in": list(fps)}, "status": {"$ne": "duplicate"}}, {"fingerprint": 1}):
            existing.add(d["fingerprint"])
    for p in parsed:
        p["already_ingested"] = bool(p["fingerprint"] and p["fingerprint"] in existing)
    return {"bank_name": bank, "bank_account_masked": mask_account(bank_account), "total": len(parsed),
            "valid": sum(1 for p in parsed if not p["errors"]), "invalid": sum(1 for p in parsed if p["errors"]),
            "already_ingested": sum(1 for p in parsed if p["already_ingested"]), "rows": parsed, "pages_text_lines": len(lines)}


@router.post("/statement/pdf/preview")
async def pdf_preview(file: UploadFile = File(...), bank_name: str = Form(""), bank_account: str = Form(""),
                      user: dict = Depends(require_admin)):
    res = await _pdf_preview(await file.read(), bank_name, bank_account)
    res["rows"] = res["rows"][:300]
    return res


@router.post("/statement/pdf/import")
async def pdf_import(file: UploadFile = File(...), bank_name: str = Form(""), bank_account: str = Form(""),
                     user: dict = Depends(require_admin)):
    res = await _pdf_preview(await file.read(), bank_name, bank_account)
    results, skipped = [], 0
    for p in res["rows"]:
        if p["errors"]:
            continue
        if p["already_ingested"]:
            skipped += 1
            continue
        results.append(await ingest_one(BankTxnIn(**p["txn"]), user["email"]))
    await db.bank_ingestion_log.insert_one({
        "timestamp": now_iso(), "actor": user["email"], "channel": "pdf_statement", "count": len(results),
        "pending": sum(1 for r in results if r["status"] == "pending"),
        "duplicates": sum(1 for r in results if r["status"] == "duplicate"), "sources": ["csv"],
        "ids": [r["id"] for r in results], "filename": file.filename, "bank": res["bank_name"],
        "invalid": res["invalid"], "skipped_already_ingested": skipped})
    return {"bank_name": res["bank_name"], "total": res["total"], "ingested": len(results), "invalid": res["invalid"],
            "skipped_already_ingested": skipped, "pending": sum(1 for r in results if r["status"] == "pending"),
            "duplicates": sum(1 for r in results if r["status"] == "duplicate"), "results": results}


async def ensure_phase2_indexes():
    await db.bank_queue_messages.create_index("source_message_id")
    await db.bank_queue_messages.create_index([("parsing_status", 1), ("created_at", -1)])
    await db.bank_transactions.create_index("reconciliation_status")
