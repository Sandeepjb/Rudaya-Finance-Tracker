"""Bank Transaction Inbox: ingestion, duplicate detection, 3-layer classification, human approval, learning."""
import os
import re
import json
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional, List

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Depends, Header, Query
from pydantic import BaseModel, Field

from server import (db, get_current_user, require_admin, TransactionIn, insert_finance_transaction,
                    _parse_import_date, EMERGENT_LLM_KEY, AI_MODEL, LlmChat, UserMessage)

logger = logging.getLogger("bank_inbox")
router = APIRouter(prefix="/api/bank-transactions")

SOURCES = {"manual", "email", "power_automate", "sharepoint", "bank_api", "csv"}
STATUSES = {"pending", "approved", "rejected", "duplicate"}
DIRECTIONS = {"debit", "credit"}
TYPES = {"Revenue", "Cost", "Expense"}
AI_THRESHOLD = 70
MAX_BATCH = 100

STOPWORDS = {"UPI", "NEFT", "IMPS", "RTGS", "ACH", "PAYMENT", "PAYMENTS", "PAY", "TXN", "TRF", "TRANSFER", "REF",
             "TO", "FROM", "BY", "FOR", "THE", "AND", "OF", "INB", "BIL", "ATM", "POS", "DR", "CR", "DEBIT", "CREDIT",
             "PVT", "LTD", "LIMITED", "PRIVATE", "INDIA", "INR", "RS", "BANK", "ONLINE", "MOBILE", "NET", "CHQ",
             "CHEQUE", "DEP", "WDL", "ECS", "NACH", "MMT", "VIA", "PURCHASE", "CARD", "CHARGES", "AUTO"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- normalisation ----------
def normalize_narration(text: str) -> str:
    s = (text or "").upper()
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    toks = [t for t in s.split() if not (any(c.isdigit() for c in t) and len(t) >= 4)]
    toks = [t for t in toks if not t.isdigit()]
    return " ".join(toks)


def keywords(text: str) -> set:
    return {t for t in normalize_narration(text).split() if len(t) >= 3 and t not in STOPWORDS}


def merchant_key(narration: str, merchant_name: Optional[str]) -> str:
    if merchant_name and merchant_name.strip():
        kw = [t for t in normalize_narration(merchant_name).split() if t not in STOPWORDS]
        if kw:
            return " ".join(kw[:2])
    kw = [t for t in normalize_narration(narration).split() if t not in STOPWORDS and len(t) >= 3]
    return " ".join(kw[:2])


def mask_account(acct: Optional[str]) -> str:
    a = (acct or "").strip()
    if not a:
        return ""
    return ("X" * max(2, len(a) - 4)) + a[-4:] if len(a) >= 4 else "X" * len(a)


def bank_fingerprint(d: dict) -> str:
    ref = (d.get("utr_reference") or d.get("bank_reference") or "").strip().upper()
    acct = (d.get("bank_account") or "").strip()[-4:]
    bank = (d.get("bank_name") or "").strip().upper()
    amt = f"{float(d.get('amount') or 0):.2f}"
    if ref:
        raw = "|".join(["REF", bank, acct, ref, amt, d.get("direction", "")])
    else:
        raw = "|".join(["NAR", bank, acct, d.get("transaction_date", ""), amt, d.get("direction", ""),
                        re.sub(r"\s+", " ", (d.get("narration") or "").upper().strip())])
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------- models ----------
class BankTxnIn(BaseModel):
    bank_name: str = Field(..., min_length=1, max_length=100)
    bank_account: str = Field("", max_length=40)
    transaction_date: str = Field(..., max_length=20)
    transaction_time: str = Field("", max_length=10)
    direction: str = Field(..., max_length=10)
    amount: float
    currency: str = Field("INR", max_length=5)
    narration: str = Field(..., min_length=1, max_length=500)
    merchant_name: Optional[str] = Field(None, max_length=120)
    bank_reference: str = Field("", max_length=80)
    utr_reference: str = Field("", max_length=80)
    source: str = Field("manual", max_length=30)
    source_message_id: str = Field("", max_length=200)
    source_raw_text: str = Field("", max_length=4000)


class IngestBatchIn(BaseModel):
    transactions: List[BankTxnIn] = Field(..., min_length=1, max_length=MAX_BATCH)


class EditIn(BaseModel):
    type: str
    account: str
    project_id: str
    amount: float
    date: str
    notes: str = ""


class RejectIn(BaseModel):
    reason: str = Field("", max_length=500)


class RuleUpdateIn(BaseModel):
    type: Optional[str] = None
    account: Optional[str] = None
    project_id: Optional[str] = None
    enabled: Optional[bool] = None


def _validate_payload(p: BankTxnIn) -> dict:
    d = p.model_dump()
    d["direction"] = d["direction"].strip().lower()
    if d["direction"] not in DIRECTIONS:
        raise HTTPException(422, "direction must be 'debit' or 'credit'")
    if not d["amount"] or d["amount"] <= 0:
        raise HTTPException(422, "amount must be greater than 0")
    iso = _parse_import_date(d["transaction_date"])
    if not iso:
        raise HTTPException(422, "transaction_date must be YYYY-MM-DD, DD/MM/YYYY or DD-MM-YYYY")
    d["transaction_date"] = iso
    d["source"] = (d["source"] or "manual").strip().lower()
    if d["source"] not in SOURCES:
        raise HTTPException(422, f"source must be one of {sorted(SOURCES)}")
    d["narration"] = d["narration"].strip()
    d["bank_name"] = d["bank_name"].strip()
    return d


# ---------- audit ----------
async def audit(action: str, actor: str, txn_id, previous=None, new=None, extra=None):
    await db.bank_audit_log.insert_one({
        "timestamp": now_iso(), "actor": actor, "action": action,
        "bank_transaction_id": str(txn_id) if txn_id else None,
        "previous": previous, "new": new, **(extra or {}),
    })


# ---------- historical intelligence ----------
def _similarity(kw: set, amount: float, merchant: str, t: dict) -> float:
    tkw = keywords((t.get("notes") or "") + " " + (t.get("account") or ""))
    if not kw or not tkw:
        tok = 0.0
    else:
        tok = len(kw & tkw) / min(len(kw), len(tkw))
    ta = float(t.get("amount") or 0)
    amt = 1 - abs(ta - amount) / max(ta, amount) if max(ta, amount) > 0 else 0
    mtoks = set(merchant.split()) if merchant else set()
    mer = len(mtoks & tkw) / len(mtoks) if mtoks else 0.0
    return round(0.6 * tok + 0.2 * amt + 0.2 * mer, 4)


async def historical_matches(d: dict, limit: int = 10) -> list:
    kw = keywords(d["narration"] + " " + (d.get("merchant_name") or ""))
    mer = merchant_key(d["narration"], d.get("merchant_name"))
    if not kw:
        return []
    regex = "|".join(re.escape(k) for k in sorted(kw))
    q = {"$or": [{"notes": {"$regex": regex, "$options": "i"}},
                 {"account": {"$regex": regex, "$options": "i"}}]}
    cands = await db.transactions.find(q).sort("date", -1).to_list(2000)
    scored = []
    for t in cands:
        s = _similarity(kw, float(d["amount"]), mer, t)
        if s >= 0.15:
            scored.append({"id": str(t["_id"]), "date": (t.get("date") or "")[:10], "type": t.get("type"),
                           "account": t.get("account"), "project_id": t.get("project_id"),
                           "amount": t.get("amount"), "notes": t.get("notes", ""), "similarity": s,
                           "source": t.get("source", "")})
    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:limit]


