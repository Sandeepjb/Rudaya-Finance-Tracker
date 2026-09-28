"""SharePoint bank queue hardening: allowlist, relevance gate, safe HTML bodies, HDFC/Saraswat parsing.
Pure unit tests — Microsoft Graph is stubbed, no network."""
import asyncio
import sys

import pytest

sys.path.insert(0, "/app/backend")

from bank_parsers import ParseContext, parse_alert  # noqa: E402
from bank_parsers.base import clean_email_body, looks_like_transaction  # noqa: E402
from bank_parsers.registry import identify_bank  # noqa: E402
import sharepoint_bank_queue as sq  # noqa: E402

HDFC_DEBIT = ("Dear Customer, Rs.1500.00 has been debited from account **4321 to VPA swiggy@ybl SWIGGY on 12-06-26. "
              "Your UPI transaction reference number is 516712345678.")
HDFC_NEFT = ("Update! INR 55,000.00 deposited in HDFC Bank A/c XX4321 on 12-JUN-26 for NEFT Cr-ICIC0000001-ACME PVT LTD-"
             "RUDAYA POWER-HDFCN52345678901. Avl bal INR 1,20,000.00")
SARASWAT_DEBIT = ("Your A/c XXXX0319 is debited by Rs.12,500.00 on 12-06-2026 towards UPI/516734567890/Tata Power. "
                  "Avl Bal Rs.3,45,000.00 CR. Saraswat Bank")
SARASWAT_CREDIT = "Dear Customer, Your A/c XXXX0319 is credited with INR 80,000.00 on 11/06/2026 by NEFT from Reliance Energy Ltd. Ref SBIN12345678. Saraswat Bank"
ICICI = "ICICI Bank Acct XX123 debited for Rs 900.00 on 12-Jun-26; UPI Ref 51670001; Info: BLINKIT"
OTP = "Dear Customer, 482913 is your OTP for HDFC Bank NetBanking transaction of Rs.5,000.00 to be debited. Do not share."
PROMO = "Pre-approved personal loan of Rs.5,00,000 from HDFC Bank. Apply now!"


def _msg(body, subject="", sender="alerts@hdfcbank.net", hint=""):
    from bank_inbox_phase2 import QueueMessageIn
    return QueueMessageIn(source_message_id="msg-1", sender=sender, subject=subject, email_body_text=body,
                          bank_hint=hint, source="sharepoint", queue_item_id="1", idempotency_key="sharepoint:1")


class TestBody:
    def test_large_html_is_capped_and_cleaned(self):
        html = "<html><head><style>a{}</style></head><body>" + "<div>x</div>" * 100000 + "<p>Rs.10 debited &amp; done</p></body></html>"
        out = clean_email_body(html, 20000)
        assert len(out) <= 20000 and "<" not in out and "&amp;" not in out

    def test_queue_message_never_fails_pydantic_on_big_html(self):
        html = "<p>Rs.10 debited from A/c 1234 on 12-06-26 to Shop.</p><table>" + "<tr><td>row</td></tr>" * 20000 + "</table>"
        m = sq._queue_message({"EmailBodyText": html, "SourceMessageId": "abc", "Subject": "Alert"}, "77")
        n = m.normalized()
        assert len(n.body) <= 20000 and n.body.startswith("Rs.10 debited from A/c 1234 on 12-06-26 to Shop.")

    def test_normalized_strips_html_in_body_field(self):
        m = _msg("<p>Rs.500.00 debited from A/c 1234 on 12-06-26 to Cafe.</p>")
        assert m.normalized().body.startswith("Rs.500.00 debited")


class TestRelevance:
    @pytest.mark.parametrize("t", [HDFC_DEBIT, HDFC_NEFT, SARASWAT_DEBIT, SARASWAT_CREDIT])
    def test_real_alerts_pass(self, t):
        assert looks_like_transaction(t)

    @pytest.mark.parametrize("t", [OTP, PROMO, "Your HDFC Bank statement is ready", "Hello team, meeting at 5", ""])
    def test_noise_rejected(self, t):
        assert not looks_like_transaction(t)


