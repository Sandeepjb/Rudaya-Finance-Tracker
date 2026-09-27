"""Extraction providers: Azure Document Intelligence (prebuilt-layout) and a local pdfplumber fallback.
Both return the same structured ExtractionResult (tables → rows → cells with page/row/col/confidence)."""
import asyncio
import io
import os
from dataclasses import dataclass, field, asdict
from typing import List, Optional


class ExtractionError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 502):
        super().__init__(message)
        self.code, self.message, self.http_status = code, message, http_status


@dataclass
class Cell:
    page: int
    table: int
    row: int
    col: int
    raw: str
    confidence: Optional[float] = None


@dataclass
class Table:
    page: int
    index: int
    rows: List[List[Cell]] = field(default_factory=list)


@dataclass
class ExtractionResult:
    provider: str
    model_id: str
    page_count: int
    tables: List[Table]
    text_lines: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"provider": self.provider, "model_id": self.model_id, "page_count": self.page_count,
                "tables": [{"page": t.page, "index": t.index, "rows": [[asdict(c) for c in r] for r in t.rows]} for t in self.tables]}


class ExtractionProvider:
    name = "base"
    model_id = ""

    async def analyze(self, pdf_bytes: bytes) -> ExtractionResult:
        raise NotImplementedError


def _grid(cells, page, tindex) -> List[List[Cell]]:
    rows = {}
    for c in cells:
        rows.setdefault(c.row, {})[c.col] = c
    out = []
    for r in sorted(rows):
        cols = rows[r]
        width = max(cols) + 1
        out.append([cols.get(i) or Cell(page, tindex, r, i, "") for i in range(width)])
    return out


class AzureDocumentIntelligenceProvider(ExtractionProvider):
    name = "azure_document_intelligence"
    model_id = "prebuilt-layout"
    TIMEOUT = int(os.environ.get("AZURE_DOCUMENT_INTELLIGENCE_TIMEOUT", "120"))

    @staticmethod
    def configured() -> bool:
        return bool(os.environ.get("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT") and os.environ.get("AZURE_DOCUMENT_INTELLIGENCE_KEY"))

    def _client(self):
        from azure.core.credentials import AzureKeyCredential
        from azure.core.pipeline.policies import RetryPolicy
        from azure.ai.documentintelligence.aio import DocumentIntelligenceClient
        return DocumentIntelligenceClient(
            endpoint=os.environ["AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT"].rstrip("/"),
            credential=AzureKeyCredential(os.environ["AZURE_DOCUMENT_INTELLIGENCE_KEY"]),
            retry_policy=RetryPolicy(retry_total=3, retry_backoff_factor=1, retry_backoff_max=8,
                                     retry_on_status_codes=[408, 429, 500, 502, 503, 504]))

    async def analyze(self, pdf_bytes: bytes) -> ExtractionResult:
        if not self.configured():
            raise ExtractionError("not_configured", "Azure Document Intelligence is not configured on the server", 503)
        from azure.core.exceptions import HttpResponseError, ServiceRequestError, ClientAuthenticationError
        client = self._client()
        try:
            poller = await client.begin_analyze_document(model_id=self.model_id, body=pdf_bytes, content_type="application/pdf")
            result = await asyncio.wait_for(poller.result(), timeout=self.TIMEOUT)
        except asyncio.TimeoutError:
            raise ExtractionError("timeout", "Azure analysis timed out — try again or split the statement", 504)
        except ClientAuthenticationError:
            raise ExtractionError("auth", "Azure authentication failed — check the configured endpoint/key", 502)
        except HttpResponseError as e:
            st = getattr(e, "status_code", None)
            if st == 401:
                raise ExtractionError("auth", "Azure authentication failed — check the configured endpoint/key", 502)
            if st == 429:
                raise ExtractionError("rate_limit", "Azure quota/rate limit exceeded — retry later", 503)
            if st in (400, 415):
                raise ExtractionError("invalid_document", "Azure rejected the document as invalid/unsupported", 422)
            raise ExtractionError("azure_error", f"Azure analysis failed (HTTP {st or 'error'})", 502)
        except (ServiceRequestError, OSError):
            raise ExtractionError("network", "Could not reach Azure Document Intelligence (network error)", 504)
        finally:
            await client.close()
        return self.map_result(result)

    @staticmethod
    def map_result(result) -> ExtractionResult:
        tables = []
        for ti, t in enumerate(getattr(result, "tables", None) or []):
            tpage = t.bounding_regions[0].page_number if getattr(t, "bounding_regions", None) else 1
            cells = []
            for c in t.cells or []:
                page = c.bounding_regions[0].page_number if getattr(c, "bounding_regions", None) else tpage
                cells.append(Cell(page, ti, c.row_index, c.column_index, (c.content or "").strip(), getattr(c, "confidence", None)))
            tables.append(Table(tpage, ti, _grid(cells, tpage, ti)))
        pages = getattr(result, "pages", None) or []
        lines = [ln.content for p in pages for ln in (getattr(p, "lines", None) or [])]
        if not tables and not lines:
            raise ExtractionError("empty", "Azure returned no tables or text for this document", 422)
        return ExtractionResult(AzureDocumentIntelligenceProvider.name, AzureDocumentIntelligenceProvider.model_id,
                                len(pages) or max((t.page for t in tables), default=1), tables, lines)


class LocalPdfplumberProvider(ExtractionProvider):
    """Fallback when Azure is not configured: pdfplumber table extraction (no OCR)."""
    name = "local_pdfplumber"
    model_id = "pdfplumber-tables"

    async def analyze(self, pdf_bytes: bytes) -> ExtractionResult:
        import pdfplumber
        tables, lines = [], []
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for pi, page in enumerate(pdf.pages, 1):
                    lines.extend(ln.strip() for ln in (page.extract_text() or "").splitlines() if ln.strip())
                    for tt in page.extract_tables() or []:
                        ti = len(tables)
                        rows = [[Cell(pi, ti, ri, ci, (v or "").strip(), None) for ci, v in enumerate(r)] for ri, r in enumerate(tt)]
                        tables.append(Table(pi, ti, rows))
                count = len(pdf.pages)
        except Exception as e:
            raise ExtractionError("invalid_document", f"Could not read PDF: {type(e).__name__}", 422)
        if not tables and not lines:
            raise ExtractionError("empty", "No text or tables extracted — scanned PDF needs Azure OCR", 422)
        return ExtractionResult(self.name, self.model_id, count, tables, lines)


def get_provider(name: Optional[str] = None) -> ExtractionProvider:
    if name in (None, "", "auto"):
        name = "azure" if AzureDocumentIntelligenceProvider.configured() else "local"
    if name == "azure":
        return AzureDocumentIntelligenceProvider()
    if name == "local":
        return LocalPdfplumberProvider()
    raise ExtractionError("bad_provider", "Unknown extraction provider", 422)