def _vote(matches: list) -> tuple:
    weights, total = {}, 0.0
    for m in matches:
        key = (m["type"], m["account"], m["project_id"])
        w = m["similarity"] * (1.3 if m.get("source") == "bank_transaction" else 1.0)
        weights[key] = weights.get(key, 0) + w
        total += w
    if not weights:
        return None, 0.0
    best = max(weights.items(), key=lambda kv: kv[1])
    return best[0], (best[1] / total if total else 0)


def rule_confidence(rule: dict) -> int:
    return int(max(30, min(97, 50 + 12 * rule.get("uses", 0) - 6 * rule.get("corrections", 0))))


async def classify(d: dict, actor: str) -> dict:
    """Returns suggestion dict with type/account/project_id/notes/confidence/source/reasons + matches."""
    matches = await historical_matches(d)
    mer = merchant_key(d["narration"], d.get("merchant_name"))
    reasons, suggestion = [], None

    # Layer 1: learned rule
    rule = await db.bank_mapping_rules.find_one({"pattern": mer, "enabled": True}) if mer else None
    if rule:
        conf = rule_confidence(rule)
        if conf >= AI_THRESHOLD:
            m = rule["mapping"]
            reasons.append(f"Learned mapping rule '{mer}' approved {rule.get('uses', 0)} time(s)"
                           + (f" with {rule['corrections']} correction(s)" if rule.get("corrections") else ""))
            suggestion = {"type": m["type"], "account": m["account"], "project_id": m["project_id"],
                          "confidence": conf, "source": "mapping_rule", "rule_id": str(rule["_id"])}
        else:
            reasons.append(f"Learned rule '{mer}' exists but confidence {conf}% is below threshold")

    # Layer 2: historical similarity
    if suggestion is None and matches:
        best, consensus = _vote(matches)
        top = matches[0]["similarity"]
        conf = int(round(min(96, top * 70 + consensus * 30)))
        n_same = sum(1 for m in matches if (m["type"], m["account"], m["project_id"]) == best)
        reasons.append(f"{len(matches)} historically approved transaction(s) have similar narration")
        reasons.append(f"{n_same} of the {len(matches)} closest matches mapped to {best[1]} / {best[2]} ({best[0]})")
        if any(abs(float(m['amount'] or 0) - float(d['amount'])) < 0.01 for m in matches):
            reasons.append("Exact amount match found in history")
        suggestion = {"type": best[0], "account": best[1], "project_id": best[2], "confidence": conf,
                      "source": "historical"}

    # Layer 3: AI fallback
    if (suggestion is None or suggestion["confidence"] < AI_THRESHOLD) and EMERGENT_LLM_KEY:
        ai = await _ai_classify(d, matches, suggestion)
        if ai:
            reasons.append("AI-assisted classification: " + ai.get("reason", ""))
            if suggestion and ai["confidence"] <= suggestion["confidence"]:
                reasons.append("Historical suggestion retained (AI confidence not higher)")
            else:
                suggestion = ai

    if suggestion is None:
        reasons.append("No historical matches or learned rules found — manual classification required")
        suggestion = {"type": None, "account": None, "project_id": None, "confidence": 0, "source": "none"}

    suggestion["notes"] = d["narration"]
    suggestion["reasons"] = reasons
    suggestion["merchant_key"] = mer
    suggestion["direction_note"] = "Debit/credit direction was used only as a weak signal, not as the type decision"
    return {"suggestion": suggestion, "matches": matches}


