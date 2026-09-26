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

## Implemented (2026-09-26) — batch 5: Bank Transaction Inbox (Phase 1)
- User choices: ingest auth = static `X-Ingest-Key` header (env `BANK_INGEST_API_KEY`); UI admin-only; code in separate `backend/bank_inbox.py`; AI fallback threshold 70%.
- Route `/bank-transactions` (sidebar "Bank Transactions", admin-only). Tabs: Pending / Approved / Rejected / Duplicates / All / Mapping Rules / Ingestion History. Card + table views, 11 filters.
- Collections: `bank_transactions`, `bank_mapping_rules`, `bank_audit_log`, `bank_ingestion_log` (indexes in `bank_inbox.ensure_indexes`).
- Endpoints (`/api/bank-transactions`): `POST /ingest` (X-Ingest-Key, batch ≤100), `POST /manual` (admin), `GET ""` (filters), `GET /stats`, `GET /rules`, `PUT/DELETE /rules/{id}`, `GET /ingestion-history`, `GET /{id}`, `GET /{id}/audit`, `PUT /{id}` (edit before approve), `POST /{id}/approve|reject|reclassify`.
- Classification: L1 learned rule (pattern=merchant key, conf=50+12·uses−6·corrections, used if ≥70) → L2 historical similarity over `transactions` (0.6 token overlap + 0.2 amount + 0.2 merchant; weighted vote; conf=top_sim·70+consensus·30) → L3 Claude (only if <70; validated against master data; capped 85). No debit=expense assumption.
- Fingerprint: sha256(REF|bank|acct-last4|utr/ref|amount|direction) if reference exists, else (NAR|bank|acct|date|amount|direction|upper narration); plus source+source_message_id idempotency. Duplicates stored with status=duplicate + duplicate_of.
- Approval: shared `insert_finance_transaction()` (now used by manual, AI-approved and bank flows) → source="bank_transaction", bank_transaction_id link, reconciliation_status=matched; atomic status claim prevents double post. Learning via votes per pattern (one correction never overrides).
- Tests: `tests/test_bank_inbox.py` 35 tests; full suite 80/80. Frontend iteration_7 all pass.
- Known limitations: rules keyed on first 2 meaningful tokens; AI latency ~15s on manual ingest; ingestion history unpaginated.
- Phase 2 (NOT started, awaiting approval): Power Automate → POST /ingest with X-Ingest-Key, source="power_automate", source_message_id=Outlook message id; CSV bank statement import; bank reconciliation.

## Implemented (2026-09-26) — batch 6: Statement CSV, Email templates, Bulk approve, Excel export, CSV header fix
- `backend/bank_inbox_ext.py` (routes on the bank router, registered before `/{tid}`): `POST /statement/preview|import` (auto bank/column detection ICICI/HDFC/generic, manual mapping override, skips already-ingested fingerprints), `GET/POST/PUT/DELETE /templates`, `POST /templates/test`, `POST /ingest/email` (X-Ingest-Key; regex templates per bank, 422 + failed ingestion log if unparseable), `GET /guide` (Power Automate steps), `POST /bulk-approve` (per-row results, idempotent). `bank_parse_templates` collection seeded with ICICI/HDFC/Saraswat defaults.
- `backend/excel_export.py`: `GET /api/export/excel` → xlsx with Transactions, Project P&L, Monthly, Sales Forecast, Quotations, Quotation Lines, Expense Budget, Master Data. Button `export-excel-btn` on Transactions page.
- UI: Bank Transactions tabs Import Statement / Parsing Templates; bulk bar on Pending (checkboxes, Select all ≥90%); PA guide in Ingestion History.
- Bug fix: `_parse_csv_rows` header normalisation now `"_".join(h.strip().lower().split())` so "Project ID" → project_id (test `tests/test_csv_headers.py`). Bank edit with blank notes falls back to narration.
- Tests: 100/100 backend (tests now use per-xdist-worker tags + txn_state_lock to avoid cross-worker pollution); frontend iteration_8 all pass. No tabs in any .py.
- Phase 2 remaining: actual Power Automate flow on the customer tenant (guide provided), Bank Reconciliation module.

## Implemented (2026-09-26) — batch 7: Phase 2 M365 queue readiness, Reconciliation, PDF import
- `backend/bank_parsers/` (base, icici, hdfc, saraswat, generic, registry): pluggable parsers → normalized output incl. transaction_time, currency, merchant_name, utr_reference, parser_name/version. Selection: bank_hint(+100) > trusted sender(+50) > subject(+15) > body keywords(+10) > generic; exposes selection_method / selection_confidence. HTML→text tolerant.
- `backend/bank_inbox_phase2.py`: `POST /api/bank-transactions/queue` (X-Ingest-Key + optional X-Idempotency-Key; payload supports source_message_id / internet_message_id / recipient / received_datetime / email_body_text|html / bank_hint / source / queue_item_id / idempotency_key). Pipeline: validate → source-id/idempotency replay (returns existing result, no new item, audited) → parse → ingest_one (fingerprint dup + classify) → pending. Statuses received/parsed/parse_failed/duplicate/pending in `bank_queue_messages`; `GET /queue`, `/queue/stats`, `/queue/{id}`, `/queue/{id}/resolve|discard`; `POST /parsers/test`, `POST /parsers/submit`, `GET /parsers`.
- Reconciliation: `GET /reconciliation/summary|/reconciliation|/reconciliation/unmatched-finance`, `POST /{id}/reconcile/match|unmatch|ignore`, `POST /reconciliation/auto`; candidates ±3 days, ±2% amount; statuses matched/partially_matched/unmatched/ignored; startup backfill marks legacy approved+linked as matched.
- PDF statements: `POST /statement/pdf/preview|import` (pdfplumber text extraction; scanned PDFs rejected with message).
- UI tabs: M365 Queue (Needs Parsing Review + Resolve/Discard), Parser Test (+ Send to Bank Inbox), Reconciliation; Import Statement accepts PDF.
- Constant-time ingest-key compare (hmac); 401 body no longer hints at key. Env vars: none new (BANK_INGEST_API_KEY reused; PUBLIC_API_BASE_URL optional for guide).
- Tests: 120/120 backend (`tests/test_bank_phase2.py` 20 tests), frontend iteration_9.
- Not done (by design): configuring M365/Power Automate/SharePoint; OCR for scanned PDFs; bank-specific parser refinement pending real samples.

## Backlog / Next
- P1 (approved for later): Phase 2 Power Automate / SharePoint ingestion; Bank Reconciliation
- P1: Excel `.xlsx` export mirroring the original template + a Forecast sheet
- P2: Compare Projects mode on Project P&L (multi-select drilldown)
- P3: Match cookie attributes on `delete_cookie` on logout
- P3: AI Explain-Row for anomalies
- P3: Custom AI wake word & Hindi voice support
- P3: 30-second undo toast after AI approval
- P3: Image-attachment support (JPEG/PNG for site photos)
