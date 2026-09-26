from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

import os
import json
import logging
import bcrypt
import jwt
import csv
import io
import hashlib
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, Query, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr

from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone

# --- Setup ---
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI(title="Rudaya Power Finance Tracker")
api_router = APIRouter(prefix="/api")

JWT_ALGORITHM = "HS256"
JWT_SECRET = os.environ["JWT_SECRET"]


# --- Password / JWT helpers ---
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: str, email: str) -> str:
    payload = {"sub": user_id, "email": email,
               "exp": datetime.now(timezone.utc) + timedelta(days=7),
               "type": "access"}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        user["_id"] = str(user["_id"])
        user.pop("password_hash", None)
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def set_auth_cookie(response: Response, token: str):
    response.set_cookie(
        key="access_token", value=token, httponly=True, secure=True,
        samesite="none", max_age=604800, path="/"
    )


def user_public(u: dict) -> dict:
    return {"id": str(u.get("_id", u.get("id"))), "email": u["email"],
            "name": u.get("name", ""), "role": u.get("role", "member")}


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user


# --- Brute-force login lockout (5 failed attempts / 15 min → HTTP 423) ---
LOCKOUT_THRESHOLD = 5
LOCKOUT_WINDOW_SECS = 900
_login_attempts: dict = {}  # email -> list[epoch_seconds]


def _prune_attempts(email: str) -> list:
    now = datetime.now(timezone.utc).timestamp()
    kept = [t for t in _login_attempts.get(email, []) if now - t < LOCKOUT_WINDOW_SECS]
    _login_attempts[email] = kept
    return kept


def _check_lockout(email: str):
    if len(_prune_attempts(email)) >= LOCKOUT_THRESHOLD:
        raise HTTPException(status_code=423, detail="Account temporarily locked. Try again in 15 minutes.")


def _record_failed_login(email: str):
    _login_attempts.setdefault(email, []).append(datetime.now(timezone.utc).timestamp())


def _clear_login_attempts(email: str):
    _login_attempts.pop(email, None)


# --- Auth models ---
class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    name: str = ""


class LoginIn(BaseModel):
    email: EmailStr
    password: str


# --- Transaction models ---
class TransactionIn(BaseModel):
    date: str  # ISO date
    type: str  # Revenue / Cost / Expense
    account: str
    amount: float
    project_id: str
    notes: str = ""


class TransactionOut(TransactionIn):
    id: str
    created_at: str


# --- Auth endpoints ---
@api_router.post("/auth/register")
async def register(payload: RegisterIn, response: Response):
    email = payload.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    doc = {"email": email, "password_hash": hash_password(payload.password),
           "name": payload.name or email.split("@")[0], "role": "member",
           "created_at": datetime.now(timezone.utc).isoformat()}
    result = await db.users.insert_one(doc)
    token = create_access_token(str(result.inserted_id), email)
    set_auth_cookie(response, token)
    return {"user": user_public({**doc, "_id": result.inserted_id}), "token": token}


@api_router.post("/auth/login")
async def login(payload: LoginIn, response: Response):
    email = payload.email.lower().strip()
    _check_lockout(email)
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(payload.password, user["password_hash"]):
        _record_failed_login(email)
        # After recording, re-check so the 5th failed attempt itself surfaces the lockout.
        if len(_prune_attempts(email)) >= LOCKOUT_THRESHOLD:
            raise HTTPException(status_code=423, detail="Account temporarily locked. Try again in 15 minutes.")
        raise HTTPException(status_code=401, detail="Invalid email or password")
    _clear_login_attempts(email)
    token = create_access_token(str(user["_id"]), email)
    set_auth_cookie(response, token)
    return {"user": user_public(user), "token": token}


@api_router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    return {"ok": True}


@api_router.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return {"user": user_public(user)}


# --- Meta endpoints ---
@api_router.get("/meta")
async def get_meta(user: dict = Depends(get_current_user)):
    projects = await db.projects.find({}, {"_id": 0}).to_list(500)
    accounts = await db.accounts.find({}, {"_id": 0}).to_list(500)
    project_ids = await db.project_ids.find({}, {"_id": 0}).to_list(500)
    return {"projects": projects, "accounts": accounts, "project_ids": project_ids}


class ProjectIdIn(BaseModel):
    code: str
    description: str = ""


class AccountIn(BaseModel):
    name: str


@api_router.post("/meta/project-ids")
async def add_project_id(payload: ProjectIdIn, user: dict = Depends(get_current_user)):
    if await db.project_ids.find_one({"code": payload.code}):
        raise HTTPException(status_code=400, detail="Project ID already exists")
    await db.project_ids.insert_one({"code": payload.code, "description": payload.description})
    return {"ok": True}


@api_router.post("/meta/accounts")
async def add_account(payload: AccountIn, user: dict = Depends(get_current_user)):
    if await db.accounts.find_one({"name": payload.name}):
        raise HTTPException(status_code=400, detail="Account already exists")
    await db.accounts.insert_one({"name": payload.name})
    return {"ok": True}


# --- Yearly Expense Budget (Account = Settings.accounts.name is the SoT) ---
class BudgetIn(BaseModel):
    year: int
    account: str          # MUST match an existing Settings account name
    amount: float
    notes: str = ""


def _budget_out(d: dict) -> dict:
    return {
        "id": str(d["_id"]),
        "year": d["year"], "account": d["account"],
        "amount": d["amount"], "notes": d.get("notes", ""),
        "created_at": d.get("created_at", ""),
        "updated_at": d.get("updated_at", ""),
    }


async def _account_exists(name: str) -> bool:
    return bool(await db.accounts.find_one({"name": name}))


@api_router.get("/budgets")
async def list_budgets(user: dict = Depends(get_current_user), year: Optional[int] = None):
    q = {}
    if year:
        q["year"] = year
    docs = await db.budgets.find(q).sort([("year", -1), ("account", 1)]).to_list(1000)
    return [_budget_out(d) for d in docs]


@api_router.post("/budgets")
async def create_budget(payload: BudgetIn, user: dict = Depends(get_current_user)):
    if not await _account_exists(payload.account):
        raise HTTPException(400, f"Account '{payload.account}' does not exist in Settings")
    if await db.budgets.find_one({"year": payload.year, "account": payload.account}):
        raise HTTPException(409, f"Budget for {payload.account} · {payload.year} already exists — edit it instead")
    doc = payload.model_dump()
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    doc["updated_at"] = doc["created_at"]
    doc["created_by"] = user["email"]
    r = await db.budgets.insert_one(doc)
    doc["_id"] = r.inserted_id
    return _budget_out(doc)


@api_router.put("/budgets/{bid}")
async def update_budget(bid: str, payload: BudgetIn, user: dict = Depends(get_current_user)):
    if not await _account_exists(payload.account):
        raise HTTPException(400, f"Account '{payload.account}' does not exist in Settings")
    try:
        oid = ObjectId(bid)
    except Exception:
        raise HTTPException(400, "Invalid id")
    # Prevent creating a (year, account) duplicate via update
    dup = await db.budgets.find_one({"year": payload.year, "account": payload.account, "_id": {"$ne": oid}})
    if dup:
        raise HTTPException(409, f"Budget for {payload.account} · {payload.year} already exists")
    update = {**payload.model_dump(),
              "updated_at": datetime.now(timezone.utc).isoformat(),
              "updated_by": user["email"]}
    r = await db.budgets.update_one({"_id": oid}, {"$set": update})
    if r.matched_count == 0:
        raise HTTPException(404, "Not found")
    doc = await db.budgets.find_one({"_id": oid})
    return _budget_out(doc)


@api_router.delete("/budgets/{bid}")
async def delete_budget(bid: str, user: dict = Depends(get_current_user)):
    try:
        oid = ObjectId(bid)
    except Exception:
        raise HTTPException(400, "Invalid id")
    r = await db.budgets.delete_one({"_id": oid})
    if r.deleted_count == 0:
        raise HTTPException(404, "Not found")
    return {"ok": True}