async def _ai_classify(d: dict, matches: list, prior: Optional[dict]) -> Optional[dict]:
    accounts = [a["name"] for a in await db.accounts.find({}, {"_id": 0}).to_list(500)]
    projects = [p["code"] for p in await db.project_ids.find({}, {"_id": 0}).to_list(500)]
    rules = await db.bank_mapping_rules.find({"enabled": True}).sort("uses", -1).to_list(30)
    prompt = {
        "task": "Classify this bank transaction into the finance tracker. Choose ONLY from the given master data.",
        "rules": ["Do NOT assume debit=Expense or credit=Revenue.",
                  "Prefer mappings seen in historical_matches and learned_rules.",
                  "Return strict JSON: {\"type\":..., \"account\":..., \"project_id\":..., \"confidence\":0-100, \"reason\":\"...\"}"],
        "bank_transaction": {k: d.get(k) for k in ("bank_name", "transaction_date", "direction", "amount",
                                                    "narration", "merchant_name")},
        "historical_matches": matches[:5],
        "learned_rules": [{"pattern": r["pattern"], **r["mapping"], "uses": r.get("uses", 0)} for r in rules],
        "allowed_types": sorted(TYPES), "allowed_accounts": accounts, "allowed_project_ids": projects,
        "prior_suggestion": prior,
    }
    try:
        chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"bank-classify-{now_iso()}",
                       system_message="You are an Indian SME accountant. Reply with JSON only.").with_model(*AI_MODEL)
        text = await chat.send_message(UserMessage(text=json.dumps(prompt, default=str)))
        m = re.search(r"\{.*\}", text or "", re.DOTALL)
        obj = json.loads(m.group(0)) if m else None
    except Exception as e:
        logger.warning(f"AI classification failed: {e}")
        return None
    if not obj or obj.get("type") not in TYPES or obj.get("account") not in accounts \
            or obj.get("project_id") not in projects:
        return None
    conf = int(max(0, min(85, float(obj.get("confidence") or 0))))
    return {"type": obj["type"], "account": obj["account"], "project_id": obj["project_id"],
            "confidence": conf, "source": "ai", "reason": str(obj.get("reason", ""))[:300]}


