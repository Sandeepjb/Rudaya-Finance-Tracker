# Rudaya Powers Pvt. Ltd. — Finance Tracker (PRD)

## Original Problem
"prepare a web based application to track my business financial entries as per the excel template" (Rudaya Powers Pvt. Ltd. Finance Tracker — .xlsm)

## User Choices
- Users: small team, everyone sees everything (JWT email/password auth, cookie-only)
- Modules: Dashboard, Transactions, Sales Forecast, Forecast vs Actual, Project P&L, Monthly, Settings
- Pre-load historical data from uploaded Excel: yes (120 transactions, 16 projects, 37 accounts, 107 project IDs)
- Currency: Indian Rupee ₹
- Brand: Rudaya Powers Pvt. Ltd. — real logo displayed on Login + Sidebar

## Core Modules
- Transaction (date, type ∈ {Revenue, Cost, Expense}, account, amount, project_id, notes)
- Sales Forecast (month-wise line items, optional project_id, amount, notes)
- Consolidated Forecast vs Actual (auto-sums sales_forecast per month vs actual Revenue)
- Project-wise P&L, Monthly report
- Master data: Projects, Project IDs, Accounts

## Implemented (2026-08-20)
- FastAPI backend: JWT httpOnly-cookie auth, `/api/auth/*`, `/api/transactions`, `/api/meta`, `/api/reports/*`,
  `/api/forecast` (legacy month-only upsert), `/api/sales-forecast` (line-item CRUD)
- MongoDB collections: `users`, `transactions`, `projects`, `accounts`, `project_ids`, `forecast` (legacy), `sales_forecast` (new)
- Excel seed on startup: admin user + 16 projects + 37 accounts + 107 project IDs + 120 transactions
- Consolidation rule: `sales_forecast` sums per month override legacy `forecast` docs; report exposes `line_items` count
- React frontend (Swiss / Industrial ERP style): Login, Dashboard, Transactions (drawer CRUD + filters + CSV), Sales Forecast (drawer CRUD + monthly totals strip), Forecast vs Actual (read-only consolidation + chart + achievement trend), Project P&L, Monthly, Settings
- Rudaya Powers logo on Login hero + Sidebar
- Cookie-only auth (localStorage tokens removed); explicit CORS_ORIGINS

## Test History
- iteration_1: 100% pass
- iteration_2: 100% frontend / 95% backend (missing brute-force lockout only)
- iteration_3: sales-forecast backend 16/16, consolidation math verified, UI e2e drawer flow verified
- iteration_4 (2026-09-26): Admin-only CSV Import feature — frontend 100% pass, backend 50/50 pass (incl. new 7-test suite for migrations + brute-force lockout regression closed)

## Implemented (2026-09-26) — Admin-only CSV Import (Data Migration)
- Backend: `POST /api/migrations/preview` (validates date/type/positive-amount/required fields; supports YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY dates; flags DB + in-file duplicates via SHA-256 fingerprint of date|type|account|amount|project_id|notes)
- Backend: `POST /api/migrations/import` (`mode=skip_duplicates` | `replace_existing`); replace-mode backs every existing txn up to `transaction_import_backups` with a timestamp + admin email BEFORE wiping the collection; every run recorded in `import_history`
- Backend: `GET /api/migrations/history` (audit trail; admin-only)
- Backend: `require_admin` dependency gates all migration routes (403 for members)
- Backend: Brute-force login lockout — 5 failed attempts / 15 min → HTTP 423 (in-memory per-email)
- Frontend: Sidebar Administration section + `/admin/data-migration` route
- Frontend: 3-step wizard (Upload → Preview with summary tiles + row table + show-invalid toggle → Choose mode + Import → Result)
- Frontend: Non-admin block card with Prohibit icon (page is discoverable but not usable for members)
- Tests: `/app/backend/tests/test_migrations.py` (7 tests) + updated conftest.py with a filelock to serialize the destructive replace test against report-reading tests

## Backlog / Next
- P1: Excel `.xlsx` export mirroring the original template + new Forecast sheet
- P2: Copy-last-year button in Sales Forecast
- P2: Project drill-down page (click a project in Project P&L to see its transactions + forecast chart)
- P2: Edit-before-approve for AI-proposed transactions
- P2: Attachments (invoice PDFs) via object storage
- P3: Match cookie attributes on `delete_cookie` (secure/samesite) on logout
- P3: AI Explain-Row for anomalies in Project P&L / Forecast
- P3: Custom AI wake word & Hindi voice support
- P3: 30-second undo toast after AI approval