class TestAllowlist:
    def test_identify(self):
        assert identify_bank(ParseContext(body=HDFC_DEBIT, sender="alerts@hdfcbank.net")) == "hdfc"
        assert identify_bank(ParseContext(body=SARASWAT_DEBIT, sender="alerts@saraswatbank.com")) == "saraswat"
        assert identify_bank(ParseContext(body=ICICI, sender="alerts@icicibank.com")) == "icici"
        assert identify_bank(ParseContext(body="Rs.10 debited to Shop on 12-06-26", sender="x@y.z")) == ""

    def test_triage(self):
        allow = {"hdfc", "saraswat"}
        assert sq.triage(_msg(HDFC_DEBIT), allow) is None
        assert sq.triage(_msg(SARASWAT_CREDIT, sender="alerts@saraswatbank.com"), allow) is None
        assert sq.triage(_msg(ICICI, sender="alerts@icicibank.com"), allow) == "unsupported bank: icici"
        assert sq.triage(_msg(ICICI, sender="alerts@icicibank.com", hint="ICICI Bank"), allow) == "unsupported bank: icici"
        assert sq.triage(_msg("Rs.10 debited to Shop on 12-06-26", sender="x@y.z"), allow).startswith("unsupported bank")
        assert sq.triage(_msg(OTP), allow) == "not a transaction alert"
        assert sq.triage(_msg(ICICI, sender="a@icicibank.com"), {"hdfc", "saraswat", "icici"}) is None

    def test_config_defaults_and_bad_ints(self, monkeypatch):
        monkeypatch.setenv("SHAREPOINT_BANK_QUEUE_INTERVAL_SECONDS", "abc")
        monkeypatch.delenv("SHAREPOINT_BANK_ALLOWLIST", raising=False)
        c = sq._config()
        assert c["allowlist"] == {"hdfc", "saraswat"} and c["interval"] == 120 and c["ignored_status"] == "Ignored"


class TestParsers:
    def test_hdfc_upi(self):
        r = parse_alert(ParseContext(body=HDFC_DEBIT, sender="alerts@hdfcbank.net"))
        assert r.ok and r.fields["direction"] == "debit" and r.fields["amount"] == 1500.0
        assert r.fields["transaction_date"] == "2026-06-12" and "swiggy" in r.fields["narration"].lower()

    def test_hdfc_neft(self):
        r = parse_alert(ParseContext(body=HDFC_NEFT, sender="alerts@hdfcbank.net"))
        assert r.ok and r.fields["direction"] == "credit" and r.fields["amount"] == 55000.0
        assert r.fields["narration"].startswith("NEFT Cr") and "ACME" in r.fields["narration"]
        assert r.fields["transaction_date"] == "2026-06-12"

    def test_saraswat_debit(self):
        r = parse_alert(ParseContext(body=SARASWAT_DEBIT, sender="alerts@saraswatbank.com"))
        assert r.ok and r.fields["direction"] == "debit" and r.fields["amount"] == 12500.0
        assert r.fields["narration"].startswith("UPI/516734567890/Tata Power")
        assert r.parser == "saraswat"

    def test_saraswat_credit(self):
        r = parse_alert(ParseContext(body=SARASWAT_CREDIT, sender="alerts@saraswatbank.com"))
        assert r.ok and r.fields["direction"] == "credit" and r.fields["amount"] == 80000.0
        assert "Reliance Energy" in r.fields["narration"] and r.fields["transaction_date"] == "2026-06-11"