# ---------- learning ----------
async def learn(txn: dict, final: dict, actor: str):
    pattern = (txn.get("suggestion") or {}).get("merchant_key") or merchant_key(txn["narration"], txn.get("merchant_name"))
    if not pattern:
        return
    key = f"{final['type']}|{final['account']}|{final['project_id']}"
    rule = await db.bank_mapping_rules.find_one({"pattern": pattern})
    votes = dict((rule or {}).get("votes") or {})
    votes[key] = votes.get(key, 0) + 1
    best_key = max(votes.items(), key=lambda kv: kv[1])[0]
    t, a, p = best_key.split("|", 2)
    uses = votes[best_key]
    corrections = sum(votes.values()) - uses
    doc = {"pattern": pattern, "keywords": sorted(keywords(txn["narration"])), "bank": txn.get("bank_name"),
           "mapping": {"type": t, "account": a, "project_id": p}, "votes": votes, "uses": uses,
           "corrections": corrections, "last_approved_mapping": final, "updated_at": now_iso()}
    doc["confidence"] = rule_confidence(doc)
    if rule:
        if rule.get("enabled") is False:
            doc.pop("mapping"), doc.pop("confidence")
        await db.bank_mapping_rules.update_one({"_id": rule["_id"]}, {"$set": doc})
    else:
        doc.update({"enabled": True, "created_at": now_iso(), "created_by": actor})
        await db.bank_mapping_rules.insert_one(doc)


# ---------- pipeline ----------
async def ingest_one(p: BankTxnIn, actor: str) -> dict:
    d = _validate_payload(p)
    d["fingerprint"] = bank_fingerprint(d)
    d["status"] = "pending"
    d["ingested_at"] = now_iso()
    d["ingested_by"] = actor
    d["reconciliation_status"] = "unmatched"
    d["finance_transaction_id"] = None
    dup_q = {"status": {"$ne": "duplicate"}, "$or": [{"fingerprint": d["fingerprint"]}]}
    if d.get("source_message_id"):
        dup_q["$or"].append({"source": d["source"], "source_message_id": d["source_message_id"]})
    existing = await db.bank_transactions.find_one(dup_q)
    if existing:
        d["status"] = "duplicate"
        d["duplicate_of"] = str(existing["_id"])
        d["suggestion"], d["matches"] = None, []
        r = await db.bank_transactions.insert_one(d)
        await audit("duplicate_detected", actor, r.inserted_id, new={"duplicate_of": d["duplicate_of"]})
        return _out(d | {"_id": r.inserted_id})
    r = await db.bank_transactions.insert_one(d)
    await audit("ingested", actor, r.inserted_id, new={"source": d["source"], "amount": d["amount"]})
    res = await classify(d, actor)
    await db.bank_transactions.update_one({"_id": r.inserted_id},
                                          {"$set": {"suggestion": res["suggestion"], "matches": res["matches"],
                                                    "classified_at": now_iso()}})
    src = res["suggestion"]["source"]
    action = {"ai": "ai_suggested", "mapping_rule": "historical_mapping_selected",
              "historical": "historical_mapping_selected"}.get(src, "classified")
    await audit(action, "system", r.inserted_id, new=res["suggestion"])
    d.update(suggestion=res["suggestion"], matches=res["matches"], _id=r.inserted_id)
    return _out(d)


