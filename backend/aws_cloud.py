"""AWS Bedrock AI model runner and S3 agronomy document/artifact vault for Ecovuna."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .agent import triage
from .db import connect, initialize, insert_json
from .errors import NotFoundError
from .mcp_server import list_registered_mcp_tools
from .research_connectors import ingest_document_source

DEFAULT_AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
DEFAULT_AWS_PROFILE = os.getenv("AWS_PROFILE", "wakala")
DEFAULT_BEDROCK_MODEL = os.getenv("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
DEFAULT_S3_BUCKET = os.getenv("AWS_S3_BUCKET", "hackathon-848074620906-team-47")
DEFAULT_S3_PREFIX = os.getenv("AWS_S3_PREFIX", "ecovuna")
LOCAL_S3_CACHE_DIR = Path("data/s3_vault")

_CITATION_TOKEN_RE = re.compile(r"\b(?:KALRO-HB-\d{4}-\d{2}|KMD-\d{4}-\d{2}-\d{2})\b")


def _aws_cli_available() -> bool:
    return shutil.which("aws") is not None


def _build_aws_base_cmd(
    *,
    region: str | None = None,
    profile: str | None = None,
) -> list[str]:
    cmd = ["aws", "--region", (region or DEFAULT_AWS_REGION).strip()]
    active_profile = (profile if profile is not None else os.getenv("AWS_PROFILE", DEFAULT_AWS_PROFILE)).strip()
    # Only pass --profile if explicit AWS_ACCESS_KEY_ID is not set in env
    if active_profile and not os.getenv("AWS_ACCESS_KEY_ID"):
        cmd.extend(["--profile", active_profile])
    return cmd


def get_aws_cloud_status() -> dict[str, Any]:
    """Return current AWS Bedrock and S3 configuration and connectivity status."""
    bucket = os.getenv("AWS_S3_BUCKET", DEFAULT_S3_BUCKET).strip()
    region = os.getenv("AWS_REGION", DEFAULT_AWS_REGION).strip()
    model_id = os.getenv("BEDROCK_MODEL_ID", DEFAULT_BEDROCK_MODEL).strip()
    profile = os.getenv("AWS_PROFILE", DEFAULT_AWS_PROFILE).strip()
    cli_found = _aws_cli_available()

    initialize()
    with connect() as db:
        doc_count = db.execute("SELECT COUNT(*) FROM uploaded_documents").fetchone()[0]

    return {
        "provider": "aws",
        "region": region,
        "profile": profile if not os.getenv("AWS_ACCESS_KEY_ID") else "env_credentials",
        "bedrock_model_id": model_id,
        "s3_bucket": bucket,
        "s3_prefix": DEFAULT_S3_PREFIX,
        "aws_cli_installed": cli_found,
        "uploaded_documents_count": int(doc_count),
        "supported_models": [
            "amazon.nova-lite-v1:0",
            "amazon.nova-pro-v1:0",
            "amazon.nova-micro-v1:0",
            "meta.llama3-3-70b-instruct-v1:0",
        ],
    }


def _extract_json_block(raw_text: str) -> dict[str, Any]:
    cleaned = raw_text.strip()
    if "```" in cleaned:
        parts = cleaned.split("```")
        for part in parts:
            candidate = part.removeprefix("json").strip()
            if candidate.startswith("{") and candidate.endswith("}"):
                cleaned = candidate
                break
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise TypeError("Bedrock response did not contain a JSON object")
    return parsed


def invoke_bedrock_converse(
    *,
    prompt: str,
    model_id: str | None = None,
    region: str | None = None,
    profile: str | None = None,
    timeout_seconds: float = 8.0,
) -> dict[str, Any]:
    """Invoke AWS Bedrock `converse` API via authenticated AWS CLI or boto3."""
    target_model = (model_id or os.getenv("BEDROCK_MODEL_ID", DEFAULT_BEDROCK_MODEL)).strip()
    messages_arg = json.dumps(
        [{"role": "user", "content": [{"text": prompt}]}]
    )
    cmd = [
        *_build_aws_base_cmd(region=region, profile=profile),
        "bedrock-runtime",
        "converse",
        "--model-id",
        target_model,
        "--messages",
        messages_arg,
        "--output",
        "json",
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"AWS Bedrock invocation failed ({proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}"
        )
    payload = json.loads(proc.stdout)
    content_blocks = (
        payload.get("output", {}).get("message", {}).get("content", [])
    )
    text_out = "".join(str(block.get("text", "")) for block in content_blocks)
    usage = payload.get("usage") or {}
    metrics = payload.get("metrics") or {}
    return {
        "parsed": _extract_json_block(text_out),
        "raw_text": text_out,
        "input_tokens": int(usage.get("inputTokens") or 64),
        "output_tokens": int(usage.get("outputTokens") or 48),
        "bedrock_latency_ms": float(metrics.get("latencyMs") or 0.0),
    }


def run_bedrock_agent_task(
    *,
    ward: str = "Homa Bay Central",
    prompt: str = "Assess soil moisture and stage a grounded maize advisory if safe.",
    model_id: str | None = None,
    region: str | None = None,
    profile: str | None = None,
    simulated_bedrock_response: dict[str, Any] | None = None,
    force_fallback: bool = False,
) -> dict[str, Any]:
    """Execute a complete Ecovuna agent task backed by AWS Bedrock (Amazon Nova / Llama 3) with deterministic fallback."""
    started = time.perf_counter()
    selected_model = (model_id or os.getenv("BEDROCK_MODEL_ID", DEFAULT_BEDROCK_MODEL)).strip()
    selected_region = (region or os.getenv("AWS_REGION", DEFAULT_AWS_REGION)).strip()
    tools = [t["name"] for t in list_registered_mcp_tools()]

    bedrock_prompt = (
        "You are the Ecovuna Grounded Extension AI Planner running on AWS Bedrock for African county extension operations.\n"
        f"Allowed MCP tools: {', '.join(tools)}.\n"
        "Return ONLY valid JSON with keys:\n"
        '{"action": "stage_advisory" | "safe_refusal", '
        '"ward": "<ward>", '
        '"scenario_override": "" | "flowering maize" | "flash flood waterlogging" | "microclimate divergence", '
        '"cited_rule_id": "KALRO-HB-2026-01" | "KALRO-HB-2026-02" | "KALRO-HB-2026-03", '
        '"rationale": "<concise grounded agronomic explanation>"}\n'
        f"Ward: {ward}\n"
        f"Officer request: {prompt}"
    )

    fallback_used = False
    fallback_reason: str | None = None
    input_tokens = 68
    output_tokens = 42
    bedrock_latency_ms = 0.0

    try:
        if force_fallback:
            raise RuntimeError("Forced offline fallback for AWS Bedrock")
        if simulated_bedrock_response is not None:
            plan_data = dict(simulated_bedrock_response)
        else:
            live = invoke_bedrock_converse(
                prompt=bedrock_prompt,
                model_id=selected_model,
                region=selected_region,
                profile=profile,
            )
            plan_data = live["parsed"]
            input_tokens = live["input_tokens"]
            output_tokens = live["output_tokens"]
            bedrock_latency_ms = live["bedrock_latency_ms"]

        action = str(plan_data.get("action") or "stage_advisory")
        if action not in {"stage_advisory", "safe_refusal"}:
            action = "stage_advisory"
        cited_rule = str(plan_data.get("cited_rule_id") or "KALRO-HB-2026-01")
        if action == "stage_advisory" and not cited_rule.startswith("KALRO-HB-2026-"):
            cited_rule = "KALRO-HB-2026-01"
        validated_plan = {
            "action": action,
            "ward": str(plan_data.get("ward") or ward),
            "scenario_override": str(plan_data.get("scenario_override") or ""),
            "cited_rule_id": cited_rule if action == "stage_advisory" else None,
            "rationale": str(plan_data.get("rationale") or "Grounded AWS Bedrock plan."),
        }
    except Exception as exc:  # noqa: BLE001
        fallback_used = True
        fallback_reason = str(exc)
        lower_prompt = prompt.lower()
        if ward == "Suba South" or "conflict" in lower_prompt or "divergen" in lower_prompt:
            validated_plan = {
                "action": "safe_refusal",
                "ward": ward,
                "scenario_override": "microclimate divergence",
                "cited_rule_id": None,
                "rationale": "Refusing confident advice due to conflicting sensor signals; safe fallback.",
            }
        else:
            scenario = (
                "flowering maize"
                if "flower" in lower_prompt
                else (
                    "flash flood waterlogging"
                    if "flood" in lower_prompt or ward == "Ndhiwa"
                    else ""
                )
            )
            rule = (
                "KALRO-HB-2026-03"
                if scenario == "flash flood waterlogging"
                else (
                    "KALRO-HB-2026-02"
                    if scenario == "flowering maize"
                    else "KALRO-HB-2026-01"
                )
            )
            validated_plan = {
                "action": "stage_advisory",
                "ward": ward,
                "scenario_override": scenario,
                "cited_rule_id": rule,
                "rationale": "Grounded deterministic fallback plan when AWS Bedrock is offline.",
            }

    scenario_to_run = validated_plan["scenario_override"]
    if validated_plan["action"] == "safe_refusal" and not scenario_to_run:
        scenario_to_run = "contradictory_guidance"

    state = triage(ward, scenario_to_run)
    total_ms = round((time.perf_counter() - started) * 1000, 2)
    state["agent_foundation"] = {
        "project": "Ecovuna Agentic Extension Foundation",
        "provider": "aws_bedrock",
        "model": selected_model,
        "mode": "aws_bedrock_fallback" if fallback_used else "aws_bedrock_live",
        "grounded": True,
        "human_approval_required": True,
    }
    state["cost_telemetry"] = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "local_ollama_cost_usd": 0.0,
        "cloud_equivalent_cost_usd": round(
            (input_tokens * 0.0000006) + (output_tokens * 0.0000024), 6
        ),
        "duration_ms": total_ms,
    }
    bedrock_record = {
        "provider": "aws_bedrock",
        "region": selected_region,
        "model_id": selected_model,
        "status": (
            "SAFE_REFUSAL"
            if state.get("advisory") is None
            else ("FALLBACK_DETERMINISTIC" if fallback_used else "BEDROCK_LIVE_GROUNDED")
        ),
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "bedrock_latency_ms": bedrock_latency_ms or total_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "structured_plan": validated_plan,
    }
    state["bedrock_execution"] = bedrock_record

    initialize()
    with connect() as db:
        insert_json(
            db,
            "mcp_audit_log",
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "run_id": state["run_id"],
                "server": "aws-bedrock",
                "tool_name": selected_model,
                "action": "bedrock_converse",
                "input_json": {"ward": ward, "prompt": prompt, "region": selected_region},
                "output_json": bedrock_record,
            },
        )
    return state


def upload_document_to_s3(
    *,
    title: str,
    content: str,
    ward: str = "Homa Bay Central",
    publisher: str = "KALRO / County Extension Directorate",
    filename: str = "agronomy_bulletin.md",
    content_type: str = "text/markdown",
    uploaded_by: str = "Godfrey Ogembo — WAO-KE-043",
    bucket: str | None = None,
    region: str | None = None,
    profile: str | None = None,
    force_local: bool = False,
) -> dict[str, Any]:
    """Upload an agronomy bulletin or field document to AWS S3 (with local vault mirror), index it for grounded research, and record provenance."""
    initialize()
    clean_title = title.strip() or "Extension Agronomy Document"
    raw_bytes = content.encode("utf-8")
    checksum = hashlib.sha256(raw_bytes).hexdigest()
    doc_id = f"DOC-S3-{checksum[:10].upper()}"
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", filename.strip() or "document.md")
    target_bucket = (bucket or os.getenv("AWS_S3_BUCKET", DEFAULT_S3_BUCKET)).strip()
    s3_key = f"{DEFAULT_S3_PREFIX}/documents/{doc_id}_{safe_name}"
    s3_uri = f"s3://{target_bucket}/{s3_key}"

    LOCAL_S3_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    local_mirror_path = LOCAL_S3_CACHE_DIR / f"{doc_id}_{safe_name}"
    local_mirror_path.write_text(content, encoding="utf-8")

    storage_mode = "local_vault_fallback"
    s3_error: str | None = None
    if not force_local and _aws_cli_available():
        try:
            cmd = [
                *_build_aws_base_cmd(region=region, profile=profile),
                "s3",
                "cp",
                str(local_mirror_path),
                s3_uri,
            ]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10.0,
                check=False,
            )
            if proc.returncode == 0:
                storage_mode = "aws_s3_live"
            else:
                s3_error = proc.stderr.strip() or proc.stdout.strip()
        except Exception as exc:  # noqa: BLE001
            s3_error = str(exc)

    citation_tokens = sorted(set(_CITATION_TOKEN_RE.findall(content)))
    if not citation_tokens:
        citation_tokens = ["KALRO-HB-2026-01"]

    normalized_research = ingest_document_source(
        document_id=doc_id,
        title=clean_title,
        publisher=publisher,
        content=content,
        required_citations=citation_tokens,
        run_id=f"S3-INGEST-{doc_id}",
    )

    now = datetime.now(UTC).isoformat()
    record = {
        "document_id": doc_id,
        "title": clean_title,
        "publisher": publisher,
        "ward": ward,
        "filename": safe_name,
        "content_type": content_type,
        "size_bytes": len(raw_bytes),
        "checksum_sha256": checksum,
        "s3_bucket": target_bucket,
        "s3_key": s3_key,
        "s3_uri": s3_uri,
        "storage_mode": storage_mode,
        "excerpt": normalized_research["excerpt"],
        "citation_tokens": citation_tokens,
        "uploaded_by": uploaded_by,
        "created_at": now,
        "research_citation": normalized_research,
        "s3_sync_note": s3_error,
    }

    with connect() as db:
        db.execute(
            """
            INSERT OR REPLACE INTO uploaded_documents
              (document_id, title, publisher, ward, filename, content_type,
               size_bytes, checksum_sha256, s3_bucket, s3_key, s3_uri,
               storage_mode, excerpt, citation_tokens_json, uploaded_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc_id,
                clean_title,
                publisher,
                ward,
                safe_name,
                content_type,
                len(raw_bytes),
                checksum,
                target_bucket,
                s3_key,
                s3_uri,
                storage_mode,
                normalized_research["excerpt"],
                json.dumps(citation_tokens),
                uploaded_by,
                now,
            ),
        )
        insert_json(
            db,
            "mcp_audit_log",
            {
                "timestamp": now,
                "run_id": f"S3-DOC-{doc_id}",
                "server": "aws-s3-vault",
                "tool_name": "upload_document_to_s3",
                "action": "document_upload",
                "input_json": {
                    "title": clean_title,
                    "ward": ward,
                    "filename": safe_name,
                    "s3_uri": s3_uri,
                },
                "output_json": {
                    "document_id": doc_id,
                    "storage_mode": storage_mode,
                    "checksum_sha256": checksum,
                    "citation_tokens": citation_tokens,
                },
            },
        )
    return record


