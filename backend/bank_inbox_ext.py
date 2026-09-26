"""Phase-2 bank inbox extensions: statement CSV import, email alert parsing templates, bulk approve, PA guide."""
import os
import re
import csv
import io
import json
from datetime import datetime
from typing import Optional, List

from bson import ObjectId
from fastapi import HTTPException, Depends, UploadFile, File, Form, Request
from pydantic import BaseModel, Field

from server import db, require_admin
from bank_inbox import (router, BankTxnIn, ingest_one, require_ingest_key, now_iso, audit, _oid, _pending_or_400,
                        bank_fingerprint, MAX_BATCH)

DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d-%b-%Y", "%d-%b-%y", "%d/%m/%y", "%d-%m-%y", "%d %b %Y",
                "%d %b %y", "%d/%b/%Y", "%d/%b/%y", "%Y/%m/%d", "%d.%m.%Y", "%d.%m.%y", "%b %d, %Y", "%d %B %Y")


def parse_any_date(v: str) -> Optional[str]:
    v = (v or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(v, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse_amount(v) -> Optional[float]:
    s = re.sub(r"[^\d.\-]", "", str(v or ""))
    if not s or s in ("-", "."):
        return None
    try:
        return abs(float(s))
    except ValueError:
        return None


# ================= Statement CSV =================
COLUMN_ALIASES = {
    "date": ["transaction date", "txn date", "tran date", "value date", "date", "txn posted date", "transaction_date"],
    "narration": ["narration", "description", "particulars", "remarks", "transaction remarks", "details", "transaction description"],
    "debit": ["withdrawal amt", "withdrawal amount", "withdrawal amt.", "debit", "debit amount", "withdrawal", "dr", "withdrawals"],
    "credit": ["deposit amt", "deposit amount", "deposit amt.", "credit", "credit amount", "deposit", "cr", "deposits"],
    "amount": ["amount", "transaction amount", "txn amount", "amount (inr)"],
    "direction": ["dr/cr", "cr/dr", "type", "transaction type", "dr / cr"],
    "reference": ["chq/ref no", "chq./ref.no.", "ref no", "ref no./cheque no.", "reference", "cheque no", "chq no",
                  "utr", "utr no", "transaction id", "tran id", "ref/cheque no", "cheque/ref no"],
}
BANK_HINTS = {"ICICI Bank": ["value date", "transaction remarks", "withdrawal amount (inr", "deposit amount (inr"],
              "HDFC Bank": ["chq./ref.no.", "withdrawal amt.", "deposit amt.", "closing balance"],
              "Saraswat Bank": ["dr amount", "cr amount", "total amount", "particulars", "instruments"]}


def _norm_header(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "").strip().lower().replace("_", " "))


def detect_mapping(headers: List[str]) -> dict:
    normed = [_norm_header(h) for h in headers]
    mapping = {}
    for field, aliases in COLUMN_ALIASES.items():
        for a in aliases:
            hit = next((i for i, h in enumerate(normed) if h == a or h.startswith(a + " (") or h.startswith(a + "(")), None)
            if hit is not None:
                mapping[field] = headers[hit]
                break
        if field not in mapping:
            for a in aliases:
                hit = next((i for i, h in enumerate(normed) if a in h and len(a) > 3), None)
                if hit is not None:
                    mapping[field] = headers[hit]
                    break
    if "amount" in mapping and mapping["amount"] in (mapping.get("debit"), mapping.get("credit")):
        mapping.pop("amount")
    return mapping


def detect_bank(headers: List[str]) -> Optional[str]:
    joined = " | ".join(_norm_header(h) for h in headers)
    scores = {b: sum(1 for k in ks if k in joined) for b, ks in BANK_HINTS.items()}
    best = max(scores.items(), key=lambda kv: kv[1])
    return best[0] if best[1] >= 2 else None


def read_statement(raw: bytes) -> tuple:
    """Return (headers, rows[dict]). Skips preamble lines before the real header row."""
    text = raw.decode("utf-8-sig", errors="replace")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    reader_rows = list(csv.reader(lines))
    hdr_idx = None
    from bank_parsers.statement import HEADER_ALIASES, normalize_header
    for i, row in enumerate(reader_rows[:40]):
        normed = [normalize_header(c) for c in row]
        has_date = any(any(a == h or a in h for a in HEADER_ALIASES["date"]) for h in normed)
        has_nar = any(any(a == h or a in h for a in HEADER_ALIASES["narration"]) for h in normed)
        if has_date and has_nar and len([c for c in row if c.strip()]) >= 3:
            hdr_idx = i
            break
    if hdr_idx is None:
        raise HTTPException(422, "Could not find a header row with date + narration columns")
    headers = [h.strip() for h in reader_rows[hdr_idx]]
    rows = []
    for row in reader_rows[hdr_idx + 1:]:
        if not any(c.strip() for c in row):
            continue
        rows.append({headers[i]: (row[i].strip() if i < len(row) else "") for i in range(len(headers)) if headers[i]})
    return headers, rows


def row_to_txn(row: dict, mapping: dict, bank_name: str, bank_account: str, idx: int) -> tuple:
    errors = []
    date = parse_any_date(row.get(mapping.get("date", ""), ""))
    if not date:
        errors.append("unparseable date")
    narration = row.get(mapping.get("narration", ""), "").strip()
    if not narration:
        errors.append("missing narration")
    amount, direction = None, None
    if mapping.get("debit") or mapping.get("credit"):
        d_amt = parse_amount(row.get(mapping.get("debit", ""), ""))
        c_amt = parse_amount(row.get(mapping.get("credit", ""), ""))
        if d_amt and d_amt > 0:
            amount, direction = d_amt, "debit"
        elif c_amt and c_amt > 0:
            amount, direction = c_amt, "credit"
    if amount is None and mapping.get("amount"):
        amount = parse_amount(row.get(mapping["amount"], ""))
        dv = row.get(mapping.get("direction", ""), "").strip().lower()
        raw_amt = str(row.get(mapping["amount"], ""))
        if dv.startswith(("dr", "debit", "withdraw")) or raw_amt.strip().startswith("-"):
            direction = "debit"
        elif dv.startswith(("cr", "credit", "deposit")):
            direction = "credit"
    if not amount or amount <= 0:
        errors.append("missing/zero amount")
    if not direction:
        errors.append("direction not determinable")
    ref = row.get(mapping.get("reference", ""), "").strip()
    txn = {"bank_name": bank_name, "bank_account": bank_account or "", "transaction_date": date or "",
           "direction": direction or "", "amount": amount or 0, "narration": narration, "bank_reference": ref,
           "source": "csv", "source_message_id": "", "source_raw_text": json.dumps(row)[:4000]}
    return txn, errors


async def _preview_rows(raw: bytes, bank_name: str, bank_account: str, mapping_json: str) -> dict:
    from bank_parsers.statement import (detect_mapping as st_detect, normalize_row, is_total_row, totals_report,
                                        extract_statement_totals)
    headers, rows = read_statement(raw)
    mapping = json.loads(mapping_json) if mapping_json else {}
    mapping = {k: v for k, v in mapping.items() if v}
    mapping = _legacy_mapping_keys(mapping) if mapping else st_detect(headers)
    bank = bank_name or detect_bank(headers) or "Unknown Bank"
    statement_totals = extract_statement_totals(rows, mapping)
    parsed, fps = [], set()
    for i, r in enumerate(rows):
        if is_total_row(r, mapping):
            continue
        p = normalize_row(r, mapping, bank, bank_account, parse_any_date)
        p["row"] = i + 1
        fp = bank_fingerprint(p["txn"]) if not p["errors"] else None
        if fp and fp in fps:
            p["errors"], p["needs_review"], fp = ["duplicate within file"], True, None
        if fp:
            fps.add(fp)
        p["fingerprint"] = fp
        parsed.append(p)
    existing = set()
    if fps:
        async for d in db.bank_transactions.find({"fingerprint": {"$in": list(fps)}, "status": {"$ne": "duplicate"}}, {"fingerprint": 1}):
            existing.add(d["fingerprint"])
    for p in parsed:
        p["already_ingested"] = bool(p["fingerprint"] and p["fingerprint"] in existing)
    return {"headers": headers, "mapping": mapping, "bank_name": bank, "total": len(parsed),
            "valid": sum(1 for p in parsed if not p["errors"]), "invalid": sum(1 for p in parsed if p["errors"]),
            "needs_review": sum(1 for p in parsed if p["needs_review"]),
            "already_ingested": sum(1 for p in parsed if p["already_ingested"]),
            "totals": totals_report(parsed, statement_totals), "rows": parsed}


_LEGACY_KEYS = {"debit": "debit_amount", "credit": "credit_amount", "reference": "bank_reference"}


def _legacy_mapping_keys(m: dict) -> dict:
    return {_LEGACY_KEYS.get(k, k): v for k, v in m.items()}


MAX_STATEMENT_BYTES = 5 * 1024 * 1024


async def _read_upload(file: UploadFile) -> bytes:
    raw = await file.read()
    if len(raw) > MAX_STATEMENT_BYTES:
        raise HTTPException(413, "Statement file exceeds 5 MB")
    if not raw.strip():
        raise HTTPException(422, "Empty file")
    return raw


@router.post("/statement/preview")
async def statement_preview(file: UploadFile = File(...), bank_name: str = Form(""), bank_account: str = Form(""),
                            mapping: str = Form(""), user: dict = Depends(require_admin)):
    raw = await _read_upload(file)
    res = await _preview_rows(raw, bank_name, bank_account, mapping)
    res["rows"] = res["rows"][:300]
    return res


@router.post("/statement/import")
async def statement_import(file: UploadFile = File(...), bank_name: str = Form(""), bank_account: str = Form(""),
                           mapping: str = Form(""), skip_ingested: str = Form("true"),
                           user: dict = Depends(require_admin)):
    raw = await _read_upload(file)
    res = await _preview_rows(raw, bank_name, bank_account, mapping)
    skip = skip_ingested.lower() == "true"
    results, skipped = [], 0
    for p in res["rows"]:
        if p["errors"]:
            continue
        if skip and p["already_ingested"]:
            skipped += 1
            continue
        results.append(await ingest_one(BankTxnIn(**p["txn"]), user["email"]))
    await db.bank_ingestion_log.insert_one({
        "timestamp": now_iso(), "actor": user["email"], "channel": "csv_statement", "count": len(results),
        "pending": sum(1 for r in results if r["status"] == "pending"),
        "duplicates": sum(1 for r in results if r["status"] == "duplicate"), "sources": ["csv"],
        "ids": [r["id"] for r in results], "filename": file.filename, "bank": res["bank_name"],
        "invalid": res["invalid"], "skipped_already_ingested": skipped})
    return {"bank_name": res["bank_name"], "total": res["total"], "ingested": len(results), "invalid": res["invalid"],
            "skipped_already_ingested": skipped,
            "pending": sum(1 for r in results if r["status"] == "pending"),
            "duplicates": sum(1 for r in results if r["status"] == "duplicate"), "results": results}


# ================= Email parsing templates =================
DEFAULT_TEMPLATES = [
    {"bank_name": "ICICI Bank", "name": "ICICI debit/credit alert", "enabled": True, "priority": 10,
     "patterns": {
         "amount": r"(?:INR|Rs\.?)\s*([\d,]+\.?\d*)",
         "debit": r"\b(debited|spent|paid|withdrawn)\b",
         "credit": r"\b(credited|received|deposited)\b",
         "date": r"\bon\s+(\d{1,2}[-/ ][A-Za-z]{3}[-/ ]\d{2,4}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
         "narration": r"(?:Info:|Information:|towards|for|to)\s*([^\.\n]+?)(?:\.\s|\n|The\s|Avl|Available|$)",
         "reference": r"(?:Ref(?:erence)?(?:\s*No)?\.?\s*:?\s*|UTR\s*:?\s*)([A-Za-z0-9]{6,})",
         "account": r"(?:Account|A/c|Acct)\s*(?:No\.?\s*)?(?:XX|\*+)?(\d{3,6})"},
     "sample": "Dear Customer, Your Account XX2345 has been debited with INR 4,499.13 on 12-May-26. Info: MICROSOFT SUBSCRIPTION E080105RXG. The Available Balance is INR 1,20,000.00. Ref No: ICI123456789"},
    {"bank_name": "HDFC Bank", "name": "HDFC UPI/NEFT alert", "enabled": True, "priority": 10,
     "patterns": {
         "amount": r"(?:Rs\.?|INR)\s*([\d,]+\.?\d*)",
         "debit": r"\b(debited|has been debited|spent)\b",
         "credit": r"\b(credited|has been credited|deposited)\b",
         "date": r"\bon\s+(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{1,2}[-/ ][A-Za-z]{3}[-/ ]\d{2,4})",
         "narration": r"(?:\bto\s+(?!VPA\s*$)|towards\s+|\bby\s+|\bfor\s+|from\s+(?!a/c|A/c|account))([^\.\n]+?)(?:\s*\(|\.\s|\.$|\n|$)",
         "reference": r"(?:UPI\s*Ref(?:erence)?\s*No\.?\s*:?\s*|Ref(?:erence)?\s*(?:No)?\.?\s*:?\s*|UTR\s*:?\s*)([A-Za-z0-9]{6,})",
         "account": r"(?:a/c|A/c|Account)\s*(?:No\.?\s*)?(?:\*+|XX|x+)?(\d{3,6})"},
     "sample": "Rs.15222.00 debited from a/c **6789 on 25-09-26 to LEI CODE REGISTRATION SERVICES (UPI Ref No 526812345678). Not you? Call 18002586161."},
    {"bank_name": "Saraswat Bank", "name": "Saraswat generic alert", "enabled": True, "priority": 10,
     "patterns": {
         "amount": r"(?:Rs\.?|INR)\s*([\d,]+\.?\d*)",
         "debit": r"\b(debited|withdrawn|Dr)\b",
         "credit": r"\b(credited|deposited|Cr)\b",
         "date": r"\bon\s+(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{1,2}[-/ ][A-Za-z]{3}[-/ ]\d{2,4})",
         "narration": r"(?:for|towards|Info:|Desc:|Description:)\s*([^\.\n]+?)(?:\.\s|\n|$)",
         "reference": r"(?:Ref(?:erence)?\s*(?:No)?\.?\s*:?\s*|UTR\s*:?\s*|Txn\s*ID\s*:?\s*)([A-Za-z0-9]{6,})",
         "account": r"(?:A/c|Account)\s*(?:No\.?\s*)?(?:XX|\*+)?(\d{3,6})"},
     "sample": "Your A/c XX4321 is debited with Rs. 2500.00 on 10-06-2026 for NEFT TO ABC SUPPLIERS. Ref No: SRS998877. Avl Bal Rs. 50000.00"},
]
PATTERN_KEYS = ["amount", "debit", "credit", "date", "narration", "reference", "account"]


class TemplateIn(BaseModel):
    bank_name: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=120)
    enabled: bool = True
    priority: int = 10
    patterns: dict
    sample: str = Field("", max_length=4000)