def _out(d: dict) -> dict:
    return {
        "id": str(d["_id"]), "bank_name": d.get("bank_name"), "bank_account_masked": mask_account(d.get("bank_account")),
        "transaction_date": d.get("transaction_date"), "transaction_time": d.get("transaction_time", ""),
        "direction": d.get("direction"), "amount": d.get("amount"), "currency": d.get("currency", "INR"),
        "narration": d.get("narration"), "merchant_name": d.get("merchant_name"),
        "bank_reference": d.get("bank_reference", ""), "utr_reference": d.get("utr_reference", ""),
        "source": d.get("source"), "source_message_id": d.get("source_message_id", ""),
        "status": d.get("status"), "fingerprint": d.get("fingerprint"), "duplicate_of": d.get("duplicate_of"),
        "suggestion": d.get("suggestion"), "matches": d.get("matches") or [],
        "user_edits": d.get("user_edits"), "final": d.get("final"), "modified_fields": d.get("modified_fields") or [],
        "finance_transaction_id": d.get("finance_transaction_id"), "reconciliation_status": d.get("reconciliation_status"),
        "ingested_at": d.get("ingested_at"), "approved_at": d.get("approved_at"), "approved_by": d.get("approved_by"),
        "rejected_at": d.get("rejected_at"), "rejected_by": d.get("rejected_by"),
        "rejection_reason": d.get("rejection_reason"),
    }


def _oid(i: str) -> ObjectId:
    try:
        return ObjectId(i)
    except Exception:
        raise HTTPException(400, "Invalid id")


def _effective(txn: dict) -> dict:
    s = txn.get("suggestion") or {}
    base = {"type": s.get("type"), "account": s.get("account"), "project_id": s.get("project_id"),
            "amount": txn["amount"], "date": txn["transaction_date"], "notes": s.get("notes") or txn["narration"]}
    return {**base, **(txn.get("user_edits") or {})}


# ---------- ingestion (machine auth) ----------
async def require_ingest_key(x_ingest_key: Optional[str] = Header(None)):
    expected = os.environ.get("BANK_INGEST_API_KEY")
    if not expected:
        raise HTTPException(503, "Ingestion not configured")
    if not x_ingest_key or not hashlib.sha256(x_ingest_key.encode()).hexdigest() == hashlib.sha256(expected.encode()).hexdigest():
        raise HTTPException(401, "Invalid ingestion key")
    return "integration"


@router.post("/ingest")
async def ingest(payload: IngestBatchIn, actor: str = Depends(require_ingest_key)):
    results = [await ingest_one(t, actor) for t in payload.transactions]
    await db.bank_ingestion_log.insert_one({
        "timestamp": now_iso(), "actor": actor, "channel": "ingest_api",
        "count": len(results), "pending": sum(1 for r in results if r["status"] == "pending"),
        "duplicates": sum(1 for r in results if r["status"] == "duplicate"),
        "sources": sorted({r["source"] for r in results}), "ids": [r["id"] for r in results]})
    return {"count": len(results), "results": results}


@router.post("/manual")
async def manual_ingest(payload: BankTxnIn, user: dict = Depends(require_admin)):
    payload.source = "manual"
    r = await ingest_one(payload, user["email"])
    await db.bank_ingestion_log.insert_one({
        "timestamp": now_iso(), "actor": user["email"], "channel": "manual", "count": 1,
        "pending": 1 if r["status"] == "pending" else 0, "duplicates": 1 if r["status"] == "duplicate" else 0,
        "sources": ["manual"], "ids": [r["id"]]})
    return r


