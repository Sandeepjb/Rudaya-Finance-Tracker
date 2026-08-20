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

## Backlog / Next
- P1: Brute-force login lockout (5 attempts / 15 min → 423)
- P1: Excel `.xlsx` export mirroring the original template + new Forecast sheet
- P2: Copy-last-year button in Sales Forecast
- P2: Project drill-down page
- P2: Attachments (invoice PDFs) via object storage
- P3: Match cookie attributes on `delete_cookie` (secure/samesite) on logout