class TemplateTestIn(BaseModel):
    raw_text: str = Field(..., min_length=1, max_length=8000)
    patterns: Optional[dict] = None
    template_id: Optional[str] = None
    bank_name: Optional[str] = None


class EmailIngestIn(BaseModel):
    bank_name: Optional[str] = Field(None, max_length=100)
    raw_text: str = Field(..., min_length=5, max_length=8000)
    source: str = Field("power_automate", max_length=30)
    source_message_id: str = Field("", max_length=200)
    subject: str = Field("", max_length=300)
    received_at: str = Field("", max_length=40)


class BulkApproveIn(BaseModel):
    ids: List[str] = Field(..., min_length=1, max_length=MAX_BATCH)


def _validate_patterns(p: dict):
    for k in PATTERN_KEYS:
        v = p.get(k, "")
        if not isinstance(v, str):
            raise HTTPException(422, f"pattern '{k}' must be a string")
        if v:
            try:
                re.compile(v, re.IGNORECASE)
            except re.error as e:
                raise HTTPException(422, f"Invalid regex for '{k}': {e}")
    if not p.get("amount"):
        raise HTTPException(422, "'amount' pattern is required")


def _first(pattern: str, text: str) -> Optional[str]:
    if not pattern:
        return None
    m = re.search(pattern, text, re.IGNORECASE)
    if not m:
        return None
    return (m.group(1) if m.groups() else m.group(0)).strip()


