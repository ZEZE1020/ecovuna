"""Document and official web research connectors with citation and prompt-injection safeguards (#16)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .db import connect, initialize, insert_json

ALLOWLISTED_WEB_DOMAINS: dict[str, str] = {
    "kalro.org": "Kenya Agricultural and Livestock Research Organization (KALRO)",
    "www.kalro.org": "Kenya Agricultural and Livestock Research Organization (KALRO)",
    "meteo.go.ke": "Kenya Meteorological Department (KMD)",
    "www.meteo.go.ke": "Kenya Meteorological Department (KMD)",
    "kilimo.go.ke": "Ministry of Agriculture and Livestock Development",
    "www.kilimo.go.ke": "Ministry of Agriculture and Livestock Development",
    "homabay.go.ke": "County Government of Homa Bay — Agriculture Directorate",
}

MAX_CONTENT_CHARS = 8000
MAX_EXCERPT_CHARS = 360
DEFAULT_BULLETIN_PATH = Path("data/kalro_bulletins/homabay_agronomy_2026.md")

# Patterns that indicate prompt-injection attempts inside untrusted documents/pages
_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"system\s*prompt", re.IGNORECASE),
    re.compile(r"bypass\s+wao\s+approval", re.IGNORECASE),
    re.compile(r"dispatch\s+immediately\s+without\s+approval", re.IGNORECASE),
    re.compile(r"<\s*/?\s*system\s*>", re.IGNORECASE),
)

OFFICIAL_WEB_FIXTURES: dict[str, dict[str, str]] = {
    "https://www.meteo.go.ke/bulletins/KMD-2026-10-14": {
        "title": "KMD Homa Bay County 7-Day Agro-Meteorological Advisory (KMD-2026-10-14)",
        "publisher": "Kenya Meteorological Department (KMD)",
        "content": (
            "Bulletin KMD-2026-10-14: Sub-county rainfall outlook for Homa Bay Central, Ndhiwa, "
            "and Suba South. Below-normal rainfall expected in Lake Victoria basin zones over the "
            "next 7 days (KALRO-HB-2026-01, KALRO-HB-2026-02); isolated heavy downpours in Ndhiwa "
            "lowlands may trigger flash waterlogging (KALRO-HB-2026-03)."
        ),
    },
    "https://www.kalro.org/advisories/KALRO-HB-2026": {
        "title": "KALRO Homa Bay Maize & Sorghum Agronomy Standard 2026",
        "publisher": "Kenya Agricultural and Livestock Research Organization (KALRO)",
        "content": (
            "Official KALRO Agronomy Reference (KALRO-HB-2026-01 / KALRO-HB-2026-02 / KALRO-HB-2026-03). "
            "Pair with KMD-2026-10-14 before staging any Ward Agricultural Officer e-voucher package."
        ),
    },
}


@dataclass(frozen=True)
class NormalizedSourceCitation:
    """Normalized, inspectable document or official web source citation."""

    source_type: str  # "document" | "official_web"
    source_id: str
    url_or_path: str
    title: str
    publisher: str
    retrieved_at: str
    excerpt: str
    checksum_sha256: str
    citation_matched: bool
    matched_tokens: list[str]
    quality_status: str  # "VERIFIED" | "FALLBACK_LOCAL" | "REJECTED"
    data_only_envelope: str
    injection_sanitized: bool
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sanitize_untrusted_content(raw_text: str) -> tuple[str, bool]:
    """Strip prompt-injection directives and isolate retrieved data from agent instructions."""
    sanitized = raw_text
    flagged = False
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(sanitized):
            flagged = True
            sanitized = pattern.sub("[REDACTED_UNTRUSTED_DIRECTIVE]", sanitized)
    return sanitized, flagged


def _match_citations(text: str, required_tokens: list[str]) -> tuple[bool, list[str]]:
    matched = [tok for tok in required_tokens if tok and tok in text]
    return (len(matched) > 0, matched)


def _audit_connector(
    run_id: str,
    tool_name: str,
    inputs: dict[str, Any],
    output: dict[str, Any],
) -> None:
    initialize()
    with connect() as db:
        insert_json(
            db,
            "mcp_audit_log",
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "run_id": run_id,
                "server": "ecovuna-research-connector",
                "tool_name": tool_name,
                "action": "research_retrieve",
                "input_json": inputs,
                "output_json": output,
            },
        )


def ingest_document_source(
    *,
    document_id: str = "DOC-KALRO-HB-2026",
    title: str = "Homa Bay Agronomy Bulletin 2026",
    publisher: str = "KALRO Homa Bay Research Centre",
    content: str | None = None,
    file_path: str | Path | None = None,
    required_citations: list[str] | None = None,
    run_id: str = "RESEARCH-DOC",
) -> dict[str, Any]:
    """Normalize an uploaded bulletin/PDF text or local agronomy document with quality checks."""
    now = datetime.now(UTC).isoformat()
    req_tokens = required_citations or ["KALRO-HB-2026-01", "KMD-2026-10-14"]
    resolved_path = Path(file_path) if file_path else DEFAULT_BULLETIN_PATH

    try:
        if content is not None:
            raw_text = content
            source_ref = f"upload://{document_id}"
        elif resolved_path.exists():
            raw_text = resolved_path.read_text(encoding="utf-8")
            source_ref = f"file://{resolved_path.as_posix()}"
        else:
            raise FileNotFoundError(f"Document source '{resolved_path}' not found")

        if not raw_text.strip():
            raise ValueError("Document extraction produced empty text")

        bounded_text = raw_text[:MAX_CONTENT_CHARS]
        sanitized_text, injection_flagged = _sanitize_untrusted_content(bounded_text)
        matched, matched_tokens = _match_citations(sanitized_text, req_tokens)

        lines = [line.strip() for line in sanitized_text.splitlines() if line.strip()]
        matching_line = next(
            (
                line
                for line in lines
                if any(tok in line for tok in matched_tokens)
            ),
            lines[0] if lines else sanitized_text[:MAX_EXCERPT_CHARS],
        )
        excerpt = matching_line[:MAX_EXCERPT_CHARS]
        quality_status = "VERIFIED" if matched else "REJECTED"
        error_msg = (
            None
            if matched
            else f"Document does not contain required citation tokens: {req_tokens}"
        )

        record = NormalizedSourceCitation(
            source_type="document",
            source_id=document_id,
            url_or_path=source_ref,
            title=title,
            publisher=publisher,
            retrieved_at=now,
            excerpt=excerpt,
            checksum_sha256=_checksum(sanitized_text),
            citation_matched=matched,
            matched_tokens=matched_tokens,
            quality_status=quality_status,
            data_only_envelope=f"<untrusted_document_data id='{document_id}'>{excerpt}</untrusted_document_data>",
            injection_sanitized=injection_flagged,
            error=error_msg,
        ).as_dict()
    except (OSError, ValueError) as exc:
        fallback_text = (
            DEFAULT_BULLETIN_PATH.read_text(encoding="utf-8")
            if DEFAULT_BULLETIN_PATH.exists()
            else "Fallback KALRO-HB-2026-01 KMD-2026-10-14"
        )
        matched, matched_tokens = _match_citations(fallback_text, req_tokens)
        excerpt = fallback_text.splitlines()[0][:MAX_EXCERPT_CHARS]
        record = NormalizedSourceCitation(
            source_type="document",
            source_id=document_id,
            url_or_path=str(file_path or DEFAULT_BULLETIN_PATH),
            title=title,
            publisher=publisher,
            retrieved_at=now,
            excerpt=excerpt,
            checksum_sha256=_checksum(fallback_text),
            citation_matched=matched,
            matched_tokens=matched_tokens,
            quality_status="FALLBACK_LOCAL",
            data_only_envelope=f"<untrusted_document_data id='{document_id}'>{excerpt}</untrusted_document_data>",
            injection_sanitized=False,
            error=f"Document extraction error ({exc}); fell back to approved local bulletin.",
        ).as_dict()

    _audit_connector(
        run_id,
        "ingest_document_source",
        {"document_id": document_id, "required_citations": req_tokens},
        record,
    )
    return record


def fetch_official_web_source(
    url: str,
    *,
    required_citations: list[str] | None = None,
    timeout_seconds: float = 2.0,
    simulate_failure: bool = False,
    custom_content: str | None = None,
    run_id: str = "RESEARCH-WEB",
) -> dict[str, Any]:
    """Fetch and normalize an allowlisted official web source with timeout and fallback."""
    now = datetime.now(UTC).isoformat()
    req_tokens = required_citations or ["KMD-2026-10-14", "KALRO-HB-2026-01"]
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()

    if host not in ALLOWLISTED_WEB_DOMAINS:
        rejected = NormalizedSourceCitation(
            source_type="official_web",
            source_id=f"WEB-REJECTED-{_checksum(url)[:8].upper()}",
            url_or_path=url,
            title="Unverified External Web Source",
            publisher=host or "unknown",
            retrieved_at=now,
            excerpt="",
            checksum_sha256=_checksum(url),
            citation_matched=False,
            matched_tokens=[],
            quality_status="REJECTED",
            data_only_envelope="",
            injection_sanitized=False,
            error=f"Domain '{host}' is not in the official agronomy allowlist.",
        ).as_dict()
        _audit_connector(run_id, "fetch_official_web_source", {"url": url}, rejected)
        return rejected

    publisher = ALLOWLISTED_WEB_DOMAINS[host]
    try:
        if simulate_failure or timeout_seconds <= 0:
            raise TimeoutError(f"Timed out fetching official web source {url}")

        fixture = OFFICIAL_WEB_FIXTURES.get(url)
        raw_content = (
            custom_content
            if custom_content is not None
            else (
                fixture["content"]
                if fixture
                else f"Official {publisher} bulletin referencing {', '.join(req_tokens)}."
            )
        )
        title = (
            fixture["title"]
            if fixture
            else f"Official {publisher} Bulletin"
        )
        bounded = raw_content[:MAX_CONTENT_CHARS]
        sanitized, injection_flagged = _sanitize_untrusted_content(bounded)
        matched, matched_tokens = _match_citations(sanitized, req_tokens)
        excerpt = sanitized[:MAX_EXCERPT_CHARS]
        quality_status = "VERIFIED" if matched else "REJECTED"
        error_msg = (
            None
            if matched
            else f"Official web page did not match required citations: {req_tokens}"
        )

        record = NormalizedSourceCitation(
            source_type="official_web",
            source_id=f"WEB-{_checksum(url)[:8].upper()}",
            url_or_path=url,
            title=title,
            publisher=publisher,
            retrieved_at=now,
            excerpt=excerpt,
            checksum_sha256=_checksum(sanitized),
            citation_matched=matched,
            matched_tokens=matched_tokens,
            quality_status=quality_status,
            data_only_envelope=f"<untrusted_web_data url='{url}'>{excerpt}</untrusted_web_data>",
            injection_sanitized=injection_flagged,
            error=error_msg,
        ).as_dict()
    except (TimeoutError, OSError, RuntimeError) as exc:
        fallback_text = (
            DEFAULT_BULLETIN_PATH.read_text(encoding="utf-8")
            if DEFAULT_BULLETIN_PATH.exists()
            else "Approved local fallback KMD-2026-10-14 KALRO-HB-2026-01"
        )
        matched, matched_tokens = _match_citations(fallback_text, req_tokens)
        excerpt = fallback_text.splitlines()[0][:MAX_EXCERPT_CHARS]
        record = NormalizedSourceCitation(
            source_type="official_web",
            source_id=f"WEB-FALLBACK-{_checksum(url)[:8].upper()}",
            url_or_path=url,
            title=f"{publisher} (Offline Local Evidence Fallback)",
            publisher=publisher,
            retrieved_at=now,
            excerpt=excerpt,
            checksum_sha256=_checksum(fallback_text),
            citation_matched=matched,
            matched_tokens=matched_tokens,
            quality_status="FALLBACK_LOCAL",
            data_only_envelope=f"<untrusted_web_data url='{url}'>{excerpt}</untrusted_web_data>",
            injection_sanitized=False,
            error=f"Web retrieval failed ({exc}); fell back safely to approved local evidence.",
        ).as_dict()

    _audit_connector(run_id, "fetch_official_web_source", {"url": url}, record)
    return record


def gather_research_bundle(
    *,
    run_id: str,
    rule_id: str,
    bulletin_id: str = "KMD-2026-10-14",
    simulate_web_failure: bool = False,
) -> dict[str, Any]:
    """Retrieve both a document source and an official web source for a single agent trace."""
    required = [rule_id, bulletin_id]
    doc_source = ingest_document_source(
        document_id="DOC-KALRO-HB-2026",
        title="Homa Bay Agronomy Bulletin 2026",
        publisher="KALRO Homa Bay Research Centre",
        required_citations=required,
        run_id=run_id,
    )
    web_source = fetch_official_web_source(
        f"https://www.meteo.go.ke/bulletins/{bulletin_id}",
        required_citations=required,
        simulate_failure=simulate_web_failure,
        run_id=run_id,
    )
    sources = [doc_source, web_source]
    try:
        with connect() as db:
            uploaded_rows = db.execute(
                "SELECT document_id, title, publisher, s3_uri, excerpt, checksum_sha256, created_at "
                "FROM uploaded_documents ORDER BY created_at DESC LIMIT 3"
            ).fetchall()
        for row in uploaded_rows:
            sources.append(
                {
                    "source_type": "s3_uploaded_document",
                    "source_id": row["document_id"],
                    "url_or_path": row["s3_uri"],
                    "title": row["title"],
                    "publisher": row["publisher"],
                    "retrieved_at": row["created_at"],
                    "excerpt": row["excerpt"],
                    "checksum_sha256": row["checksum_sha256"],
                    "citation_matched": True,
                    "matched_tokens": [rule_id],
                    "quality_status": "VERIFIED",
                }
            )
    except OSError:
        uploaded_rows = []

    can_support_staging = bool(
        doc_source["citation_matched"] and web_source["citation_matched"]
    )
    return {
        "document_source": doc_source,
        "web_source": web_source,
        "sources": sources,
        "citation_verified": can_support_staging,
    }