class TestWorker:
    def test_run_once_routes_items(self, monkeypatch):
        patched = {}
        items = [
            {"id": "1", "fields": {"ProcessingStatus": "New", "SourceMessageId": "s1", "Sender": "alerts@hdfcbank.net", "EmailBodyText": HDFC_DEBIT}},
            {"id": "2", "fields": {"ProcessingStatus": "New", "SourceMessageId": "s2", "Sender": "alerts@icicibank.com", "EmailBodyText": ICICI}},
            {"id": "3", "fields": {"ProcessingStatus": "New", "SourceMessageId": "s3", "Sender": "alerts@hdfcbank.net", "EmailBodyText": OTP}},
            {"id": "4", "fields": {"ProcessingStatus": "New", "SourceMessageId": "s4", "Sender": "alerts@hdfcbank.net", "EmailBodyText": "HDFC Bank: Rs.99 debited on 12-06-26."}},
            {"id": "5", "fields": {"ProcessingStatus": "Processed", "SourceMessageId": "s5", "EmailBodyText": HDFC_DEBIT}},
            {"id": "6", "fields": {"ProcessingStatus": "New", "RetryCount": 5, "SourceMessageId": "s6", "EmailBodyText": HDFC_DEBIT}},
        ]
        for k, v in {"SHAREPOINT_BANK_QUEUE_ENABLED": "true", "M365_TENANT_ID": "t", "M365_CLIENT_ID": "c",
                     "M365_CLIENT_SECRET": "s", "SHAREPOINT_SITE_ID": "site", "SHAREPOINT_BANK_QUEUE_LIST_ID": "list"}.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("SHAREPOINT_BANK_ALLOWLIST", raising=False)
        monkeypatch.setattr(sq, "_token", lambda c: "tok")
        monkeypatch.setattr(sq, "_get_items", lambda c, t: items)
        monkeypatch.setattr(sq, "_patch_fields", lambda c, t, i, v: patched.setdefault(i, []).append(v))

        async def fake_process(msg, actor):
            return {"parsing_status": "pending" if "swiggy" in msg.email_body_text else "parse_failed", "bank_transaction_id": "bt1"}
        import bank_inbox_phase2
        monkeypatch.setattr(bank_inbox_phase2, "process_queue_message", fake_process)

        stats = asyncio.get_event_loop().run_until_complete(sq.run_once(None))
        assert stats == {"seen": 6, "eligible": 4, "processed": 1, "duplicate": 0, "parse_failed": 1, "ignored": 2, "failed": 0}
        assert patched["1"][-1]["ProcessingStatus"] == "Processed" and patched["1"][-1]["FinanceBankTransactionId"] == "bt1"
        assert patched["2"][-1]["ProcessingStatus"] == "Ignored" and "icici" in patched["2"][-1]["ProcessingMessage"]
        assert patched["3"][-1]["ProcessingStatus"] == "Ignored" and "RetryCount" not in patched["3"][-1]
        assert patched["4"][-1]["ProcessingStatus"] == "Parse Failed"
        assert "5" not in patched and "6" not in patched

    def test_worker_loop_disabled_returns_immediately(self, monkeypatch):
        monkeypatch.setenv("SHAREPOINT_BANK_QUEUE_ENABLED", "false")
        asyncio.get_event_loop().run_until_complete(sq.worker_loop(None, asyncio.Event()))

    def test_cycle_failure_does_not_kill_loop(self, monkeypatch):
        monkeypatch.setenv("SHAREPOINT_BANK_QUEUE_ENABLED", "true")
        monkeypatch.setenv("SHAREPOINT_BANK_QUEUE_INTERVAL_SECONDS", "30")
        calls = {"n": 0}
        stop = asyncio.Event()

        async def boom(db):
            calls["n"] += 1
            if calls["n"] == 2:
                stop.set()
            raise RuntimeError("graph down")
        monkeypatch.setattr(sq, "run_once", boom)

        async def fast_wait(coro, timeout):
            stop_set = stop.is_set()
            coro.close()
            if not stop_set:
                return None
            return None
        monkeypatch.setattr(sq.asyncio, "wait_for", fast_wait)
        asyncio.get_event_loop().run_until_complete(sq.worker_loop(None, stop))
        assert calls["n"] == 2