def apply_template(patterns: dict, text: str, bank_name: str) -> dict:
    text = re.sub(r"\s+", " ", text or "").strip()
    fields, errors = {}, []
    amt = parse_amount(_first(patterns.get("amount"), text))
    if not amt:
        errors.append("amount not found")
    is_debit = bool(_first(patterns.get("debit"), text))
    is_credit = bool(_first(patterns.get("credit"), text))
    direction = "debit" if is_debit and not is_credit else "credit" if is_credit and not is_debit else None
    if direction is None and is_debit and is_credit:
        dpos = re.search(patterns["debit"], text, re.IGNORECASE).start()
        cpos = re.search(patterns["credit"], text, re.IGNORECASE).start()
        direction = "debit" if dpos < cpos else "credit"
    if not direction:
        errors.append("direction not found")
    raw_date = _first(patterns.get("date"), text)
    date = parse_any_date(raw_date) if raw_date else None
    if not date:
        errors.append("date not found/unparseable")
    narration = _first(patterns.get("narration"), text) or ""
    if not narration:
        errors.append("narration not found")
    fields.update({"bank_name": bank_name, "amount": amt or 0, "direction": direction or "", "transaction_date": date or "",
                   "narration": narration[:500], "bank_reference": _first(patterns.get("reference"), text) or "",
                   "bank_account": _first(patterns.get("account"), text) or ""})
    return {"fields": fields, "errors": errors}