@api_router.get("/reports/budget-vs-actual")
async def budget_vs_actual(user: dict = Depends(get_current_user), year: Optional[int] = None):
    """Yearly Expense Budget vs Actual. Actual = SUM of Expense transactions per account for `year`.
    Rows include ALL budgeted accounts; also lists spent-but-unbudgeted accounts as info rows.
    Account is the existing Settings account name — single source of truth."""
    year = year or datetime.now(timezone.utc).year

    # Actual expense per account for the year
    actual = {}
    async for t in db.transactions.find({"type": "Expense"}):
        dt = _parse_iso(t.get("date", ""))
        if not dt or dt.year != year:
            continue
        a = t.get("account") or "(none)"
        actual[a] = actual.get(a, 0) + t.get("amount", 0)

    # Budgets for the year — one doc per (year, account)
    b_docs = await db.budgets.find({"year": year}).to_list(1000)
    budgets = {b["account"]: b for b in b_docs}

    def status_of(util):
        if util is None:
            return "unbudgeted"
        if util > 100:
            return "over"
        if util > 90:
            return "risk"
        return "ok"

    rows = []
    # Budgeted rows first
    for name, b in budgets.items():
        amt = b.get("amount", 0)
        act = actual.get(name, 0)
        util = (act / amt * 100) if amt else None
        rows.append({
            "budget_id": str(b["_id"]),
            "account": name,
            "budget": amt,
            "actual": act,
            "remaining": max(0.0, amt - act),
            "deficit": max(0.0, act - amt),
            "utilization_pct": util,
            "status": status_of(util),
        })
    # Unbudgeted accounts that have actual spend — surfaced so users can budget them
    for name, act in actual.items():
        if name in budgets:
            continue
        rows.append({
            "budget_id": None, "account": name,
            "budget": 0, "actual": act, "remaining": 0, "deficit": act,
            "utilization_pct": None, "status": "unbudgeted",
        })
    rows.sort(key=lambda r: (0 if r["status"] == "over" else 1 if r["status"] == "risk" else 2 if r["status"] == "ok" else 3, -r["actual"]))

    totals = {
        "budget": sum(r["budget"] for r in rows),
        "actual": sum(r["actual"] for r in rows),
    }
    totals["remaining"] = max(0.0, totals["budget"] - totals["actual"])
    totals["deficit"] = max(0.0, totals["actual"] - totals["budget"])
    totals["utilization_pct"] = (totals["actual"] / totals["budget"] * 100) if totals["budget"] else None
    return {"year": year, "rows": rows, "totals": totals}


# --- Transaction endpoints ---
def txn_out(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "date": doc["date"],
        "type": doc["type"],
        "account": doc["account"],
        "amount": doc["amount"],
        "project_id": doc["project_id"],
        "notes": doc.get("notes", ""),
        "created_at": doc.get("created_at", ""),
    }


@api_router.get("/transactions")
async def list_transactions(
    user: dict = Depends(get_current_user),
    type: Optional[str] = None,
    project_id: Optional[str] = None,
    account: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search: Optional[str] = None,
):
    q = {}
    if type:
        q["type"] = type
    if project_id:
        q["project_id"] = project_id
    if account:
        q["account"] = account
    if start_date or end_date:
        r = {}
        if start_date:
            r["$gte"] = start_date
        if end_date:
            r["$lte"] = end_date + "T23:59:59"
        q["date"] = r
    if search:
        q["$or"] = [
            {"notes": {"$regex": search, "$options": "i"}},
            {"account": {"$regex": search, "$options": "i"}},
            {"project_id": {"$regex": search, "$options": "i"}},
        ]
    docs = await db.transactions.find(q).sort("date", -1).to_list(5000)
    return [txn_out(d) for d in docs]


@api_router.post("/transactions")
async def create_transaction(payload: TransactionIn, user: dict = Depends(get_current_user)):
    doc = payload.model_dump()
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    doc["created_by"] = user["email"]
    result = await db.transactions.insert_one(doc)
    doc["_id"] = result.inserted_id
    return txn_out(doc)


