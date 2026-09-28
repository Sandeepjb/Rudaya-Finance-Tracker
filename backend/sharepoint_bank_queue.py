"""Background SharePoint -> Finance Tracker bank queue bridge.

Transport only. All parsing, idempotency, duplicate detection, classification and
pending-inbox creation are delegated to bank_inbox_phase2.process_queue_message().

Hardening (this module owns it):
  * bank allowlist  – only banks in SHAREPOINT_BANK_ALLOWLIST (default hdfc,saraswat) are processed;
                      everything else (incl. ICICI) is marked Ignored in SharePoint and never enters the inbox.
  * relevance gate  – OTP / promo / statement-ready / failed-transaction mails from an allowed bank are
                      marked Ignored instead of polluting needs_parsing_review.
  * safe email body – large HTML bodies are stripped + capped BEFORE Pydantic validation.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger("sharepoint_bank_queue")
GRAPH = "https://graph.microsoft.com/v1.0"
DEFAULT_BANK_ALLOWLIST = "hdfc,saraswat"


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int((os.getenv(name) or "").strip() or default))
    except ValueError:
        logger.warning("Invalid integer for %s; using default %s", name, default)
        return max(minimum, default)


def _config() -> Dict[str, Any]:
    allow = os.getenv("SHAREPOINT_BANK_ALLOWLIST", DEFAULT_BANK_ALLOWLIST)
    return {
        "enabled": _bool("SHAREPOINT_BANK_QUEUE_ENABLED", False),
        "tenant": os.getenv("M365_TENANT_ID", "").strip(),
        "client": os.getenv("M365_CLIENT_ID", "").strip(),
        "secret": os.getenv("M365_CLIENT_SECRET", "").strip(),
        "site": os.getenv("SHAREPOINT_SITE_ID", "").strip(),
        "list_id": os.getenv("SHAREPOINT_BANK_QUEUE_LIST_ID", "").strip(),
        "interval": _int("SHAREPOINT_BANK_QUEUE_INTERVAL_SECONDS", 120, 30),
        "max_retries": _int("SHAREPOINT_BANK_QUEUE_MAX_RETRIES", 5, 1),
        "allowlist": {b.strip().lower() for b in allow.split(",") if b.strip()},
        "ignored_status": os.getenv("SHAREPOINT_BANK_QUEUE_IGNORED_STATUS", "Ignored").strip() or "Ignored",
    }


def _token(c: Dict[str, Any]) -> str:
    response = requests.post(
        f"https://login.microsoftonline.com/{c['tenant']}/oauth2/v2.0/token",
        data={
            "client_id": c["client"],
            "client_secret": c["secret"],
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def _headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _get_items(c: Dict[str, Any], token: str) -> list:
    fields = (
        "Title,Subject,Sender,Sender0,BankName,SourceMessageId,InternetMessageId,"
        "ReceivedDateTime,EmailBodyText,ProcessingStatus,RetryCount"
    )
    url = f"{GRAPH}/sites/{c['site']}/lists/{c['list_id']}/items?expand=fields(select={fields})"
    items = []
    while url:
        response = requests.get(url, headers=_headers(token), timeout=30)
        response.raise_for_status()
        payload = response.json()
        items.extend(payload.get("value", []))
        url = payload.get("@odata.nextLink")
    return items


def _patch_fields(c: Dict[str, Any], token: str, item_id: str, values: dict) -> None:
    url = f"{GRAPH}/sites/{c['site']}/lists/{c['list_id']}/items/{item_id}/fields"
    response = requests.patch(url, headers=_headers(token), json=values, timeout=30)
    response.raise_for_status()


def _queue_message(fields: dict, item_id: str):
    # Local import avoids circular import during server/bank_inbox startup.
    from bank_inbox_phase2 import QueueMessageIn, QUEUE_BODY_MAX
    from bank_parsers.base import clean_email_body

    return QueueMessageIn(
        source_message_id=(fields.get("SourceMessageId") or "").strip()[:300],
        internet_message_id=(fields.get("InternetMessageId") or "").strip()[:300],
        sender=(fields.get("Sender") or fields.get("Sender0") or "").strip()[:300],
        subject=(fields.get("Subject") or fields.get("Title") or "").strip()[:500],
        received_at=(fields.get("ReceivedDateTime") or "").strip()[:40],
        email_body_text=clean_email_body(fields.get("EmailBodyText") or "", QUEUE_BODY_MAX),
        bank_hint=(fields.get("BankName") or "").strip()[:100],
        source="sharepoint",
        queue_item_id=str(item_id),
        idempotency_key=f"sharepoint:{item_id}",
    )


def triage(m, allowlist: set) -> Optional[str]:
    """Return None when the message should be parsed, else a short reason for ignoring it.
    Bank identity comes from the existing parser registry (hint > sender > subject > body keywords)."""
    from bank_parsers import ParseContext
    from bank_parsers.base import looks_like_transaction
    from bank_parsers.registry import identify_bank

    ctx = ParseContext(body=m.email_body_text, subject=m.subject, sender=m.sender, bank_hint=m.bank_hint,
                       received_at=m.received_at)
    bank = identify_bank(ctx)
    if not bank:
        return "unsupported bank: unidentified"
    if bank not in allowlist:
        return f"unsupported bank: {bank}"
    if not looks_like_transaction(ctx.text):
        return "not a transaction alert"
    return None


async def run_once(db) -> Dict[str, int]:
    from bank_inbox_phase2 import process_queue_message

    c = _config()
    if not c["enabled"]:
        return {"disabled": 1}
    if not all((c["tenant"], c["client"], c["secret"], c["site"], c["list_id"])):
        raise RuntimeError("SharePoint bank queue enabled but M365/SharePoint environment settings are incomplete")

    token = await asyncio.to_thread(_token, c)
    items = await asyncio.to_thread(_get_items, c, token)
    stats = {"seen": len(items), "eligible": 0, "processed": 0, "duplicate": 0, "parse_failed": 0,
             "ignored": 0, "failed": 0}

    for item in items:
        item_id = str(item.get("id") or "")
        fields = item.get("fields") or {}
        status = fields.get("ProcessingStatus") or "New"
        retries = int(fields.get("RetryCount") or 0)
        if not item_id or status != "New" or retries >= c["max_retries"]:
            continue
        stats["eligible"] += 1
        try:
            await asyncio.to_thread(_patch_fields, c, token, item_id, {"ProcessingStatus": "Processing"})
            msg = _queue_message(fields, item_id)
            reason = triage(msg, c["allowlist"])
            if reason:
                # Never enters the inbox, never consumes retries, never lands in needs_parsing_review.
                logger.info("SharePoint bank queue item %s ignored (%s)", item_id, reason)
                await asyncio.to_thread(
                    _patch_fields, c, token, item_id,
                    {"ProcessingStatus": c["ignored_status"],
                     "ProcessedDateTime": datetime.now(timezone.utc).isoformat(),
                     "ProcessingMessage": f"Ignored by finance worker: {reason}"[:1000]},
                )
                stats["ignored"] += 1
                continue
            result = await process_queue_message(msg, "sharepoint_worker")
            pipeline_status = result.get("parsing_status")
            bank_txn_id = result.get("bank_transaction_id") or (result.get("transaction") or {}).get("id") or ""
            if pipeline_status == "pending":
                sp_status, stat_key = "Processed", "processed"
            elif pipeline_status == "duplicate":
                sp_status, stat_key = "Duplicate", "duplicate"
            elif pipeline_status == "parse_failed":
                sp_status, stat_key = "Parse Failed", "parse_failed"
            else:
                raise RuntimeError(f"Unexpected bank queue pipeline status: {pipeline_status!r}")

            await asyncio.to_thread(
                _patch_fields, c, token, item_id,
                {
                    "ProcessingStatus": sp_status,
                    "ProcessedDateTime": datetime.now(timezone.utc).isoformat(),
                    "FinanceBankTransactionId": str(bank_txn_id),
                    "ProcessingMessage": f"Finance queue result: {pipeline_status}"[:1000],
                },
            )
            stats[stat_key] += 1
        except Exception as exc:
            stats["failed"] += 1
            logger.exception("SharePoint bank queue item %s failed", item_id)
            next_retries = retries + 1
            try:
                await asyncio.to_thread(
                    _patch_fields, c, token, item_id,
                    {
                        "ProcessingStatus": "Failed" if next_retries >= c["max_retries"] else "New",
                        "RetryCount": next_retries,
                        # Intentionally do not expose exception text or credentials in SharePoint.
                        "ProcessingMessage": f"Worker technical failure ({type(exc).__name__}); retry {next_retries}/{c['max_retries']}",
                    },
                )
            except Exception:
                logger.exception("Could not update SharePoint failure state for item %s", item_id)
    return stats


async def worker_loop(db, stop_event: asyncio.Event) -> None:
    try:
        c = _config()
    except Exception:
        logger.exception("SharePoint bank queue worker could not read configuration; worker not started")
        return
    if not c["enabled"]:
        logger.info("SharePoint bank queue worker disabled")
        return
    logger.info("SharePoint bank queue worker started; interval=%ss; banks=%s", c["interval"], sorted(c["allowlist"]))
    while not stop_event.is_set():
        try:
            logger.info("SharePoint bank queue cycle: %s", await run_once(db))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("SharePoint bank queue cycle failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=c["interval"])
        except asyncio.TimeoutError:
            pass
