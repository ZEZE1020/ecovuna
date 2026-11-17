"""SQLite persistence with Amazon DynamoDB state sync (`ecovuna-ward-state`, `ecovuna-hitl-audit`, `ecovuna-tool-registry`)."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DB_PATH = Path(os.getenv("SQLITE_DB_PATH", "./data/ecovuna.db"))
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "dynamodb").lower()
DYNAMODB_REGION = os.getenv("AWS_REGION", "eu-west-1")
DYNAMODB_PROFILE = os.getenv("AWS_PROFILE", "wakala")
WARD_STATE_TABLE = os.getenv("DYNAMODB_WARD_STATE_TABLE", "ecovuna-ward-state")
HITL_AUDIT_TABLE = os.getenv("DYNAMODB_HITL_AUDIT_TABLE", "ecovuna-hitl-audit")
TOOL_REGISTRY_TABLE = os.getenv("DYNAMODB_TOOL_REGISTRY_TABLE", "ecovuna-tool-registry")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS farmers (
  farmer_id TEXT PRIMARY KEY, full_name TEXT NOT NULL,
  phone_number TEXT NOT NULL, ward TEXT NOT NULL,
  agroclimatic_zone TEXT NOT NULL, cooperative_name TEXT NOT NULL,
  preferred_language TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plots (
  plot_id TEXT PRIMARY KEY, farmer_id TEXT NOT NULL REFERENCES farmers,
  latitude REAL NOT NULL, longitude REAL NOT NULL, crop_type TEXT NOT NULL,
  planting_date TEXT NOT NULL, current_growth_stage TEXT NOT NULL,
  acreage REAL NOT NULL, kijanibox_sensor_id TEXT NOT NULL,
  repayment_score INTEGER NOT NULL, subsidy_tier_eligible TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS telemetry_cache (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ward TEXT NOT NULL,
  sensor_id TEXT NOT NULL, timestamp TEXT NOT NULL,
  soil_moisture_pct REAL NOT NULL, soil_temp_c REAL NOT NULL,
  precipitation_7d_mm REAL NOT NULL, rainfall_anomaly_mm REAL NOT NULL,
  raw_payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS staged_advisories (
  advisory_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, ward TEXT NOT NULL,
  anomaly_type TEXT NOT NULL, target_growth_stage TEXT NOT NULL,
  affected_plot_ids_json TEXT NOT NULL, affected_household_count INTEGER NOT NULL,
  draft_sms_swahili TEXT NOT NULL, draft_sms_english TEXT NOT NULL,
  ussd_menu_payload TEXT NOT NULL, evoucher_package_code TEXT NOT NULL,
  evoucher_total_kes REAL NOT NULL, per_farmer_kes REAL NOT NULL,
  citations_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING_WAO_APPROVAL'
);
CREATE TABLE IF NOT EXISTS mcp_audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
  run_id TEXT NOT NULL, server TEXT NOT NULL, tool_name TEXT NOT NULL,
  action TEXT NOT NULL, input_json TEXT NOT NULL, output_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS partners (
  partner_id TEXT PRIMARY KEY, name TEXT NOT NULL, partner_type TEXT NOT NULL,
  ward TEXT NOT NULL, latitude REAL NOT NULL, longitude REAL NOT NULL,
  service_radius_km REAL NOT NULL, verified INTEGER NOT NULL DEFAULT 0,
  contact_name TEXT NOT NULL, contact_phone TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inputs (
  input_id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
  crop_types_json TEXT NOT NULL, soil_profiles_json TEXT NOT NULL,
  climate_zones_json TEXT NOT NULL, unit TEXT NOT NULL,
  price_kes REAL NOT NULL, partner_id TEXT NOT NULL REFERENCES partners,
  stock_status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS farm_assignments (
  assignment_id TEXT PRIMARY KEY, plot_id TEXT NOT NULL REFERENCES plots,
  partner_id TEXT NOT NULL REFERENCES partners, input_id TEXT REFERENCES inputs,
  status TEXT NOT NULL DEFAULT 'RECOMMENDED', reason_json TEXT NOT NULL,
  created_at TEXT NOT NULL, officer_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_runs (
  run_id TEXT PRIMARY KEY, ward TEXT NOT NULL,
  status TEXT NOT NULL, current_node TEXT NOT NULL,
  state_json TEXT NOT NULL, created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS policy_decisions (
  decision_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
  tool_name TEXT NOT NULL, category TEXT NOT NULL,
  channel TEXT NOT NULL, officer_id TEXT NOT NULL,
  approval_token TEXT NOT NULL, allowed INTEGER NOT NULL,
  error_code TEXT NOT NULL, reason TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversation_sessions (
  session_id TEXT PRIMARY KEY, ward TEXT NOT NULL,
  crop TEXT NOT NULL, season TEXT NOT NULL,
  telemetry_freshness TEXT NOT NULL, prior_run_ids_json TEXT NOT NULL,
  unresolved_questions_json TEXT NOT NULL, created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversation_turns (
  turn_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES conversation_sessions,
  role TEXT NOT NULL, message TEXT NOT NULL,
  run_id TEXT, sections_json TEXT NOT NULL,
  citations_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS field_artifacts (
  artifact_id TEXT PRIMARY KEY,
  artifact_group_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  run_id TEXT NOT NULL,
  session_id TEXT,
  ward TEXT NOT NULL,
  artifact_type TEXT NOT NULL,
  title TEXT NOT NULL,
  content_text TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  citations_json TEXT NOT NULL,
  approval_status TEXT NOT NULL,
  approved_by_wao TEXT,
  dispatched INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS run_tool_events (
  event_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  session_id TEXT,
  sequence_no INTEGER NOT NULL,
  node TEXT NOT NULL,
  server TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  output_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS phone_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  phone_number TEXT NOT NULL,
  sender TEXT NOT NULL,
  timestamp TEXT NOT NULL,
  text_sw TEXT NOT NULL,
  text_en TEXT NOT NULL,
  text_luo TEXT NOT NULL,
  citation TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS uploaded_documents (
  document_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  publisher TEXT NOT NULL,
  ward TEXT NOT NULL,
  filename TEXT NOT NULL,
  content_type TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  checksum_sha256 TEXT NOT NULL,
  s3_bucket TEXT NOT NULL,
  s3_key TEXT NOT NULL,
  s3_uri TEXT NOT NULL,
  storage_mode TEXT NOT NULL,
  excerpt TEXT NOT NULL,
  citation_tokens_json TEXT NOT NULL,
  uploaded_by TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


def _dynamodb_put_item(table_name: str, pk: str, payload: dict[str, Any]) -> bool:
    if os.getenv("DYNAMODB_LIVE_SYNC", "false").lower() != "true":
        return False
    if shutil.which("aws") is None:
        return False
    cmd = ["aws", "--region", DYNAMODB_REGION]
    if DYNAMODB_PROFILE and not os.getenv("AWS_ACCESS_KEY_ID"):
        cmd.extend(["--profile", DYNAMODB_PROFILE])
    item = {
        "pk": {"S": pk},
        "updated_at": {"S": datetime.now(UTC).isoformat()},
        "payload_json": {"S": json.dumps(payload, default=str)},
    }
    cmd.extend(
        [
            "dynamodb",
            "put-item",
            "--table-name",
            table_name,
            "--item",
            json.dumps(item),
        ]
    )
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=2.5,
            check=False,
        )
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _restore_snapshot(connection: sqlite3.Connection) -> None:
    _ = connection


def _save_snapshot(connection: sqlite3.Connection) -> None:
    _ = connection


def sync_dynamodb_tables(
    *,
    ward_state: dict[str, Any] | None = None,
    hitl_audit: dict[str, Any] | None = None,
    tool_registry: dict[str, Any] | None = None,
) -> dict[str, bool]:
    """Persist records into Amazon DynamoDB tables (`ecovuna-ward-state`, `ecovuna-hitl-audit`, `ecovuna-tool-registry`)."""
    results: dict[str, bool] = {}
    if ward_state is not None:
        pk = str(ward_state.get("ward") or ward_state.get("run_id") or "WARD-DEFAULT")
        results[WARD_STATE_TABLE] = _dynamodb_put_item(WARD_STATE_TABLE, pk, ward_state)
    if hitl_audit is not None:
        pk = str(hitl_audit.get("run_id") or hitl_audit.get("triage_id") or "AUDIT-DEFAULT")
        results[HITL_AUDIT_TABLE] = _dynamodb_put_item(HITL_AUDIT_TABLE, pk, hitl_audit)
    if tool_registry is not None:
        pk = str(tool_registry.get("tool_name") or tool_registry.get("id") or "REGISTRY-SNAPSHOT")
        results[TOOL_REGISTRY_TABLE] = _dynamodb_put_item(
            TOOL_REGISTRY_TABLE, pk, tool_registry
        )
    return results


def storage_backend() -> str:
    return STORAGE_BACKEND


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(SCHEMA_SQL)
        _restore_snapshot(connection)
        yield connection
        _save_snapshot(connection)
        connection.commit()
    finally:
        connection.close()


def initialize() -> None:
    with connect() as db:
        db.executescript(SCHEMA_SQL)


def insert_json(db: sqlite3.Connection, table: str, values: dict[str, object]) -> None:
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    db.execute(
        f"INSERT OR REPLACE INTO {table} ({columns}) VALUES ({placeholders})",
        [json.dumps(value) if isinstance(value, (dict, list)) else value for value in values.values()],
    )