def _tpl_out(d: dict) -> dict:
    return {"id": str(d["_id"]), "bank_name": d["bank_name"], "name": d["name"], "enabled": d.get("enabled", True),
            "priority": d.get("priority", 10), "patterns": d.get("patterns", {}), "sample": d.get("sample", ""),
            "is_default": d.get("is_default", False), "uses": d.get("uses", 0), "updated_at": d.get("updated_at")}


async def seed_templates():
    if await db.bank_parse_templates.count_documents({}) == 0:
        for t in DEFAULT_TEMPLATES:
            await db.bank_parse_templates.insert_one({**t, "is_default": True, "uses": 0, "created_at": now_iso(),
                                                      "updated_at": now_iso()})


@router.get("/templates")
async def list_templates(user: dict = Depends(require_admin)):
    docs = await db.bank_parse_templates.find({}).sort([("bank_name", 1), ("priority", 1)]).to_list(200)
    return [_tpl_out(d) for d in docs]


@router.post("/templates")
async def create_template(payload: TemplateIn, user: dict = Depends(require_admin)):
    _validate_patterns(payload.patterns)
    doc = {**payload.model_dump(), "is_default": False, "uses": 0, "created_at": now_iso(), "updated_at": now_iso(),
           "created_by": user["email"]}
    r = await db.bank_parse_templates.insert_one(doc)
    return _tpl_out({**doc, "_id": r.inserted_id})