# ---------- listing ----------
@router.get("/stats")
async def stats(user: dict = Depends(require_admin)):
    pipe = [{"$group": {"_id": "$status", "n": {"$sum": 1}}}]
    out = {s: 0 for s in STATUSES}
    async for r in db.bank_transactions.aggregate(pipe):
        out[r["_id"]] = r["n"]
    out["all"] = sum(out.values())
    return out


@router.get("")
async def list_txns(user: dict = Depends(require_admin), status: Optional[str] = None, bank: Optional[str] = None,
                    direction: Optional[str] = None, start_date: Optional[str] = None, end_date: Optional[str] = None,
                    min_amount: Optional[float] = None, max_amount: Optional[float] = None,
                    suggested_type: Optional[str] = None, account: Optional[str] = None,
                    project_id: Optional[str] = None, min_confidence: Optional[int] = None,
                    max_confidence: Optional[int] = None, search: Optional[str] = None, limit: int = 500):
    q = {}
    if status and status != "all":
        q["status"] = status
    if bank:
        q["bank_name"] = {"$regex": re.escape(bank), "$options": "i"}
    if direction:
        q["direction"] = direction.lower()
    if start_date or end_date:
        q["transaction_date"] = {k: v for k, v in (("$gte", start_date), ("$lte", end_date)) if v}
    if min_amount is not None or max_amount is not None:
        q["amount"] = {k: v for k, v in (("$gte", min_amount), ("$lte", max_amount)) if v is not None}
    if suggested_type:
        q["suggestion.type"] = suggested_type
    if account:
        q["suggestion.account"] = account
    if project_id:
        q["suggestion.project_id"] = project_id
    if min_confidence is not None or max_confidence is not None:
        q["suggestion.confidence"] = {k: v for k, v in (("$gte", min_confidence), ("$lte", max_confidence)) if v is not None}
    if search:
        q["$or"] = [{"narration": {"$regex": re.escape(search), "$options": "i"}},
                    {"bank_reference": {"$regex": re.escape(search), "$options": "i"}},
                    {"merchant_name": {"$regex": re.escape(search), "$options": "i"}}]
    docs = await db.bank_transactions.find(q).sort([("transaction_date", -1), ("ingested_at", -1)]).to_list(min(limit, 2000))
    return [_out(d) for d in docs]


@router.get("/rules")
async def list_rules(user: dict = Depends(require_admin)):
    docs = await db.bank_mapping_rules.find({}).sort("uses", -1).to_list(1000)
    return [_rule_out(d) for d in docs]


def _rule_out(d: dict) -> dict:
    return {"id": str(d["_id"]), "pattern": d.get("pattern"), "keywords": d.get("keywords", []), "bank": d.get("bank"),
            "mapping": d.get("mapping"), "uses": d.get("uses", 0), "corrections": d.get("corrections", 0),
            "votes": d.get("votes", {}), "last_approved_mapping": d.get("last_approved_mapping"),
            "confidence": d.get("confidence", rule_confidence(d)), "enabled": d.get("enabled", True),
            "created_at": d.get("created_at"), "updated_at": d.get("updated_at")}


@router.put("/rules/{rid}")
async def update_rule(rid: str, payload: RuleUpdateIn, user: dict = Depends(require_admin)):
    oid = _oid(rid)
    rule = await db.bank_mapping_rules.find_one({"_id": oid})
    if not rule:
        raise HTTPException(404, "Rule not found")
    upd = {"updated_at": now_iso()}
    if payload.enabled is not None:
        upd["enabled"] = payload.enabled
    mapping = dict(rule.get("mapping") or {})
    for k in ("type", "account", "project_id"):
        v = getattr(payload, k)
        if v is not None:
            if k == "type" and v not in TYPES:
                raise HTTPException(422, "type must be Revenue/Cost/Expense")
            mapping[k] = v
    if mapping != rule.get("mapping"):
        upd["mapping"] = mapping
        upd["manually_edited_by"] = user["email"]
    await db.bank_mapping_rules.update_one({"_id": oid}, {"$set": upd})
    await audit("rule_edited", user["email"], None, previous=_rule_out(rule), new=upd, extra={"rule_id": rid})
    return _rule_out(await db.bank_mapping_rules.find_one({"_id": oid}))


