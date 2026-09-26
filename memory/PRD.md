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
- Consolidated Forecast vs Actual (SF + non-lost quotations vs actuals per month by type)
- Project-wise P&L with **click-through drilldown** (transactions + forecast-vs-actual chart + quotations scoped to that project)
- Monthly report
- Master data: Projects, Project IDs, Accounts (SoT for Budgets + Import)
- Yearly Expense Budget vs Actual per Settings account
- AI Assistant (Claude Sonnet 4.6 streaming with approval-gated write actions + voice STT/TTS)
- Administration → Data Migration: Admin-only CSV import, dry-run P&L impact, backups & restore (with P&L Impact preview)

## Test History
- iteration_1: 100% pass
- iteration_2: 100% frontend / 95% backend (brute-force lockout regression, since fixed)
- iteration_3: sales-forecast backend 16/16, consolidation math verified, UI e2e drawer flow verified
- iteration_4 (2026-09-26): Admin-only CSV Import — frontend 100% pass, backend 50/50 pass
- iteration_5 (2026-09-26): Dry-run P&L Impact + Backups & Restore — 57/57 backend pass
- iteration_6 (2026-09-26): Project Drilldown + Copy Last Year + Backup P&L Impact — 65/65 backend pass

## Implemented (2026-09-26) — Batch of P1/P2 enhancements
- **Admin CSV Import**: preview + import; SHA-256 fingerprint dedup (DB + in-file); Skip duplicates | Replace existing (auto-backup)
- Brute-force login lockout (5 fails / 15 min → 423)
- **Dry-run P&L Impact** on CSV: rich per-year dialog with month-by-month before + after + delta + Net-Δ sparklines
- **Backups & Restore**: list every snapshot (`transaction_import_backups`), preview rows, **Merge** (idempotent) or **Full restore** (auto-backs up current state first). Every restore recorded in `import_history` with mode `restore_merge`/`restore_full`
- **Project Drilldown** (P2): click any row in Project P&L → right-side sheet with tiles, Recharts line/bar charts of forecast vs actual (scoped to project · SF + non-lost quotations), full transactions table, quotations table
- **Copy Last Year Forecast** (P2): one-tap dialog on Sales Forecast to clone last year's SF into next year, with optional quotation cloning (draft, `-COPYYYYY` suffix) and an overwrite toggle
- **Backup P&L Impact** (P2 stretch): `POST /migrations/backups/{stamp}/dry-run mode=merge|full` — reuses the same rich P&L impact dialog so admins preview a restore's effect before committing
- All admin-only routes gated by a shared `require_admin` FastAPI dependency
- Tests: /app/backend/tests/test_migrations.py + test_migrations_extras.py + test_p2_features.py (22 focused tests); conftest.py filelock serializes destructive tests against report readers

## Backlog / Next
- P1: Excel `.xlsx` export mirroring the original template + a Forecast sheet
- P2: Edit-before-approve for AI-proposed transactions
- P2: Attachments (invoice PDFs) via object storage
- P3: Match cookie attributes on `delete_cookie` (secure/samesite) on logout
- P3: AI Explain-Row for anomalies in Project P&L / Forecast
- P3: Custom AI wake word & Hindi voice support
- P3: 30-second undo toast after AI approval