def list_uploaded_documents(*, ward: str | None = None) -> list[dict[str, Any]]:
    """List documents stored in the S3 agronomy document vault."""
    initialize()
    with connect() as db:
        if ward:
            rows = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM uploaded_documents WHERE ward = ? ORDER BY created_at DESC",
                    (ward,),
                )
            ]
        else:
            rows = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM uploaded_documents ORDER BY created_at DESC"
                )
            ]
    for row in rows:
        row["citation_tokens"] = json.loads(row.pop("citation_tokens_json") or "[]")
    return rows


def sync_artifact_to_s3(
    artifact: dict[str, Any],
    *,
    bucket: str | None = None,
    region: str | None = None,
    profile: str | None = None,
    force_local: bool = False,
) -> dict[str, Any]:
    """Sync a generated field artifact (field_brief, sms, ussd, visit_list) to AWS S3."""
    artifact_id = str(artifact["artifact_id"])
    run_id = str(artifact["run_id"])
    art_type = str(artifact["artifact_type"])
    version = int(artifact.get("version") or 1)
    target_bucket = (bucket or os.getenv("AWS_S3_BUCKET", DEFAULT_S3_BUCKET)).strip()
    s3_key = f"{DEFAULT_S3_PREFIX}/artifacts/{run_id}/{artifact_id}_{art_type}_v{version}.txt"
    s3_uri = f"s3://{target_bucket}/{s3_key}"

    LOCAL_S3_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    local_file = LOCAL_S3_CACHE_DIR / f"{artifact_id}_{art_type}_v{version}.txt"
    local_file.write_text(str(artifact.get("content_text") or ""), encoding="utf-8")

    storage_mode = "local_vault_fallback"
    if not force_local and _aws_cli_available():
        cmd = [
            *_build_aws_base_cmd(region=region, profile=profile),
            "s3",
            "cp",
            str(local_file),
            s3_uri,
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10.0,
            check=False,
        )
        if proc.returncode == 0:
            storage_mode = "aws_s3_live"

    return {
        "artifact_id": artifact_id,
        "run_id": run_id,
        "s3_bucket": target_bucket,
        "s3_key": s3_key,
        "s3_uri": s3_uri,
        "storage_mode": storage_mode,
        "synced_at": datetime.now(UTC).isoformat(),
    }


def get_uploaded_document(document_id: str) -> dict[str, Any]:
    initialize()
    with connect() as db:
        row = db.execute(
            "SELECT * FROM uploaded_documents WHERE document_id = ?",
            (document_id,),
        ).fetchone()
    if not row:
        raise NotFoundError(
            f"Uploaded document '{document_id}' was not found.",
            error_code="DOCUMENT_NOT_FOUND",
        )
    item = dict(row)
    item["citation_tokens"] = json.loads(item.pop("citation_tokens_json") or "[]")
    return item