@router.put("/templates/{tid}")
async def update_template(tid: str, payload: TemplateIn, user: dict = Depends(require_admin)):
    _validate_patterns(payload.patterns)
    oid = _oid(tid)
    prev = await db.bank_parse_templates.find_one({"_id": oid})
    if not prev:
        raise HTTPException(404, "Template not found")
    await db.bank_parse_templates.update_one({"_id": oid}, {"$set": {**payload.model_dump(), "updated_at": now_iso(),
                                                                     "updated_by": user["email"]}})
    await audit("template_edited", user["email"], None, previous=_tpl_out(prev), new=payload.model_dump(), extra={"template_id": tid})
    return _tpl_out(await db.bank_parse_templates.find_one({"_id": oid}))


@router.delete("/templates/{tid}")
async def delete_template(tid: str, user: dict = Depends(require_admin)):
    r = await db.bank_parse_templates.delete_one({"_id": _oid(tid)})
    if r.deleted_count == 0:
        raise HTTPException(404, "Template not found")
    return {"ok": True}


@router.post("/templates/test")
async def test_template(payload: TemplateTestIn, user: dict = Depends(require_admin)):
    if payload.patterns:
        _validate_patterns(payload.patterns)
        return apply_template(payload.patterns, payload.raw_text, payload.bank_name or "Unknown Bank")
    if payload.template_id:
        t = await db.bank_parse_templates.find_one({"_id": _oid(payload.template_id)})
        if not t:
            raise HTTPException(404, "Template not found")
        return apply_template(t["patterns"], payload.raw_text, t["bank_name"])
    res = await parse_with_templates(payload.raw_text, payload.bank_name)
    return res


