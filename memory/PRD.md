# Rudaya Powers Pvt. Ltd. — Finance Tracker (PRD)

## Original Problem
"prepare a web based application to track my business financial entries as per the excel template" (Rudaya Powers Pvt. Ltd. Finance Tracker — .xlsm)

## User Choices
- Users: small team, everyone sees everything (JWT email/password auth, cookie-only)
- Modules: Dashboard, Transactions, Sales Forecast, Forecast vs Actual, Project P&L, Monthly, Settings, Yearly Expense Budget, Quotations, AI Assistant, Administration (Data Migration)
- Pre-load historical data from uploaded Excel: yes (120 transactions, 16 projects, 37 accounts, 107 project IDs)
- Currency: Indian Rupee ₹
- Brand: Rudaya Powers Pvt. Ltd. — real logo displayed on Login + Sidebar
- Administration section is always visible in the sidebar; non-admins see an "Admin only" block on gated pages

## Core Modules
- Transaction / Sales Forecast / Quotations / Consolidated Forecast vs Actual / Project P&L with drilldown / Monthly / Master Data / Yearly Expense Budget / AI Assistant (Claude Sonnet 4.6) / Data Migration (Import + Backups + Restore + Dry-run P&L Impact)

## Test History
- iterations 1–6 covered core, sales forecast, data migration, CSV import, backups & restore, project drilldown / copy last year / backup P&L impact
- iteration 7 (2026-09-26): Edit-Before-Approve + PDF Attachments — 67/67 backend pass

## Implemented (2026-09-26) — batch 4: Edit-Before-Approve + PDF Attachments
- **Edit Before Approve**: New `PUT /api/ai/pending/{pid}` schema-validates edits against the target model. UI adds a "pencil" button on every pending AI proposal that opens a dialog to tweak amount / date / account / project / notes (transaction), amount / month / project (sales_forecast), or metadata (quotation) before approving. Approved records use the edited values.
- **PDF Invoice Attachments (Emergent object storage)**: Reusable `AttachmentsPanel` on the transaction and quotation drawers. Uploads up to 10 PDFs/entity, 10 MB each, with soft-delete + inline download. Backend uses the platform's `INTEGRATION_PROXY_URL` object storage: `POST /api/attachments/{entity_type}/{entity_id}`, `GET /api/attachments/{entity_type}/{entity_id}` (list), `GET /api/attachments/{attachment_id}/download` (JWT via header or `?auth=`), `DELETE /api/attachments/{attachment_id}` (soft delete). Route order fixed so `/download` isn't shadowed by the list route. Metadata mirrored to `db.attachments` with `is_deleted` flag.
- Tests: `/app/backend/tests/test_p3_features.py` — 2 test classes exercise PUT edit, schema validation, approve-after-edit, PDF-only enforcement, size / count limits, download auth, soft delete, and 404 paths.

## Backlog / Next
- P1: Excel `.xlsx` export mirroring the original template + a Forecast sheet
- P2: Compare Projects mode on Project P&L (multi-select drilldown)
- P3: Match cookie attributes on `delete_cookie` on logout
- P3: AI Explain-Row for anomalies
- P3: Custom AI wake word & Hindi voice support
- P3: 30-second undo toast after AI approval
- P3: Image-attachment support (JPEG/PNG for site photos)
