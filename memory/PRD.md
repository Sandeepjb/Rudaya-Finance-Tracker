# Rudaya Powers Pvt. Ltd. — Finance Tracker (PRD)

## Original Problem
"prepare a web based application to track my business financial entries as per the excel template" (Rudaya Powers Pvt. Ltd. Finance Tracker — .xlsm)

## User Choices
- Users: small team, everyone sees everything (JWT email/password auth, cookie-only)
- Modules: Dashboard, Transactions, Sales Forecast, Forecast vs Actual, Project P&L, Monthly, Settings, Yearly Expense Budget, Quotations, AI Assistant, Administration (Data Migration)
- Pre-load historical data from uploaded Excel: yes (120 transactions, 16 projects, 37 accounts, 107 project IDs)
- Currency: Indian Rupee ₹
- Brand: Rudaya Powers Pvt. Ltd. — real logo displayed on Login + Sidebar
- Administration section is always visible in the sidebar; non-admins see an "Admin only" block on gated pages.

## Core Modules
- Transaction (date, type ∈ {Revenue, Cost, Expense}, account, amount, project_id, notes)
- Sales Forecast (month-wise line items with optional project_id + type)
- Quotations (with Revenue/Cost/Expense line items; number is unique)
- Consolidated Forecast vs Actual (auto-sums sales_forecast + non-lost quotations per month vs actual)
- Project-wise P&L, Monthly report
- Master data: Projects, Project IDs, Accounts (SoT for Budgets + Import)
- Yearly Expense Budget vs Actual per Settings account
- AI Assistant (Claude Sonnet 4.6 streaming with approval-gated write actions + voice STT/TTS)
- Administration → Data Migration: Admin-only CSV import, dry-run P&L impact, backups & restore

## Test History
- iteration_1: 100% pass
- iteration_2: 100% frontend / 95% backend (brute-force lockout regression, since fixed)
- iteration_3: sales-forecast backend 16/16, consolidation math verified, UI e2e drawer flow verified
- iteration_4 (2026-09-26): Admin-only CSV Import — frontend 100% pass, backend 50/50 pass (added migration test suite + fixed brute-force + test race)
- iteration_5 (2026-09-26): Dry-run P&L Impact + Backups & Restore — 57/57 backend pass

## Implemented (2026-09-26) — Admin CSV Import + P1 enhancements
- CSV Import (preview + import): validates date/type/amount/required fields; SHA-256 fingerprint dedup (DB + in-file); Skip duplicates | Replace existing (auto-backup)
- Brute-force login lockout (5 fails / 15 min → 423) — per-email in-memory
- **Dry-run P&L Impact** dialog: month-by-month Revenue / Cost / Expense / Net for years touched by the CSV; shows before + after + delta + Net-Δ sparklines; scoped per year via tabs; correctly zeros the "before" in replace-existing mode
- **Backups & Restore** tab under Data Migration: lists every snapshot from `transaction_import_backups` (Rev/Cost/Expense totals, count, admin, timestamp); preview any snapshot; **Merge** restore (idempotent, insert only new fingerprints) OR **Full restore** (auto-backs up current state first, then wipes & inserts snapshot fresh); every restore recorded in `import_history` with mode `restore_merge` or `restore_full`
- All admin-only routes gated by a shared `require_admin` FastAPI dependency
- Tests: /app/backend/tests/test_migrations.py + test_migrations_extras.py (14 tests); conftest.py filelock serializes destructive tests against report readers

## Backlog / Next
- P2: **Project Drilldown** — click a project in Project P&L to open its transactions + a forecast-vs-actual chart (SF + non-lost quotations scoped to the project)
- P2: **Copy Last Year Forecast** — one-tap button on Sales Forecast that clones last year's line items into next year (SF only + optional "also copy open quotations" checkbox)
- P1: Excel `.xlsx` export mirroring the original template + a Forecast sheet
- P2: Edit-before-approve for AI-proposed transactions
- P2: Attachments (invoice PDFs) via object storage
- P3: Match cookie attributes on `delete_cookie` (secure/samesite) on logout
- P3: AI Explain-Row for anomalies in Project P&L / Forecast
- P3: Custom AI wake word & Hindi voice support
- P3: 30-second undo toast after AI approval
