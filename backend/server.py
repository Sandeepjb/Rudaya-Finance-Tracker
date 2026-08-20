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

from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, Query
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr

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
    project_id: str = ""  # "" == unallocated / general
    amount: float
    notes: str = ""


def _sf_out(d: dict) -> dict:
    return {
        "id": str(d["_id"]),
        "year": d["year"], "month": d["month"],
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


@api_router.get("/reports/forecast-vs-actual")
async def forecast_vs_actual(user: dict = Depends(get_current_user), year: Optional[int] = None):
    """Consolidated: actual Revenue transactions vs summed Sales Forecast line-items per month.
    Legacy per-month `forecast` docs are added on top if a month has no sales_forecast entries."""
    year = year or datetime.now(timezone.utc).year
    # Actual revenue per month
    docs = await db.transactions.find({"type": "Revenue"}).to_list(20000)
    actual = {m: 0 for m in range(1, 13)}
    for d in docs:
        try:
            dt = datetime.fromisoformat(d["date"].replace("Z", ""))
        except Exception:
            continue
        if dt.year == year:
            actual[dt.month] = actual.get(dt.month, 0) + d["amount"]

    # Consolidated forecast from sales_forecast line items
    forecast = {m: 0 for m in range(1, 13)}
    line_counts = {m: 0 for m in range(1, 13)}
    async for sf in db.sales_forecast.find({"year": year}):
        m = sf["month"]
        if 1 <= m <= 12:
            forecast[m] += sf.get("amount", 0)
            line_counts[m] += 1

    # Backfill with legacy `forecast` docs only where sales_forecast has no entries
    legacy = await db.forecast.find({"year": year}).to_list(500)
    for f in legacy:
        m = f["month"]
        if 1 <= m <= 12 and line_counts[m] == 0:
            forecast[m] = f.get("amount", 0)

    rows = []
    for m in range(1, 13):
        rev = actual[m]
        fc = forecast[m]
        rows.append({
            "year": year, "month": m,
            "label": datetime(year, m, 1).strftime("%b"),
            "forecast": fc, "actual": rev,
            "variance": rev - fc,
            "achievement_pct": (rev / fc * 100) if fc else None,
            "line_items": line_counts[m],
        })
    return {"year": year, "rows": rows,
            "total_forecast": sum(forecast.values()),
            "total_actual": sum(actual.values())}


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


# --- Seeding ---
async def seed_all():
    # Users
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

    # Meta (projects / accounts / project_ids)
    meta_path = ROOT_DIR / "seed_meta.json"
    if meta_path.exists() and await db.projects.count_documents({}) == 0:
        meta = json.loads(meta_path.read_text())
        if meta.get("projects"):
            await db.projects.insert_many(meta["projects"])
    if meta_path.exists() and await db.accounts.count_documents({}) == 0:
        meta = json.loads(meta_path.read_text())
        if meta.get("accounts"):
            await db.accounts.insert_many([{"name": a} for a in meta["accounts"]])
    if meta_path.exists() and await db.project_ids.count_documents({}) == 0:
        meta = json.loads(meta_path.read_text())
        if meta.get("project_ids"):
            await db.project_ids.insert_many([{"code": p, "description": ""} for p in meta["project_ids"]])

    # Transactions
    txn_path = ROOT_DIR / "seed_transactions.json"
    if txn_path.exists() and await db.transactions.count_documents({}) == 0:
        txns = json.loads(txn_path.read_text())
        docs = []
        for t in txns:
            docs.append({
                "date": t["date"] or datetime.now(timezone.utc).isoformat(),
                "type": t["type"],
                "account": t["account"],
                "amount": t["amount"],
                "project_id": t["project_id"],
                "notes": t.get("notes", ""),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "created_by": admin_email,
                "source": "excel_import",
            })
        if docs:
            await db.transactions.insert_many(docs)


@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    await db.transactions.create_index("date")
    await db.transactions.create_index("type")
    await db.transactions.create_index("project_id")
    await db.forecast.create_index([("year", 1), ("month", 1)], unique=True)
    await db.sales_forecast.create_index([("year", 1), ("month", 1)])
    await db.sales_forecast.create_index("project_id")
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