async def parse_with_templates(text: str, bank_name: Optional[str]) -> dict:
    q = {"enabled": True}
    if bank_name:
        q["bank_name"] = {"$regex": f"^{re.escape(bank_name.strip())}$", "$options": "i"}
    tpls = await db.bank_parse_templates.find(q).sort("priority", 1).to_list(100)
    if not tpls and bank_name:
        tpls = await db.bank_parse_templates.find({"enabled": True}).sort("priority", 1).to_list(100)
    best = None
    for t in tpls:
        r = apply_template(t["patterns"], text, bank_name or t["bank_name"])
        r["template_id"], r["template_name"] = str(t["_id"]), t["name"]
        if not r["errors"]:
            return r
        if best is None or len(r["errors"]) < len(best["errors"]):
            best = r
    return best or {"fields": {}, "errors": ["no enabled templates"], "template_id": None, "template_name": None}


@router.post("/ingest/email")
async def ingest_email(payload: EmailIngestIn, actor: str = Depends(require_ingest_key)):
    parsed = await parse_with_templates(payload.raw_text, payload.bank_name)
    log = {"timestamp": now_iso(), "actor": actor, "channel": "email_alert", "sources": [payload.source],
           "bank": payload.bank_name, "template": parsed.get("template_name"), "subject": payload.subject[:120]}
    if parsed["errors"]:
        await db.bank_ingestion_log.insert_one({**log, "count": 0, "pending": 0, "duplicates": 0,
                                                "failed": 1, "errors": parsed["errors"], "ids": []})
        raise HTTPException(422, {"message": "Could not parse alert", "errors": parsed["errors"],
                                  "partial": parsed["fields"], "template": parsed.get("template_name")})
    f = parsed["fields"]
    txn = BankTxnIn(**{**f, "source": payload.source, "source_message_id": payload.source_message_id,
                       "source_raw_text": payload.raw_text[:4000]})
    r = await ingest_one(txn, actor)
    if parsed.get("template_id"):
        await db.bank_parse_templates.update_one({"_id": ObjectId(parsed["template_id"])}, {"$inc": {"uses": 1}})
    await db.bank_ingestion_log.insert_one({**log, "count": 1, "pending": 1 if r["status"] == "pending" else 0,
                                            "duplicates": 1 if r["status"] == "duplicate" else 0, "ids": [r["id"]]})
    return {"parsed": f, "template": parsed.get("template_name"), "transaction": r}