@api_router.put("/transactions/{txn_id}")
async def update_transaction(txn_id: str, payload: TransactionIn, user: dict = Depends(get_current_user)):
    result = await db.transactions.update_one(
        {"_id": ObjectId(txn_id)}, {"$set": payload.model_dump()}
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Transaction not found")
    doc = await db.transactions.find_one({"_id": ObjectId(txn_id)})
    return txn_out(doc)


@api_router.delete("/transactions/{txn_id}")
async def delete_transaction(txn_id: str, user: dict = Depends(get_current_user)):
    result = await db.transactions.delete_one({"_id": ObjectId(txn_id)})
    if result.deleted_count == 0:
        raise HTTPException(404, "Transaction not found")
    return {"ok": True}


# --- Report endpoints ---
@api_router.get("/reports/summary")
async def summary(user: dict = Depends(get_current_user)):
    pipeline = [{"$group": {"_id": "$type", "total": {"$sum": "$amount"}, "count": {"$sum": 1}}}]
    result = {r["_id"]: {"total": r["total"], "count": r["count"]}
              async for r in db.transactions.aggregate(pipeline)}
    revenue = result.get("Revenue", {}).get("total", 0)
    cost = result.get("Cost", {}).get("total", 0)
    expense = result.get("Expense", {}).get("total", 0)
    return {
        "revenue": revenue, "cost": cost, "expense": expense,
        "gross_profit": revenue - cost,
        "net_profit": revenue - cost - expense,
        "counts": {k: v["count"] for k, v in result.items()},
    }


@api_router.get("/reports/monthly")
async def monthly(user: dict = Depends(get_current_user), year: Optional[int] = None):
    docs = await db.transactions.find({}).to_list(20000)
    buckets = {}  # (year, month) -> {"Revenue":..,"Cost":..,"Expense":..}
    for d in docs:
        try:
            dt = datetime.fromisoformat(d["date"].replace("Z", ""))
        except Exception:
            continue
        if year and dt.year != year:
            continue
        key = (dt.year, dt.month)
        b = buckets.setdefault(key, {"Revenue": 0, "Cost": 0, "Expense": 0})
        b[d["type"]] = b.get(d["type"], 0) + d["amount"]
    rows = []
    for (y, m), b in sorted(buckets.items()):
        rev, cst, exp = b["Revenue"], b["Cost"], b["Expense"]
        rows.append({
            "year": y, "month": m,
            "label": datetime(y, m, 1).strftime("%b %Y"),
            "revenue": rev, "cost": cst, "expense": exp,
            "gross_profit": rev - cst, "net_profit": rev - cst - exp,
        })
    return rows


# --- Forecast endpoints ---
class ForecastIn(BaseModel):
    year: int
    month: int  # 1-12
    amount: float
    notes: str = ""


class SalesForecastIn(BaseModel):
    year: int
    month: int  # 1-12
    type: str = "Revenue"  # Revenue / Cost / Expense
    project_id: str = ""  # "" == unallocated / general
    amount: float
    notes: str = ""


def _sf_out(d: dict) -> dict:
    return {
        "id": str(d["_id"]),
        "year": d["year"], "month": d["month"],
        "type": d.get("type", "Revenue"),
        "project_id": d.get("project_id", ""),
        "amount": d["amount"], "notes": d.get("notes", ""),
        "updated_at": d.get("updated_at", ""),
    }


@api_router.get("/sales-forecast")
async def list_sales_forecast(
    user: dict = Depends(get_current_user),
    year: Optional[int] = None,
    project_id: Optional[str] = None,
):
    q = {}
    if year:
        q["year"] = year
    if project_id:
        q["project_id"] = project_id
    docs = await db.sales_forecast.find(q).sort([("year", 1), ("month", 1)]).to_list(2000)
    return [_sf_out(d) for d in docs]


@api_router.post("/sales-forecast")
async def create_sales_forecast(payload: SalesForecastIn, user: dict = Depends(get_current_user)):
    if payload.month < 1 or payload.month > 12:
        raise HTTPException(400, "month must be 1..12")
    doc = payload.model_dump()
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    doc["updated_at"] = doc["created_at"]
    doc["created_by"] = user["email"]
    result = await db.sales_forecast.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _sf_out(doc)


@api_router.put("/sales-forecast/{fid}")
async def update_sales_forecast(fid: str, payload: SalesForecastIn, user: dict = Depends(get_current_user)):
    if payload.month < 1 or payload.month > 12:
        raise HTTPException(400, "month must be 1..12")
    try:
        oid = ObjectId(fid)
    except Exception:
        raise HTTPException(400, "Invalid id")
    update = {**payload.model_dump(),
              "updated_at": datetime.now(timezone.utc).isoformat(),
              "updated_by": user["email"]}
    result = await db.sales_forecast.update_one({"_id": oid}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(404, "Not found")
    doc = await db.sales_forecast.find_one({"_id": oid})
    return _sf_out(doc)


@api_router.delete("/sales-forecast/{fid}")
async def delete_sales_forecast(fid: str, user: dict = Depends(get_current_user)):
    try:
        oid = ObjectId(fid)
    except Exception:
        raise HTTPException(400, "Invalid id")
    r = await db.sales_forecast.delete_one({"_id": oid})
    if r.deleted_count == 0:
        raise HTTPException(404, "Not found")
    return {"ok": True}


# --- Quotations ---
class QuotationLineIn(BaseModel):
    type: str  # Revenue / Cost / Expense — validated below
    description: str = ""
    amount: float
    notes: str = ""

    @classmethod
    def __get_validators__(cls):
        yield from super().__get_validators__()

    def __init__(self, **data):
        t = data.get("type")
        if t not in ("Revenue", "Cost", "Expense"):
            raise ValueError(f"type must be Revenue/Cost/Expense, got {t!r}")
        super().__init__(**data)


class QuotationIn(BaseModel):
    quotation_number: str
    client_name: str = ""
    project_id: str = ""
    quote_date: str  # ISO date (YYYY-MM-DD)
    expected_year: int
    expected_month: int  # 1-12
    status: str = "draft"  # draft / sent / won / lost
    notes: str = ""
    lines: List[QuotationLineIn] = []


def _q_totals(lines: list) -> dict:
    t = {"Revenue": 0.0, "Cost": 0.0, "Expense": 0.0}
    for ln in lines:
        typ = ln.get("type", "Revenue")
        t[typ] = t.get(typ, 0) + ln.get("amount", 0)
    t["net"] = t["Revenue"] - t["Cost"] - t["Expense"]
    return t


def _q_out(d: dict) -> dict:
    lines = d.get("lines", []) or []
    return {
        "id": str(d["_id"]),
        "quotation_number": d.get("quotation_number", ""),
        "client_name": d.get("client_name", ""),
        "project_id": d.get("project_id", ""),
        "quote_date": d.get("quote_date", ""),
        "expected_year": d.get("expected_year"),
        "expected_month": d.get("expected_month"),
        "status": d.get("status", "draft"),
        "notes": d.get("notes", ""),
        "lines": lines,
        "totals": _q_totals(lines),
        "updated_at": d.get("updated_at", ""),
    }


@api_router.get("/quotations")
async def list_quotations(
    user: dict = Depends(get_current_user),
    year: Optional[int] = None,
    status: Optional[str] = None,
    project_id: Optional[str] = None,
):
    q = {}
    if year:
        q["expected_year"] = year
    if status:
        q["status"] = status
    if project_id:
        q["project_id"] = project_id
    docs = await db.quotations.find(q).sort([("quote_date", -1)]).to_list(500)
    return [_q_out(d) for d in docs]


@api_router.get("/quotations/{qid}")
async def get_quotation(qid: str, user: dict = Depends(get_current_user)):
    try:
        oid = ObjectId(qid)
    except Exception:
        raise HTTPException(400, "Invalid id")
    doc = await db.quotations.find_one({"_id": oid})
    if not doc:
        raise HTTPException(404, "Not found")
    return _q_out(doc)


@api_router.post("/quotations")
async def create_quotation(payload: QuotationIn, user: dict = Depends(get_current_user)):
    if payload.expected_month < 1 or payload.expected_month > 12:
        raise HTTPException(400, "expected_month must be 1..12")
    doc = payload.model_dump()
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    doc["updated_at"] = doc["created_at"]
    doc["created_by"] = user["email"]
    try:
        result = await db.quotations.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, f"quotation_number '{payload.quotation_number}' already exists")
    doc["_id"] = result.inserted_id
    return _q_out(doc)


@api_router.put("/quotations/{qid}")
async def update_quotation(qid: str, payload: QuotationIn, user: dict = Depends(get_current_user)):
    if payload.expected_month < 1 or payload.expected_month > 12:
        raise HTTPException(400, "expected_month must be 1..12")
    try:
        oid = ObjectId(qid)
    except Exception:
        raise HTTPException(400, "Invalid id")
    update = {**payload.model_dump(),
              "updated_at": datetime.now(timezone.utc).isoformat(),
              "updated_by": user["email"]}
    try:
        r = await db.quotations.update_one({"_id": oid}, {"$set": update})
    except DuplicateKeyError:
        raise HTTPException(409, f"quotation_number '{payload.quotation_number}' already exists")
    if r.matched_count == 0:
        raise HTTPException(404, "Not found")
    doc = await db.quotations.find_one({"_id": oid})
    return _q_out(doc)


@api_router.delete("/quotations/{qid}")
async def delete_quotation(qid: str, user: dict = Depends(get_current_user)):
    try:
        oid = ObjectId(qid)
    except Exception:
        raise HTTPException(400, "Invalid id")
    r = await db.quotations.delete_one({"_id": oid})
    if r.deleted_count == 0:
        raise HTTPException(404, "Not found")
    return {"ok": True}


@api_router.get("/forecast")
async def list_forecast(user: dict = Depends(get_current_user), year: Optional[int] = None):
    q = {}
    if year:
        q["year"] = year
    docs = await db.forecast.find(q).sort([("year", 1), ("month", 1)]).to_list(500)
    return [{"id": str(d["_id"]), "year": d["year"], "month": d["month"],
             "amount": d["amount"], "notes": d.get("notes", "")} for d in docs]


@api_router.post("/forecast")
async def upsert_forecast(payload: ForecastIn, user: dict = Depends(get_current_user)):
    """Legacy month-only forecast (single value per month). Kept for backward compat."""
    if payload.month < 1 or payload.month > 12:
        raise HTTPException(400, "month must be 1..12")
    key = {"year": payload.year, "month": payload.month}
    await db.forecast.update_one(
        key,
        {"$set": {**payload.model_dump(),
                  "updated_at": datetime.now(timezone.utc).isoformat(),
                  "updated_by": user["email"]}},
        upsert=True,
    )
    doc = await db.forecast.find_one(key)
    return {"id": str(doc["_id"]), "year": doc["year"], "month": doc["month"],
            "amount": doc["amount"], "notes": doc.get("notes", "")}


@api_router.delete("/forecast/{fid}")
async def delete_forecast(fid: str, user: dict = Depends(get_current_user)):
    try:
        oid = ObjectId(fid)
    except Exception:
        raise HTTPException(400, "Invalid id")
    r = await db.forecast.delete_one({"_id": oid})
    if r.deleted_count == 0:
        raise HTTPException(404, "Not found")
    return {"ok": True}


def _month_bucket_zero() -> dict:
    return {m: 0 for m in range(1, 13)}


def _typed_bucket_zero() -> dict:
    return {"Revenue": _month_bucket_zero(), "Cost": _month_bucket_zero(), "Expense": _month_bucket_zero()}


def _parse_iso(dt_str: str):
    try:
        return datetime.fromisoformat(dt_str.replace("Z", ""))
    except Exception:
        return None


async def _actual_by_type_by_month(year: int) -> dict:
    docs = await db.transactions.find({}).to_list(20000)
    actual = _typed_bucket_zero()
    for d in docs:
        dt = _parse_iso(d["date"])
        if not dt or dt.year != year:
            continue
        typ = d.get("type")
        if typ in actual:
            actual[typ][dt.month] += d["amount"]
    return actual


async def _forecast_by_type_by_month(year: int) -> tuple:
    """Sum Sales Forecast line items + quotation lines (status != lost) per (type, month).
    Falls back to legacy `forecast` collection (treated as Revenue) only if no other source exists for that month.
    Returns (forecast_totals, line_counts). Both are dict[type][month] -> value.
    """
    forecast = _typed_bucket_zero()
    line_counts = _typed_bucket_zero()

    async for sf in db.sales_forecast.find({"year": year}):
        m = sf.get("month")
        typ = sf.get("type", "Revenue")
        if 1 <= m <= 12 and typ in forecast:
            forecast[typ][m] += sf.get("amount", 0)
            line_counts[typ][m] += 1

    async for q in db.quotations.find({"expected_year": year, "status": {"$ne": "lost"}}):
        m = q.get("expected_month")
        if not (m and 1 <= m <= 12):
            continue
        for ln in (q.get("lines") or []):
            typ = ln.get("type", "Revenue")
            if typ in forecast:
                forecast[typ][m] += ln.get("amount", 0)
                line_counts[typ][m] += 1

    # Legacy /forecast docs are treated as Revenue-only fallback
    legacy = await db.forecast.find({"year": year}).to_list(500)
    for f in legacy:
        m = f.get("month")
        if 1 <= m <= 12 and line_counts["Revenue"][m] == 0:
            forecast["Revenue"][m] = f.get("amount", 0)

    return forecast, line_counts


@api_router.get("/reports/forecast-vs-actual")
async def forecast_vs_actual(user: dict = Depends(get_current_user), year: Optional[int] = None):
    """Consolidated forecast (Sales Forecast + non-lost Quotations) vs actual transactions,
    broken down by type (Revenue / Cost / Expense) for each month."""
    year = year or datetime.now(timezone.utc).year
    actual = await _actual_by_type_by_month(year)
    forecast, line_counts = await _forecast_by_type_by_month(year)
    types = ["Revenue", "Cost", "Expense"]
    rows = []
    for m in range(1, 13):
        row = {"year": year, "month": m, "label": datetime(year, m, 1).strftime("%b"),
               "forecast": {}, "actual": {}, "variance": {}, "achievement_pct": {}, "line_items": {}}
        for t in types:
            f_val = forecast[t][m]
            a_val = actual[t][m]
            row["forecast"][t] = f_val
            row["actual"][t] = a_val
            row["variance"][t] = a_val - f_val
            row["achievement_pct"][t] = (a_val / f_val * 100) if f_val else None
            row["line_items"][t] = line_counts[t][m]
        rows.append(row)
    total_forecast = {t: sum(forecast[t].values()) for t in types}
    total_actual = {t: sum(actual[t].values()) for t in types}
    return {
        "year": year, "types": types, "rows": rows,
        "total_forecast": total_forecast,
        "total_actual": total_actual,
        "total_forecast_all": sum(total_forecast.values()),
        "total_actual_all": sum(total_actual.values()),
    }


@api_router.get("/reports/project-pnl")
async def project_pnl(user: dict = Depends(get_current_user)):
    docs = await db.transactions.find({}).to_list(20000)
    buckets = {}
    for d in docs:
        pid = d.get("project_id") or "(none)"
        b = buckets.setdefault(pid, {"Revenue": 0, "Cost": 0, "Expense": 0})
        b[d["type"]] = b.get(d["type"], 0) + d["amount"]
    rows = []
    for pid, b in buckets.items():
        rev, cst, exp = b["Revenue"], b["Cost"], b["Expense"]
        rows.append({
            "project_id": pid,
            "revenue": rev, "cost": cst, "expense": exp,
            "gross_profit": rev - cst, "net_profit": rev - cst - exp,
        })
    rows.sort(key=lambda r: (r["revenue"] + r["cost"] + r["expense"]), reverse=True)
    return rows


@api_router.get("/reports/project-detail/{project_id}")
async def project_detail(project_id: str, user: dict = Depends(get_current_user), year: Optional[int] = None):
    """Drilldown for a single project — transactions, month-by-month forecast vs actual (SF + non-lost
    quotations scoped to the project), and totals. `year` defaults to current."""
    y = year or datetime.now(timezone.utc).year
    types = ["Revenue", "Cost", "Expense"]

    # Actual per (type, month) scoped to project
    actual = _typed_bucket_zero()
    totals = {"Revenue": 0.0, "Cost": 0.0, "Expense": 0.0}
    txn_docs = await db.transactions.find({"project_id": project_id}).sort("date", -1).to_list(5000)
    for t in txn_docs:
        totals[t["type"]] = totals.get(t["type"], 0) + t["amount"]
        dt = _parse_iso(t.get("date", ""))
        if dt and dt.year == y and t["type"] in actual:
            actual[t["type"]][dt.month] += t["amount"]

    # Forecast per (type, month) scoped to project (SF rows + non-lost quotation lines)
    forecast = _typed_bucket_zero()
    line_counts = _typed_bucket_zero()
    async for sf in db.sales_forecast.find({"year": y, "project_id": project_id}):
        m, typ = sf.get("month"), sf.get("type", "Revenue")
        if m and 1 <= m <= 12 and typ in forecast:
            forecast[typ][m] += sf.get("amount", 0)
            line_counts[typ][m] += 1

    quotations = []
    async for q in db.quotations.find({"project_id": project_id, "status": {"$ne": "lost"}}).sort("quote_date", -1):
        quotations.append({
            "id": str(q["_id"]),
            "quotation_number": q.get("quotation_number"),
            "client_name": q.get("client_name", ""),
            "expected_year": q.get("expected_year"),
            "expected_month": q.get("expected_month"),
            "status": q.get("status"),
            "totals": _q_totals(q.get("lines") or []),
        })
        if q.get("expected_year") != y:
            continue
        m = q.get("expected_month")
        if not (m and 1 <= m <= 12):
            continue
        for ln in (q.get("lines") or []):
            typ = ln.get("type", "Revenue")
            if typ in forecast:
                forecast[typ][m] += ln.get("amount", 0)
                line_counts[typ][m] += 1

    rows = []
    for m in range(1, 13):
        row = {"month": m, "label": datetime(y, m, 1).strftime("%b"),
               "forecast": {}, "actual": {}, "variance": {}, "achievement_pct": {}, "line_items": {}}
        for t in types:
            fv, av = forecast[t][m], actual[t][m]
            row["forecast"][t] = fv
            row["actual"][t] = av
            row["variance"][t] = av - fv
            row["achievement_pct"][t] = (av / fv * 100) if fv else None
            row["line_items"][t] = line_counts[t][m]
        rows.append(row)

    total_forecast = {t: sum(forecast[t].values()) for t in types}
    total_actual = {t: sum(actual[t].values()) for t in types}
    txns_out = [txn_out(t) for t in txn_docs]

    return {
        "project_id": project_id,
        "year": y,
        "totals": {
            "revenue": totals["Revenue"],
            "cost": totals["Cost"],
            "expense": totals["Expense"],
            "gross_profit": totals["Revenue"] - totals["Cost"],
            "net_profit": totals["Revenue"] - totals["Cost"] - totals["Expense"],
        },
        "rows": rows,
        "total_forecast": total_forecast,
        "total_actual": total_actual,
        "transactions": txns_out,
        "quotations": quotations,
        "transaction_count": len(txns_out),
    }


# --- Copy Last Year Forecast ---
class CopyLastYearIn(BaseModel):
    target_year: int
    include_quotations: bool = False
    overwrite: bool = False  # if False, skip rows whose (year, month, type, project_id, notes) already exists


@api_router.post("/sales-forecast/copy-last-year")
async def copy_last_year_forecast(payload: CopyLastYearIn, user: dict = Depends(get_current_user)):
    """Clone last year's Sales Forecast line items into `target_year`. Optionally clone non-lost
    quotations too (with `expected_year` shifted and a new unique quotation_number).
    Non-destructive: existing rows in the target year are preserved unless `overwrite=True`."""
    src_year = payload.target_year - 1
    now_iso = datetime.now(timezone.utc).isoformat()
    src_rows = await db.sales_forecast.find({"year": src_year}).to_list(2000)
    sf_created = sf_skipped = 0

    for sf in src_rows:
        doc = {
            "year": payload.target_year,
            "month": sf.get("month"),
            "type": sf.get("type", "Revenue"),
            "project_id": sf.get("project_id", ""),
            "amount": sf.get("amount", 0),
            "notes": sf.get("notes", ""),
        }
        # Dedup key: (year, month, type, project_id, notes)
        dup = await db.sales_forecast.find_one({
            "year": doc["year"], "month": doc["month"],
            "type": doc["type"], "project_id": doc["project_id"],
            "notes": doc["notes"],
        })
        if dup and not payload.overwrite:
            sf_skipped += 1
            continue
        doc["created_at"] = now_iso
        doc["updated_at"] = now_iso
        doc["created_by"] = user["email"]
        doc["source"] = "copy_last_year"
        doc["copied_from_year"] = src_year
        await db.sales_forecast.insert_one(doc)
        sf_created += 1

    q_created = q_skipped = 0
    if payload.include_quotations:
        async for q in db.quotations.find({"expected_year": src_year, "status": {"$ne": "lost"}}):
            base_number = q.get("quotation_number") or f"Q{str(q['_id'])[-6:]}"
            new_number = f"{base_number}-COPY{payload.target_year}"
            if await db.quotations.find_one({"quotation_number": new_number}):
                q_skipped += 1
                continue
            new_doc = {
                "quotation_number": new_number,
                "client_name": q.get("client_name", ""),
                "project_id": q.get("project_id", ""),
                "quote_date": (q.get("quote_date") or "")[:4].replace(str(src_year), str(payload.target_year)) + (q.get("quote_date") or "")[4:] if (q.get("quote_date") or "").startswith(str(src_year)) else q.get("quote_date", f"{payload.target_year}-01-01"),
                "expected_year": payload.target_year,
                "expected_month": q.get("expected_month"),
                "status": "draft",
                "notes": (q.get("notes", "") + f" [copied from {base_number}]").strip(),
                "lines": q.get("lines") or [],
                "created_at": now_iso,
                "updated_at": now_iso,
                "created_by": user["email"],
                "source": "copy_last_year",
            }
            try:
                await db.quotations.insert_one(new_doc)
                q_created += 1
            except DuplicateKeyError:
                q_skipped += 1

    return {
        "ok": True,
        "target_year": payload.target_year,
        "source_year": src_year,
        "sales_forecast": {"copied": sf_created, "skipped": sf_skipped},
        "quotations": {"copied": q_created, "skipped": q_skipped} if payload.include_quotations else None,
    }


# --- P&L Impact preview for Backup restore ---
@api_router.post("/migrations/backups/{stamp}/dry-run")
async def backup_restore_dry_run(stamp: str, mode: str = Form(...), user: dict = Depends(require_admin)):
    """Preview month-by-month P&L delta if we restored this backup snapshot in `mode` (merge|full)."""
    if mode not in ("merge", "full"):
        raise HTTPException(status_code=400, detail="mode must be 'merge' or 'full'")
    docs = await db.transaction_import_backups.find({"_backup_stamp": stamp}).to_list(None)
    if not docs:
        raise HTTPException(status_code=404, detail="Backup snapshot not found")

    existing_fps = await _existing_fingerprints()
    to_insert = []
    seen: set = set()
    for d in docs:
        core = _strip_backup_meta(d)
        if not all(k in core for k in ("date", "type", "account", "amount")):
            continue
        fp = _fingerprint(core)
        if mode == "merge" and (fp in existing_fps or fp in seen):
            continue
        if mode == "full" and fp in seen:
            continue
        seen.add(fp)
        to_insert.append(core)

    types = ["Revenue", "Cost", "Expense"]
    years = sorted({int((r.get("date") or "0000")[:4]) for r in to_insert if r.get("date")})
    if not years:
        years = [datetime.now(timezone.utc).year]

    years_out = {}
    for y in years:
        before = await _month_totals_for_year(y)
        contrib = _typed_bucket_zero()
        for r in to_insert:
            try:
                dt = datetime.strptime((r.get("date") or "")[:10], "%Y-%m-%d")
            except ValueError:
                continue
            if dt.year != y:
                continue
            typ = r.get("type")
            if typ in contrib:
                contrib[typ][dt.month] += r.get("amount", 0)

        # Full restore wipes current transactions first, so `after` is only the snapshot rows.
        if mode == "full":
            after = _typed_bucket_zero()
        else:
            after = {t: dict(before[t]) for t in types}
        for t in types:
            for m in range(1, 13):
                after[t][m] = after[t].get(m, 0) + contrib[t][m]

        months = []
        for m in range(1, 13):
            b = {t: before[t][m] for t in types}
            a = {t: after[t][m] for t in types}
            b["net"] = b["Revenue"] - b["Cost"] - b["Expense"]
            a["net"] = a["Revenue"] - a["Cost"] - a["Expense"]
            months.append({
                "month": m,
                "label": datetime(y, m, 1).strftime("%b"),
                "before": b, "after": a,
                "delta": {t: a[t] - b[t] for t in [*types, "net"]},
            })

        totals_before = {t: sum(before[t].values()) for t in types}
        totals_after = {t: sum(after[t].values()) for t in types}
        totals_before["net"] = totals_before["Revenue"] - totals_before["Cost"] - totals_before["Expense"]
        totals_after["net"] = totals_after["Revenue"] - totals_after["Cost"] - totals_after["Expense"]
        years_out[str(y)] = {
            "months": months,
            "totals_before": totals_before,
            "totals_after": totals_after,
            "totals_delta": {t: totals_after[t] - totals_before[t] for t in [*types, "net"]},
        }

    return {
        "mode": mode,
        "stamp": stamp,
        "would_insert": len(to_insert),
        "would_skip": len(docs) - len(to_insert),
        "years": years_out,
    }


# --- Seeding ---


# --- AI Assistant (Claude) ---
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
AI_MODEL = ("anthropic", "claude-sonnet-4-6")

AI_SYSTEM_PROMPT = (
    "You are RudayaAI, a concise financial insights assistant for Rudaya Powers Pvt. Ltd. "
    "You have access to live company financial data (transactions, monthly totals, forecast vs actual by type, "
    "project-wise P&L, and quotations). All amounts are Indian Rupees; format as ₹ with Indian grouping "
    "(e.g. ₹12,34,567) and use L/Cr shorthand (₹5.5L, ₹1.2Cr) when helpful. "
    "Be direct — give the answer first, then a short explanation. Use bullet points when listing. "
    "If the user asks a question the data doesn't cover, say so plainly. Never invent numbers.\n\n"
    "WRITE ACCESS (approval-gated): When the user asks you to RECORD, ADD, CREATE, LOG, ENTER or "
    "SAVE something (a transaction, a quotation, or a sales forecast entry), you must NOT claim it "
    "was saved. Instead, output ONE confirmation sentence for the human, and then a machine-parseable "
    "block on its own line in EXACTLY this format:\n"
    "<propose>{\"kind\": \"transaction\"|\"quotation\"|\"sales_forecast\", \"data\": { ... }}</propose>\n"
    "You may emit multiple <propose> blocks in one reply. All proposals go to a pending queue and the "
    "user approves them explicitly. Never fabricate ids, dates or amounts. If a required field is "
    "missing, ask the user for it instead of proposing.\n\n"
    "Schemas:\n"
    " • transaction: {date:'YYYY-MM-DD', type:'Revenue'|'Cost'|'Expense', account:str, amount:number, project_id:str, notes:str}\n"
    " • sales_forecast: {year:int, month:int(1-12), type:'Revenue'|'Cost'|'Expense', project_id:str(optional), amount:number, notes:str}\n"
    " • quotation: {quotation_number:str, client_name:str, project_id:str, quote_date:'YYYY-MM-DD', expected_year:int, expected_month:int(1-12), status:'draft'|'sent'|'won'|'lost', notes:str, lines:[{type:'Revenue'|'Cost'|'Expense', description:str, amount:number}]}\n"
    "After each <propose> also add a one-line human summary starting with '↳' so the user sees what was queued.\n"
)


class AiChatIn(BaseModel):
    message: str
    session_id: Optional[str] = None
    year: Optional[int] = None


async def _build_finance_context(year: Optional[int]) -> str:
    y = year or datetime.now(timezone.utc).year
    # summary
    pipe = [{"$group": {"_id": "$type", "total": {"$sum": "$amount"}, "count": {"$sum": 1}}}]
    summary = {r["_id"]: {"total": r["total"], "count": r["count"]}
               async for r in db.transactions.aggregate(pipe)}
    # monthly
    monthly_docs = await db.transactions.find({}).to_list(20000)
    monthly = {}
    for d in monthly_docs:
        dt = _parse_iso(d["date"])
        if not dt:
            continue
        key = f"{dt.year}-{dt.month:02d}"
        b = monthly.setdefault(key, {"Revenue": 0, "Cost": 0, "Expense": 0})
        b[d["type"]] = b.get(d["type"], 0) + d["amount"]
    # forecast v actual
    actual = await _actual_by_type_by_month(y)
    forecast, line_counts = await _forecast_by_type_by_month(y)
    fva = []
    for m in range(1, 13):
        fva.append({
            "month": datetime(y, m, 1).strftime("%b"),
            "forecast": {t: forecast[t][m] for t in ["Revenue", "Cost", "Expense"]},
            "actual": {t: actual[t][m] for t in ["Revenue", "Cost", "Expense"]},
        })
    # project pnl
    p_docs = await db.transactions.find({}).to_list(20000)
    proj = {}
    for d in p_docs:
        pid = d.get("project_id") or "(none)"
        b = proj.setdefault(pid, {"Revenue": 0, "Cost": 0, "Expense": 0})
        b[d["type"]] = b.get(d["type"], 0) + d["amount"]
    top = sorted(proj.items(),
                 key=lambda kv: kv[1]["Revenue"] - kv[1]["Cost"] - kv[1]["Expense"],
                 reverse=True)[:10]
    # quotations
    quotes = []
    async for q in db.quotations.find({}).sort("quote_date", -1).limit(20):
        quotes.append({
            "number": q.get("quotation_number"),
            "client": q.get("client_name"),
            "project_id": q.get("project_id"),
            "expected": f'{q.get("expected_year")}-{q.get("expected_month"):02d}',
            "status": q.get("status"),
            "totals": _q_totals(q.get("lines") or []),
        })

    ctx = {
        "company": "Rudaya Powers Pvt. Ltd.",
        "currency": "INR",
        "asOfYear": y,
        "overallTotals": {k: v["total"] for k, v in summary.items()},
        "recentMonthlyByType": dict(sorted(monthly.items())[-6:]),
        "forecastVsActual": fva,
        "topProjectsByNetProfit": [{"project_id": p, **b,
                                    "net": b["Revenue"] - b["Cost"] - b["Expense"]}
                                   for p, b in top],
        "quotations": quotes,
    }
    return json.dumps(ctx, default=str)


@api_router.post("/ai/chat")
async def ai_chat(payload: AiChatIn, user: dict = Depends(get_current_user)):
    if not EMERGENT_LLM_KEY:
        raise HTTPException(500, "AI key not configured")
    session_id = payload.session_id or f"user-{user['email']}-{datetime.now(timezone.utc).isoformat()}"

    # Persist user message
    await db.ai_messages.insert_one({
        "session_id": session_id, "role": "user", "content": payload.message,
        "user_email": user["email"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    ctx_json = await _build_finance_context(payload.year)
    system = AI_SYSTEM_PROMPT + "\n\nLive company data (JSON):\n" + ctx_json

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=session_id,
        system_message=system,
    ).with_model(*AI_MODEL)

    async def event_generator():
        collected = []
        try:
            async for ev in chat.stream_message(UserMessage(text=payload.message)):
                if isinstance(ev, TextDelta):
                    collected.append(ev.content)
                    yield f"data: {json.dumps({'delta': ev.content})}\n\n"
                elif isinstance(ev, StreamDone):
                    break
            full = "".join(collected)
            proposals = await _extract_and_store_proposals(full, user["email"], session_id)
            await db.ai_messages.insert_one({
                "session_id": session_id, "role": "assistant", "content": full,
                "user_email": user["email"],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "proposals": proposals,
            })
            yield f"data: {json.dumps({'done': True, 'session_id': session_id, 'proposals': proposals})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@api_router.get("/ai/history")
async def ai_history(user: dict = Depends(get_current_user), session_id: Optional[str] = None, limit: int = 50):
    q = {"user_email": user["email"]}
    if session_id:
        q["session_id"] = session_id
    docs = await db.ai_messages.find(q).sort("created_at", 1).to_list(limit)
    return [{"id": str(d["_id"]), "role": d["role"], "content": d["content"],
             "session_id": d["session_id"], "created_at": d["created_at"]} for d in docs]


import re as _re

_PROPOSE_RE = _re.compile(r"<propose>\s*(\{.*?\})\s*</propose>", _re.DOTALL)

ALLOWED_KINDS = {"transaction", "sales_forecast", "quotation"}


async def _extract_and_store_proposals(full_text: str, user_email: str, session_id: str) -> list:
    proposals = []
    for m in _PROPOSE_RE.finditer(full_text or ""):
        try:
            obj = json.loads(m.group(1))
        except Exception:
            continue
        kind = obj.get("kind")
        data = obj.get("data")
        if kind not in ALLOWED_KINDS or not isinstance(data, dict):
            continue
        doc = {
            "kind": kind, "data": data, "status": "pending",
            "session_id": session_id, "created_by": user_email,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        r = await db.ai_pending_actions.insert_one(doc)
        proposals.append({"id": str(r.inserted_id), "kind": kind, "data": data, "status": "pending"})
    return proposals


@api_router.get("/ai/pending")
async def list_pending(user: dict = Depends(get_current_user), status: Optional[str] = "pending"):
    q = {"created_by": user["email"]}
    if status and status != "all":
        q["status"] = status
    docs = await db.ai_pending_actions.find(q).sort("created_at", -1).to_list(100)
    return [{"id": str(d["_id"]), "kind": d["kind"], "data": d["data"],
             "status": d["status"], "created_at": d["created_at"],
             "session_id": d.get("session_id", "")} for d in docs]


async def _apply_pending(doc: dict, user: dict) -> dict:
    kind, data = doc["kind"], doc["data"]
    if kind == "transaction":
        payload = TransactionIn(**data).model_dump()
        payload["created_at"] = datetime.now(timezone.utc).isoformat()
        payload["created_by"] = user["email"]
        payload["source"] = "ai_approved"
        r = await db.transactions.insert_one(payload)
        return {"kind": "transaction", "id": str(r.inserted_id)}
    if kind == "sales_forecast":
        payload = SalesForecastIn(**data).model_dump()
        if payload["month"] < 1 or payload["month"] > 12:
            raise HTTPException(400, "month must be 1..12")
        payload["created_at"] = datetime.now(timezone.utc).isoformat()
        payload["updated_at"] = payload["created_at"]
        payload["created_by"] = user["email"]
        r = await db.sales_forecast.insert_one(payload)
        return {"kind": "sales_forecast", "id": str(r.inserted_id)}
    if kind == "quotation":
        payload = QuotationIn(**data).model_dump()
        payload["created_at"] = datetime.now(timezone.utc).isoformat()
        payload["updated_at"] = payload["created_at"]
        payload["created_by"] = user["email"]
        try:
            r = await db.quotations.insert_one(payload)
        except DuplicateKeyError:
            raise HTTPException(409, f"quotation_number '{payload.get('quotation_number')}' already exists")
        return {"kind": "quotation", "id": str(r.inserted_id)}
    raise HTTPException(400, f"unsupported kind {kind}")


@api_router.post("/ai/pending/{pid}/approve")
async def approve_pending(pid: str, user: dict = Depends(get_current_user)):
    try:
        oid = ObjectId(pid)
    except Exception:
        raise HTTPException(400, "Invalid id")
    doc = await db.ai_pending_actions.find_one({"_id": oid, "created_by": user["email"]})
    if not doc:
        raise HTTPException(404, "Not found")
    if doc["status"] != "pending":
        raise HTTPException(400, f"Already {doc['status']}")
    result = await _apply_pending(doc, user)
    await db.ai_pending_actions.update_one(
        {"_id": oid},
        {"$set": {"status": "approved",
                  "approved_at": datetime.now(timezone.utc).isoformat(),
                  "approved_by": user["email"],
                  "applied_ref": result}}
    )
    return {"ok": True, "applied": result}


@api_router.post("/ai/pending/{pid}/reject")
async def reject_pending(pid: str, user: dict = Depends(get_current_user)):
    try:
        oid = ObjectId(pid)
    except Exception:
        raise HTTPException(400, "Invalid id")
    r = await db.ai_pending_actions.update_one(
        {"_id": oid, "created_by": user["email"], "status": "pending"},
        {"$set": {"status": "rejected",
                  "rejected_at": datetime.now(timezone.utc).isoformat()}}
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Not found or already handled")
    return {"ok": True}


# --- Data Migration: Admin-only CSV Import ---
REQUIRED_CSV_HEADERS = ["date", "type", "account", "amount", "project_id", "notes"]
ALLOWED_TXN_TYPES = {"Revenue", "Cost", "Expense"}


def _normalize_type(v: str) -> Optional[str]:
    if not v:
        return None
    s = v.strip().lower()
    mapping = {"revenue": "Revenue", "cost": "Cost", "expense": "Expense"}
    return mapping.get(s)


def _parse_import_date(v: str) -> Optional[str]:
    """Accept YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY. Return ISO YYYY-MM-DD or None."""
    if not v:
        return None
    v = v.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(v, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _fingerprint(txn: dict) -> str:
    """Stable hash of (date, type, account, amount, project_id, notes)."""
    parts = [
        (txn.get("date") or "")[:10],
        (txn.get("type") or "").strip(),
        (txn.get("account") or "").strip(),
        f"{float(txn.get('amount') or 0):.2f}",
        (txn.get("project_id") or "").strip(),
        (txn.get("notes") or "").strip(),
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse_csv_rows(raw: bytes) -> tuple:
    """Return (rows, header_error). rows is list of dicts with row_number + raw + parsed + errors."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1", errors="replace")
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return [], "CSV is empty"
    header_norm = [h.strip().lower() for h in header]
    missing = [h for h in REQUIRED_CSV_HEADERS if h not in header_norm]
    if missing:
        return [], f"Missing required column(s): {', '.join(missing)}"
    idx = {h: header_norm.index(h) for h in REQUIRED_CSV_HEADERS}

    out = []
    for i, row in enumerate(reader, start=2):  # header is row 1
        if not any(c.strip() for c in row):
            continue  # skip blank lines
        raw_row = {h: (row[idx[h]] if idx[h] < len(row) else "") for h in REQUIRED_CSV_HEADERS}
        errors = []
        parsed_date = _parse_import_date(raw_row["date"])
        if not parsed_date:
            errors.append("Invalid or missing date (accepted: YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY)")
        ttype = _normalize_type(raw_row["type"])
        if not ttype:
            errors.append("Type must be Revenue, Cost, or Expense")
        account = raw_row["account"].strip()
        if not account:
            errors.append("Account is required")
        try:
            amount = float(raw_row["amount"])
            if amount <= 0:
                errors.append("Amount must be a positive number")
        except (TypeError, ValueError):
            amount = None
            errors.append("Amount must be numeric")
        project_id = raw_row["project_id"].strip()
        if not project_id:
            errors.append("Project ID is required")
        notes = raw_row["notes"].strip()

        parsed = None
        if not errors:
            parsed = {
                "date": parsed_date,
                "type": ttype,
                "account": account,
                "amount": amount,
                "project_id": project_id,
                "notes": notes,
            }
        out.append({
            "row_number": i,
            "raw": raw_row,
            "parsed": parsed,
            "errors": errors,
            "valid": len(errors) == 0,
            "fingerprint": _fingerprint(parsed) if parsed else "",
        })
    return out, None


async def _existing_fingerprints() -> set:
    """Compute fingerprints of every existing transaction (safe for tens of thousands of rows)."""
    fps = set()
    async for t in db.transactions.find({}, {"date": 1, "type": 1, "account": 1, "amount": 1, "project_id": 1, "notes": 1, "fingerprint": 1}):
        fp = t.get("fingerprint") or _fingerprint(t)
        fps.add(fp)
    return fps


def _summarize(rows: list) -> dict:
    by_type = {"Revenue": {"count": 0, "total": 0.0},
               "Cost": {"count": 0, "total": 0.0},
               "Expense": {"count": 0, "total": 0.0}}
    valid = 0
    invalid = 0
    duplicates = 0
    for r in rows:
        if not r["valid"]:
            invalid += 1
            continue
        valid += 1
        if r.get("duplicate"):
            duplicates += 1
        p = r["parsed"]
        by_type[p["type"]]["count"] += 1
        by_type[p["type"]]["total"] += p["amount"]
    return {
        "total_rows": len(rows),
        "valid_rows": valid,
        "invalid_rows": invalid,
        "duplicates": duplicates,
        "by_type": by_type,
    }


@api_router.post("/migrations/preview")
async def preview_import(file: UploadFile = File(...), user: dict = Depends(require_admin)):
    raw = await file.read()
    rows, header_error = _parse_csv_rows(raw)
    if header_error:
        raise HTTPException(status_code=400, detail=header_error)
    fps = await _existing_fingerprints()
    seen: set = set()
    for r in rows:
        if not r["valid"]:
            r["duplicate"] = False
            continue
        fp = r["fingerprint"]
        # A row is a duplicate if it already exists in DB OR appeared earlier in this file.
        r["duplicate"] = fp in fps or fp in seen
        seen.add(fp)
    summary = _summarize(rows)
    return {
        "filename": file.filename,
        **summary,
        "rows": rows,
    }


@api_router.post("/migrations/import")
async def import_csv(
    file: UploadFile = File(...),
    mode: str = Form(...),
    user: dict = Depends(require_admin),
):
    if mode not in ("skip_duplicates", "replace_existing"):
        raise HTTPException(status_code=400, detail="mode must be 'skip_duplicates' or 'replace_existing'")
    raw = await file.read()
    rows, header_error = _parse_csv_rows(raw)
    if header_error:
        raise HTTPException(status_code=400, detail=header_error)
    if not rows:
        raise HTTPException(status_code=400, detail="CSV has no data rows")

    valid_rows = [r for r in rows if r["valid"]]
    invalid_count = len(rows) - len(valid_rows)
    if not valid_rows:
        raise HTTPException(status_code=400, detail=f"No valid rows to import ({invalid_count} invalid)")

    now_iso = datetime.now(timezone.utc).isoformat()
    backup_ref = None
    backup_count = 0

    if mode == "replace_existing":
        # Back up existing transactions BEFORE deleting.
        backup_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        existing = await db.transactions.find({}).to_list(None)
        backup_count = len(existing)
        if backup_count:
            backup_docs = []
            for t in existing:
                t_copy = dict(t)
                t_copy["_original_id"] = str(t_copy.pop("_id"))
                t_copy["_backup_stamp"] = backup_stamp
                t_copy["_backed_up_by"] = user["email"]
                t_copy["_backed_up_at"] = now_iso
                backup_docs.append(t_copy)
            await db.transaction_import_backups.insert_many(backup_docs)
        await db.transactions.delete_many({})
        backup_ref = {"stamp": backup_stamp, "count": backup_count}

    # After a replace, the DB is empty — recompute fingerprints for skip-duplicates fresh.
    existing_fps = await _existing_fingerprints()

    inserted_docs = []
    skipped_duplicate = 0
    seen_in_batch: set = set()
    for r in valid_rows:
        fp = r["fingerprint"]
        if fp in existing_fps or fp in seen_in_batch:
            skipped_duplicate += 1
            continue
        seen_in_batch.add(fp)
        doc = dict(r["parsed"])
        doc["created_at"] = now_iso
        doc["created_by"] = user["email"]
        doc["source"] = "csv_import"
        doc["fingerprint"] = fp
        inserted_docs.append(doc)

    inserted_count = 0
    if inserted_docs:
        res = await db.transactions.insert_many(inserted_docs)
        inserted_count = len(res.inserted_ids)

    history_doc = {
        "filename": file.filename,
        "mode": mode,
        "admin_email": user["email"],
        "started_at": now_iso,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "total_rows": len(rows),
        "invalid_rows": invalid_count,
        "inserted": inserted_count,
        "skipped_duplicate": skipped_duplicate,
        "backup_stamp": backup_ref["stamp"] if backup_ref else None,
        "backed_up_count": backup_count,
    }
    hist_res = await db.import_history.insert_one(history_doc)

    return {
        "ok": True,
        "history_id": str(hist_res.inserted_id),
        "mode": mode,
        "inserted": inserted_count,
        "skipped_duplicate": skipped_duplicate,
        "invalid_rows": invalid_count,
        "total_rows": len(rows),
        "backup": backup_ref,
    }


@api_router.get("/migrations/history")
async def import_history(user: dict = Depends(require_admin), limit: int = 50):
    docs = await db.import_history.find({}).sort("completed_at", -1).to_list(limit)
    return [{"id": str(d["_id"]),
             "filename": d.get("filename", ""),
             "mode": d.get("mode", ""),
             "admin_email": d.get("admin_email", ""),
             "started_at": d.get("started_at", ""),
             "completed_at": d.get("completed_at", ""),
             "total_rows": d.get("total_rows", 0),
             "invalid_rows": d.get("invalid_rows", 0),
             "inserted": d.get("inserted", 0),
             "skipped_duplicate": d.get("skipped_duplicate", 0),
             "backup_stamp": d.get("backup_stamp"),
             "backed_up_count": d.get("backed_up_count", 0),
             "restored_from": d.get("restored_from")} for d in docs]


# --- Dry-run: preview month-by-month P&L delta if the CSV were imported now ---
async def _month_totals_for_year(year: int) -> dict:
    """Returns {Revenue: {m:sum}, Cost: {m:sum}, Expense: {m:sum}} for `year` from db.transactions."""
    return await _actual_by_type_by_month(year)


def _selected_rows_for_mode(rows: list, existing_fps: set, mode: str) -> list:
    """Return list of parsed dicts that WOULD be inserted, given the mode + dedup rules."""
    out = []
    seen: set = set()
    for r in rows:
        if not r["valid"]:
            continue
        fp = r["fingerprint"]
        if mode == "skip_duplicates" and (fp in existing_fps or fp in seen):
            continue
        if mode == "replace_existing" and fp in seen:
            continue
        seen.add(fp)
        out.append(r["parsed"])
    return out


@api_router.post("/migrations/dry-run")
async def dry_run_impact(
    file: UploadFile = File(...),
    mode: str = Form(...),
    user: dict = Depends(require_admin),
):
    if mode not in ("skip_duplicates", "replace_existing"):
        raise HTTPException(status_code=400, detail="mode must be 'skip_duplicates' or 'replace_existing'")
    raw = await file.read()
    rows, header_error = _parse_csv_rows(raw)
    if header_error:
        raise HTTPException(status_code=400, detail=header_error)
    existing_fps = await _existing_fingerprints()
    to_insert = _selected_rows_for_mode(rows, existing_fps, mode)

    # Years touched: from the CSV rows we would insert. If empty, still return the current year for context.
    years = sorted({int(r["date"][:4]) for r in to_insert})
    if not years:
        years = [datetime.now(timezone.utc).year]

    types = ["Revenue", "Cost", "Expense"]
    years_out = {}
    for y in years:
        before = await _month_totals_for_year(y)
        contrib = _typed_bucket_zero()
        for r in to_insert:
            try:
                dt = datetime.strptime(r["date"], "%Y-%m-%d")
            except ValueError:
                continue
            if dt.year != y:
                continue
            contrib[r["type"]][dt.month] += r["amount"]

        # In replace_existing mode the entire transactions collection is wiped BEFORE the CSV lands,
        # so the "after" P&L for the year is only the imported rows (no legacy data).
        if mode == "replace_existing":
            after = _typed_bucket_zero()
        else:
            after = {t: dict(before[t]) for t in types}
        for t in types:
            for m in range(1, 13):
                after[t][m] = after[t].get(m, 0) + contrib[t][m]

        months = []
        for m in range(1, 13):
            b = {t: before[t][m] for t in types}
            a = {t: after[t][m] for t in types}
            b["net"] = b["Revenue"] - b["Cost"] - b["Expense"]
            a["net"] = a["Revenue"] - a["Cost"] - a["Expense"]
            months.append({
                "month": m,
                "label": datetime(y, m, 1).strftime("%b"),
                "before": b,
                "after": a,
                "delta": {t: a[t] - b[t] for t in [*types, "net"]},
            })

        totals_before = {t: sum(before[t].values()) for t in types}
        totals_after = {t: sum(after[t].values()) for t in types}
        totals_before["net"] = totals_before["Revenue"] - totals_before["Cost"] - totals_before["Expense"]
        totals_after["net"] = totals_after["Revenue"] - totals_after["Cost"] - totals_after["Expense"]
        totals_delta = {t: totals_after[t] - totals_before[t] for t in [*types, "net"]}

        years_out[str(y)] = {
            "months": months,
            "totals_before": totals_before,
            "totals_after": totals_after,
            "totals_delta": totals_delta,
        }

    return {
        "mode": mode,
        "would_insert": len(to_insert),
        "years": years_out,
    }


# --- Backup snapshots: list + view + restore ---
@api_router.get("/migrations/backups")
async def list_backups(user: dict = Depends(require_admin)):
    pipeline = [
        {"$group": {
            "_id": "$_backup_stamp",
            "count": {"$sum": 1},
            "admin_email": {"$first": "$_backed_up_by"},
            "backed_up_at": {"$first": "$_backed_up_at"},
            "revenue_total": {"$sum": {"$cond": [{"$eq": ["$type", "Revenue"]}, "$amount", 0]}},
            "cost_total":    {"$sum": {"$cond": [{"$eq": ["$type", "Cost"]},    "$amount", 0]}},
            "expense_total": {"$sum": {"$cond": [{"$eq": ["$type", "Expense"]}, "$amount", 0]}},
        }},
        {"$sort": {"_id": -1}},
    ]
    out = []
    async for r in db.transaction_import_backups.aggregate(pipeline):
        if not r.get("_id"):
            continue
        out.append({
            "stamp": r["_id"],
            "count": r["count"],
            "admin_email": r.get("admin_email", ""),
            "backed_up_at": r.get("backed_up_at", ""),
            "totals": {
                "Revenue": r.get("revenue_total", 0),
                "Cost": r.get("cost_total", 0),
                "Expense": r.get("expense_total", 0),
            },
        })
    return out


@api_router.get("/migrations/backups/{stamp}")
async def get_backup(stamp: str, user: dict = Depends(require_admin), limit: int = 500):
    docs = await db.transaction_import_backups.find({"_backup_stamp": stamp}).limit(limit).to_list(None)
    if not docs:
        raise HTTPException(status_code=404, detail="Backup snapshot not found")

    def clean(d: dict) -> dict:
        return {
            "date": d.get("date", ""),
            "type": d.get("type", ""),
            "account": d.get("account", ""),
            "amount": d.get("amount", 0),
            "project_id": d.get("project_id", ""),
            "notes": d.get("notes", ""),
            "source": d.get("source", ""),
            "created_at": d.get("created_at", ""),
        }
    return {"stamp": stamp, "count": len(docs), "rows": [clean(d) for d in docs]}


def _strip_backup_meta(doc: dict) -> dict:
    drop = {"_id", "_original_id", "_backup_stamp", "_backed_up_by", "_backed_up_at", "fingerprint"}
    return {k: v for k, v in doc.items() if k not in drop}


@api_router.post("/migrations/backups/{stamp}/restore")
async def restore_backup(stamp: str, mode: str = Form(...), user: dict = Depends(require_admin)):
    """Restore a previously stored backup snapshot.
    - mode='full'  : wipe current transactions (auto-backup first!) then insert every row from the snapshot.
    - mode='merge' : insert only rows from the snapshot whose fingerprint doesn't already exist.
    Every restore is recorded in `import_history`."""
    if mode not in ("full", "merge"):
        raise HTTPException(status_code=400, detail="mode must be 'full' or 'merge'")
    docs = await db.transaction_import_backups.find({"_backup_stamp": stamp}).to_list(None)
    if not docs:
        raise HTTPException(status_code=404, detail="Backup snapshot not found")

    now_iso = datetime.now(timezone.utc).isoformat()
    auto_backup_ref = None
    if mode == "full":
        # Safety net: back up the CURRENT state before we wipe it.
        current = await db.transactions.find({}).to_list(None)
        pre_count = len(current)
        auto_stamp = f"prerestore-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        if pre_count:
            snap = []
            for t in current:
                cp = dict(t)
                cp["_original_id"] = str(cp.pop("_id"))
                cp["_backup_stamp"] = auto_stamp
                cp["_backed_up_by"] = user["email"]
                cp["_backed_up_at"] = now_iso
                snap.append(cp)
            await db.transaction_import_backups.insert_many(snap)
        await db.transactions.delete_many({})
        auto_backup_ref = {"stamp": auto_stamp, "count": pre_count}

    existing_fps = await _existing_fingerprints()
    to_insert = []
    skipped = 0
    seen: set = set()
    for d in docs:
        core = _strip_backup_meta(d)
        # Ensure required fields exist to avoid inserting corrupt rows.
        if not all(k in core for k in ("date", "type", "account", "amount", "project_id")):
            continue
        fp = _fingerprint(core)
        if fp in existing_fps or fp in seen:
            skipped += 1
            continue
        seen.add(fp)
        core["fingerprint"] = fp
        core.setdefault("notes", "")
        core.setdefault("source", "restored_backup")
        core.setdefault("created_at", now_iso)
        core["restored_by"] = user["email"]
        core["restored_from"] = stamp
        to_insert.append(core)

    inserted = 0
    if to_insert:
        res = await db.transactions.insert_many(to_insert)
        inserted = len(res.inserted_ids)

    history_doc = {
        "filename": f"restore-from-{stamp}",
        "mode": f"restore_{mode}",
        "admin_email": user["email"],
        "started_at": now_iso,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "total_rows": len(docs),
        "invalid_rows": 0,
        "inserted": inserted,
        "skipped_duplicate": skipped,
        "backup_stamp": auto_backup_ref["stamp"] if auto_backup_ref else None,
        "backed_up_count": auto_backup_ref["count"] if auto_backup_ref else 0,
        "restored_from": stamp,
    }
    hist_res = await db.import_history.insert_one(history_doc)

    return {
        "ok": True,
        "mode": mode,
        "restored_from": stamp,
        "inserted": inserted,
        "skipped_duplicate": skipped,
        "history_id": str(hist_res.inserted_id),
        "auto_backup": auto_backup_ref,
    }


# --- Seeding ---
async def _seed_admin_user() -> str:
    admin_email = os.environ["ADMIN_EMAIL"].lower().strip()
    admin_password = os.environ["ADMIN_PASSWORD"]
    existing = await db.users.find_one({"email": admin_email})
    if not existing:
        await db.users.insert_one({
            "email": admin_email, "password_hash": hash_password(admin_password),
            "name": "Sandeep", "role": "admin",
            "created_at": datetime.now(timezone.utc).isoformat()
        })
    elif not verify_password(admin_password, existing["password_hash"]):
        await db.users.update_one({"email": admin_email},
                                  {"$set": {"password_hash": hash_password(admin_password)}})
    return admin_email


async def _seed_meta():
    meta_path = ROOT_DIR / "seed_meta.json"
    if not meta_path.exists():
        return
    meta = json.loads(meta_path.read_text())
    if meta.get("projects") and await db.projects.count_documents({}) == 0:
        await db.projects.insert_many(meta["projects"])
    if meta.get("accounts") and await db.accounts.count_documents({}) == 0:
        await db.accounts.insert_many([{"name": a} for a in meta["accounts"]])
    if meta.get("project_ids") and await db.project_ids.count_documents({}) == 0:
        await db.project_ids.insert_many([{"code": p, "description": ""} for p in meta["project_ids"]])


async def _seed_transactions(admin_email: str):
    txn_path = ROOT_DIR / "seed_transactions.json"
    if not txn_path.exists() or await db.transactions.count_documents({}) > 0:
        return
    txns = json.loads(txn_path.read_text())
    now = datetime.now(timezone.utc).isoformat()
    docs = [{
        "date": t["date"] or now,
        "type": t["type"],
        "account": t["account"],
        "amount": t["amount"],
        "project_id": t["project_id"],
        "notes": t.get("notes", ""),
        "created_at": now,
        "created_by": admin_email,
        "source": "excel_import",
    } for t in txns]
    if docs:
        await db.transactions.insert_many(docs)


async def seed_all():
    admin_email = await _seed_admin_user()
    await _seed_meta()
    await _seed_transactions(admin_email)


@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    await db.transactions.create_index("date")
    await db.transactions.create_index("type")
    await db.transactions.create_index("project_id")
    await db.forecast.create_index([("year", 1), ("month", 1)], unique=True)
    await db.sales_forecast.create_index([("year", 1), ("month", 1)])
    await db.sales_forecast.create_index("project_id")
    await db.quotations.create_index([("expected_year", 1), ("expected_month", 1)])
    await db.quotations.create_index("status")
    await db.quotations.create_index("quotation_number", unique=True)
    await db.budgets.create_index([("year", 1), ("account", 1)], unique=True)
    await db.budgets.create_index("account")
    await db.transactions.create_index("fingerprint")
    await db.transaction_import_backups.create_index("_backup_stamp")
    await db.import_history.create_index("completed_at")
    await seed_all()


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
