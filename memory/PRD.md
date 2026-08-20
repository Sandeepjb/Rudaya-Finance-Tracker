# Rudaya Power Pvt. Ltd. — Finance Tracker (PRD)

## Original Problem
"prepare a web based application to track my business financial entries as per the excel template" (Rudaya Power Pvt. Ltd. Finance Tracker — .xlsm)

## User Choices
- Users: small team, everyone sees everything (JWT email/password auth)
- Modules on Day-1: Dashboard, Transactions, Project P&L, Monthly Revenue vs Expense, Settings
- Pre-load historical data from uploaded Excel: **yes** (120 transactions, 16 projects, 37 accounts, 107 project IDs)
- Currency: Indian Rupee ₹

## Personas
- **Owner / Admin (Sandeep)** — reviews KPIs, project P&L, adds transactions
- **Team member** — adds/edits transactions, sees the same reports

## Core Requirements (static)
- Transaction has: date, type ∈ {Revenue, Cost, Expense}, account, amount, project_id, notes
- Reports: totals, monthly revenue/cost/expense/net, project-wise P&L
- Manageable master data: Projects, Project IDs, Accounts

## Implemented (2026-08-20)
- FastAPI backend: JWT auth (bcrypt + cookie/bearer), `/api/auth/*`, `/api/transactions`, `/api/meta`, `/api/reports/*`
- MongoDB seed on startup: admin user, 16 projects, 37 accounts, 107 project IDs, 120 historical transactions from Excel
- React frontend (Swiss / Industrial ERP design): Login, Dashboard, Transactions (drawer add/edit + filters + CSV export), Project P&L, Monthly, Settings
- Font stack: Outfit / IBM Plex Sans / JetBrains Mono; Phosphor icons; INR ₹ Indian formatting
- Tested end-to-end (iteration_1): 100% pass on backend + frontend

## Backlog / Next Tasks
- P1: Excel `.xlsx` export (mirror the exact template columns)
- P1: Multi-year support and year selector on Monthly / Dashboard
- P2: Per-project drill-down page with transaction list & mini P&L
- P2: Role-based permissions (view-only vs editor) if team grows
- P2: Attachments (invoice PDFs) on transactions via object storage