@router.get("/guide")
async def power_automate_guide(request: Request, user: dict = Depends(require_admin)):
    base = os.environ.get("PUBLIC_API_BASE_URL") or str(request.base_url).rstrip("/")
    return {
        "header_name": "X-Ingest-Key",
        "key_env_var": "BANK_INGEST_API_KEY",
        "email_endpoint": f"{base}/api/bank-transactions/ingest/email",
        "structured_endpoint": f"{base}/api/bank-transactions/ingest",
        "steps": [
            "Power Automate → Create → Automated cloud flow → trigger 'When a new email arrives (V3)' (Office 365 Outlook).",
            "Set Folder = Inbox (or a 'Bank Alerts' rule folder); From = your bank alert sender(s); Include Attachments = No.",
            "Add action 'Html to text' (Content Conversion) with Body = triggerOutputs()?['body/body'].",
            "Add action 'HTTP': Method POST, URI = email_endpoint below, Headers: Content-Type: application/json, X-Ingest-Key: <key from server .env>.",
            "Body (JSON): { \"bank_name\": \"ICICI Bank\", \"raw_text\": @{body('Html_to_text')}, \"source\": \"power_automate\", \"source_message_id\": @{triggerOutputs()?['body/id']}, \"subject\": @{triggerOutputs()?['body/subject']} }",
            "Optional: add a Condition on the HTTP status code — on 422 (unparseable) forward the email to finance for manual entry.",
            "Save, then send a test alert; check Bank Transactions → Ingestion History for the 'email_alert' row.",
            "For SharePoint queue: use trigger 'When an item is created' and map list columns to the structured endpoint body instead.",
        ],
        "email_body_example": {"bank_name": "ICICI Bank", "raw_text": DEFAULT_TEMPLATES[0]["sample"],
                               "source": "power_automate", "source_message_id": "AAMkAGI2...", "subject": "Transaction alert"},
        "structured_body_example": {"transactions": [{"bank_name": "HDFC Bank", "bank_account": "XXXX6789",
                                                       "transaction_date": "2026-09-25", "direction": "debit",
                                                       "amount": 15222.0, "narration": "LEI CODE REGISTRATION",
                                                       "bank_reference": "526812345678", "source": "sharepoint",
                                                       "source_message_id": "sp-item-42"}]},
        "notes": ["Endpoint is idempotent on (source, source_message_id) and on bank fingerprint — safe to retry.",
                  "Never put the key in the frontend; keep it in the Power Automate HTTP action (or a Key Vault reference).",
                  "Use HTTPS only; the on-prem URL is https://finance.rudaya.local:9443 — Power Automate needs an on-premises data gateway or a public reverse proxy to reach it."],
    }


# ================= Bulk approve =================
@router.post("/bulk-approve")
async def bulk_approve(payload: BulkApproveIn, user: dict = Depends(require_admin)):
    from bank_inbox import _approve_pending_doc
    results = []
    for tid in payload.ids:
        try:
            d = await _pending_or_400(tid)
            r = await _approve_pending_doc(d, tid, user)
            results.append({"id": tid, "ok": True, "finance_transaction_id": r["finance_transaction_id"],
                            "narration": d["narration"], "amount": d["amount"]})
        except HTTPException as e:
            results.append({"id": tid, "ok": False, "error": e.detail if isinstance(e.detail, str) else str(e.detail)})
    ok = sum(1 for r in results if r["ok"])
    await audit("bulk_approved", user["email"], None, new={"requested": len(payload.ids), "approved": ok})
    return {"requested": len(payload.ids), "approved": ok, "failed": len(results) - ok, "results": results}
