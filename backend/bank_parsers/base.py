import html
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List

DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d-%b-%Y", "%d-%b-%y", "%d/%m/%y", "%d-%m-%y", "%d %b %Y",
                "%d %b %y", "%d/%b/%Y", "%d/%b/%y", "%Y/%m/%d", "%d.%m.%Y", "%d.%m.%y", "%b %d, %Y", "%d %B %Y",
                "%d-%B-%Y", "%d %b, %Y")


def parse_any_date(v: Optional[str]) -> Optional[str]:
    v = (v or "").strip().rstrip(".,")
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(v, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse_amount(v) -> Optional[float]:
    s = re.sub(r"[^\d.\-]", "", str(v or ""))
    if not s or s in ("-", "."):
        return None
    try:
        return abs(float(s))
    except ValueError:
        return None


@dataclass
class ParseContext:
    body: str
    subject: str = ""
    sender: str = ""
    bank_hint: str = ""
    received_at: str = ""

    @property
    def text(self) -> str:
        body = html_to_text(self.body)
        return re.sub(r"\s+", " ", f"{self.subject} {body}").strip()


def html_to_text(s: str) -> str:
    if not s or "<" not in s:
        return s or ""
    s = re.sub(r"(?is)<(script|style|head).*?</\1>", " ", s)
    s = re.sub(r"(?is)<!--.*?-->", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>|</td>|</th>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    return html.unescape(s.replace("&nbsp;", " "))


# Raw email bodies (large HTML newsletters, signatures, tracking pixels) are capped BEFORE any regex work.
RAW_EMAIL_MAX_CHARS = 400_000


def clean_email_body(raw: str, limit: int) -> str:
    """HTML → plain text, collapse whitespace, hard-cap to `limit` chars so Pydantic max_length never fails."""
    s = (raw or "")[:RAW_EMAIL_MAX_CHARS]
    s = html_to_text(s)
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r"\s*\n\s*", "\n", s).strip()
    return s[:limit]


NON_TXN_RE = (r"\b(OTP|one[\s-]?time\s+password|verification\s+code|is\s+your\s+password|statement\s+(?:is|has\s+been)\s+"
              r"(?:ready|generated|sent|attached)|e-?statement|will\s+be\s+debited|has\s+been\s+declined|(?:transaction|txn|payment)"
              r"\s+(?:has\s+)?(?:failed|declined|unsuccessful|reversed)|request\s+(?:has\s+been\s+)?received|"
              r"login\s+alert|logged\s+in|password\s+(?:changed|reset)|KYC|offer|cashback\s+offer|pre-?approved|"
              r"apply\s+now|due\s+date|reminder|minimum\s+amount\s+due|autopay\s+(?:set|registered))\b")


def looks_like_transaction(text: str) -> bool:
    """True only for a completed money-movement alert: an amount AND a debit/credit verb, and no non-transaction marker."""
    if not text or not re.search(AMOUNT_RE, text, re.IGNORECASE):
        return False
    if not direction_of(text):
        return False
    return not re.search(NON_TXN_RE, text, re.IGNORECASE)


@dataclass
class ParseResult:
    parser: str
    bank_name: str
    fields: dict = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    score: int = 0
    parser_version: str = "1.0"
    selection_method: str = ""
    selection_confidence: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


AMOUNT_RE = r"(?:INR|Rs\.?|₹)\s*([\d,]+(?:\.\d{1,2})?)"
DATE_RE = r"\b(\d{1,2}[-/ .][A-Za-z]{3,9}[-/ .,]\s?\d{2,4}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{4}-\d{2}-\d{2})"
ACCT_RE = r"(?:Account|A/c|Acct|a/c)\s*(?:No\.?\s*)?(?:XX|\*+|x+|X+)?(\d{3,6})\b"
REF_RE = r"(?:UPI\s*Ref(?:erence)?\s*No\.?\s*:?\s*|Ref(?:erence)?\s*(?:No\.?)?\s*:?\s*|UTR\s*(?:No\.?)?\s*:?\s*|Txn\s*(?:ID|No)\s*:?\s*|IMPS\s*Ref\s*:?\s*)([A-Za-z0-9]{6,})"
DEBIT_WORDS = r"\b(debited|spent|paid|withdrawn|purchase of|debit|deducted|transferred from)\b"
CREDIT_WORDS = r"\b(credited|received|deposited|credit|transferred to your)\b"


def first(pattern: str, text: str) -> Optional[str]:
    m = re.search(pattern, text, re.IGNORECASE)
    if not m:
        return None
    return (m.group(1) if m.groups() else m.group(0)).strip()


def direction_of(text: str) -> Optional[str]:
    d = re.search(DEBIT_WORDS, text, re.IGNORECASE)
    c = re.search(CREDIT_WORDS, text, re.IGNORECASE)
    if d and not c:
        return "debit"
    if c and not d:
        return "credit"
    if d and c:
        return "debit" if d.start() < c.start() else "credit"
    return None


TIME_RE = r"\b(\d{1,2}:\d{2}(?::\d{2})?\s?(?:AM|PM|am|pm)?)\b"
UTR_RE = r"(?:UTR|RRN|IMPS\s*Ref|NEFT\s*Ref|RTGS\s*Ref)\s*(?:No\.?)?\s*:?\s*([A-Za-z0-9]{8,})"


class BaseParser:
    name = "base"
    version = "1.0"
    bank_name = "Unknown Bank"
    keywords: tuple = ()
    sender_keywords: tuple = ()
    narration_patterns: tuple = ()

    def matches(self, ctx: ParseContext) -> int:
        return self.match_detail(ctx)[0]

    def match_detail(self, ctx: ParseContext) -> tuple:
        """Returns (score, methods). hint=100, trusted sender=50, subject kw=15 each, body kw=10 each."""
        score, methods = 0, []
        low = ctx.text.lower()
        subj = (ctx.subject or "").lower()
        if ctx.bank_hint and ctx.bank_hint.lower().split()[0] in self.bank_name.lower():
            score += 100
            methods.append("bank_hint")
        if any(k in (ctx.sender or "").lower() for k in self.sender_keywords):
            score += 50
            methods.append("sender")
        if any(k in subj for k in self.keywords):
            score += 15
            methods.append("subject")
        n = sum(1 for k in self.keywords if k in low)
        if n:
            score += 10 * n
            methods.append("body_keywords")
        return score, methods

    def extract_narration(self, text: str) -> str:
        for p in self.narration_patterns:
            v = first(p, text)
            if v and len(v) >= 3:
                return v[:500]
        return ""

    def parse(self, ctx: ParseContext) -> ParseResult:
        text = ctx.text
        r = ParseResult(parser=self.name, bank_name=ctx.bank_hint or self.bank_name, parser_version=self.version)
        amt = parse_amount(first(AMOUNT_RE, text))
        if not amt:
            r.errors.append("amount not found")
        direction = direction_of(text)
        if not direction:
            r.errors.append("direction not found")
        raw_date = first(DATE_RE, text)
        date = parse_any_date(raw_date) if raw_date else None
        if not date and ctx.received_at:
            date = parse_any_date(ctx.received_at[:10])
        if not date:
            r.errors.append("date not found")
        narration = self.extract_narration(text)
        if not narration:
            r.errors.append("narration not found")
        if not raw_date and date:
            r.warnings.append("date taken from email received time")
        ref = first(REF_RE, text) or ""
        utr = first(UTR_RE, text) or ""
        acct = first(ACCT_RE, text) or ""
        for k, v in (("bank_reference", ref), ("bank_account", acct)):
            if not v:
                r.warnings.append(f"{k} not found (optional)")
        merchant = " ".join(w for w in re.split(r"[^A-Za-z]+", narration) if len(w) > 2)[:60] if narration else ""
        r.fields = {"bank_name": r.bank_name, "bank_account": acct, "transaction_date": date or "",
                    "transaction_time": first(TIME_RE, text) or "", "direction": direction or "", "amount": amt or 0,
                    "currency": "INR", "narration": narration, "merchant_name": merchant or None,
                    "bank_reference": ref, "utr_reference": utr, "parser_name": self.name, "parser_version": self.version}
        return r