@router.delete("/rules/{rid}")
async def delete_rule(rid: str, user: dict = Depends(require_admin)):
    oid = _oid(rid)
    rule = await db.bank_mapping_rules.find_one({"_id": oid})
    if not rule:
        raise HTTPException(404, "Rule not found")
    await db.bank_mapping_rules.delete_one({"_id": oid})
    await audit("rule_deleted", user["email"], None, previous=_rule_out(rule), extra={"rule_id": rid})
    return {"ok": True}


@router.get("/ingestion-history")
async def ingestion_history(user: dict = Depends(require_admin), limit: int = 100):
    docs = await db.bank_ingestion_log.find({}).sort("timestamp", -1).to_list(min(limit, 500))
    return [{"id": str(d["_id"]), **{k: v for k, v in d.items() if k != "_id"}} for d in docs]


async def _pending_or_400(tid: str) -> dict:
    d = await db.bank_transactions.find_one({"_id": _oid(tid)})
    if not d:
        raise HTTPException(404, "Not found")
    if d["status"] != "pending":
        raise HTTPException(400, f"Already {d['status']}")
    return d


import bank_inbox_ext  # noqa: E402,F401  literal routes must register before /{tid}


# ---------- single txn ----------
@router.get("/{tid}")
async def get_txn(tid: str, user: dict = Depends(require_admin)):
    d = await db.bank_transactions.find_one({"_id": _oid(tid)})
    if not d:
        raise HTTPException(404, "Not found")
    out = _out(d)
    out["effective"] = _effective(d)
    if d.get("duplicate_of"):
        orig = await db.bank_transactions.find_one({"_id": _oid(d["duplicate_of"])})
        out["duplicate_of_txn"] = _out(orig) if orig else None
    return out


@router.get("/{tid}/audit")
async def txn_audit(tid: str, user: dict = Depends(require_admin)):
    docs = await db.bank_audit_log.find({"bank_transaction_id": tid}).sort("timestamp", 1).to_list(200)
    return [{"id": str(d["_id"]), **{k: v for k, v in d.items() if k != "_id"}} for d in docs]


@router.put("/{tid}")
async def edit_txn(tid: str, payload: EditIn, user: dict = Depends(require_admin)):
    d = await _pending_or_400(tid)
    if payload.type not in TYPES:
        raise HTTPException(422, "type must be Revenue/Cost/Expense")
    if payload.amount <= 0:
        raise HTTPException(422, "amount must be greater than 0")
    if not payload.account.strip() or not payload.project_id.strip():
        raise HTTPException(422, "account and project_id are required")
    prev = _effective(d)
    edits = payload.model_dump()
    edits["notes"] = edits["notes"].strip() or d["narration"]
    s = d.get("suggestion") or {}
    baseline = {"type": s.get("type"), "account": s.get("account"), "project_id": s.get("project_id"),
                "amount": d["amount"], "date": d["transaction_date"], "notes": s.get("notes") or d["narration"]}
    modified = [k for k in edits if str(edits[k]) != str(baseline.get(k))]
    await db.bank_transactions.update_one({"_id": d["_id"]}, {"$set": {
        "user_edits": edits, "modified_fields": modified, "edited_at": now_iso(), "edited_by": user["email"]}})
    await audit("edited", user["email"], d["_id"], previous=prev, new=edits)
    return _out(await db.bank_transactions.find_one({"_id": d["_id"]}))


