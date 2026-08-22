from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

import os
import json
import logging
import bcrypt
import jwt
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, Query
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
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
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


# --- AI Assistant (Claude) ---
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
AI_MODEL = ("anthropic", "claude-sonnet-4-6")

AI_SYSTEM_PROMPT = (
    "You are RudayaAI, a concise financial insights assistant for Rudaya Powers Pvt. Ltd. "
    "You have access to live company financial data (transactions, monthly totals, forecast vs actual by type, "
    "project-wise P&L, and quotations). All amounts are Indian Rupees; format as ₹ with Indian grouping "
    "(e.g. ₹12,34,567) and use L/Cr shorthand (₹5.5L, ₹1.2Cr) when helpful. "
    "Be direct — give the answer first, then a short explanation. Use bullet points when listing. "
    "If the user asks a question the data doesn't cover, say so plainly. Never invent numbers."
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
            await db.ai_messages.insert_one({
                "session_id": session_id, "role": "assistant", "content": full,
                "user_email": user["email"],
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            yield f"data: {json.dumps({'done': True, 'session_id': session_id})}\n\n"
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