@router.post("/{tid}/approve")
async def approve_txn(tid: str, user: dict = Depends(require_admin)):
    d = await _pending_or_400(tid)
    return await _approve_pending_doc(d, tid, user)


async def _approve_pending_doc(d: dict, tid: str, user: dict) -> dict:
    final = _effective(d)
    if final["type"] not in TYPES or not final.get("account") or not final.get("project_id"):
        raise HTTPException(422, "Suggestion incomplete — edit Type, Account and Project ID before approving")
    if not await db.accounts.find_one({"name": final["account"]}):
        raise HTTPException(422, f"Account '{final['account']}' is not in master data")
    if not await db.project_ids.find_one({"code": final["project_id"]}):
        raise HTTPException(422, f"Project ID '{final['project_id']}' is not in master data")
    # atomic claim prevents double posting
    claim = await db.bank_transactions.update_one({"_id": d["_id"], "status": "pending"},
                                                  {"$set": {"status": "approving"}})
    if claim.matched_count == 0:
        raise HTTPException(400, "Already processed")
    payload = TransactionIn(**final).model_dump()
    fin = await insert_finance_transaction(payload, user["email"], "bank_transaction",
                                           extra={"bank_transaction_id": tid})
    s = d.get("suggestion") or {}
    modified = [k for k in ("type", "account", "project_id", "amount", "date", "notes")
                if str(final[k]) != str({"amount": d["amount"], "date": d["transaction_date"],
                                         "notes": s.get("notes") or d["narration"]}.get(k, s.get(k)))]
    await db.bank_transactions.update_one({"_id": d["_id"]}, {"$set": {
        "status": "approved", "final": final, "modified_fields": modified, "finance_transaction_id": fin["id"],
        "reconciliation_status": "matched", "approved_at": now_iso(), "approved_by": user["email"]}})
    await audit("approved", user["email"], d["_id"], previous=s, new=final)
    await audit("finance_transaction_created", user["email"], d["_id"], new={"finance_transaction_id": fin["id"]})
    await learn(d, {k: final[k] for k in ("type", "account", "project_id")}, user["email"])
    return {"ok": True, "finance_transaction_id": fin["id"], "modified_fields": modified,
            "transaction": _out(await db.bank_transactions.find_one({"_id": d["_id"]}))}


@router.post("/{tid}/reject")
async def reject_txn(tid: str, payload: RejectIn, user: dict = Depends(require_admin)):
    d = await _pending_or_400(tid)
    await db.bank_transactions.update_one({"_id": d["_id"], "status": "pending"}, {"$set": {
        "status": "rejected", "rejected_at": now_iso(), "rejected_by": user["email"],
        "rejection_reason": payload.reason}})
    await audit("rejected", user["email"], d["_id"], new={"reason": payload.reason})
    return {"ok": True}


@router.post("/{tid}/reclassify")
async def reclassify(tid: str, user: dict = Depends(require_admin)):
    d = await _pending_or_400(tid)
    res = await classify(d, user["email"])
    await db.bank_transactions.update_one({"_id": d["_id"]}, {"$set": {
        "suggestion": res["suggestion"], "matches": res["matches"], "classified_at": now_iso()}})
    await audit("classified", user["email"], d["_id"], previous=d.get("suggestion"), new=res["suggestion"])
    return _out(await db.bank_transactions.find_one({"_id": d["_id"]}))


async def ensure_indexes():
    await db.bank_transactions.create_index("fingerprint")
    await db.bank_transactions.create_index([("status", 1), ("transaction_date", -1)])
    await db.bank_transactions.create_index([("source", 1), ("source_message_id", 1)])
    await db.bank_transactions.create_index("finance_transaction_id")
    await db.bank_mapping_rules.create_index("pattern", unique=True)
    await db.bank_audit_log.create_index([("bank_transaction_id", 1), ("timestamp", 1)])
    await db.bank_ingestion_log.create_index("timestamp")
    await db.bank_parse_templates.create_index([("bank_name", 1), ("priority", 1)])
    from bank_inbox_ext import seed_templates
    await seed_templates()
