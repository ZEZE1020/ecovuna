"""SQLite persistence for registry, extension operations, and audit records."""
from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.getenv("SQLITE_DB_PATH", "./data/ecovuna.db"))


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize() -> None:
    with connect() as db:
        db.executescript(
            """
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
            """
        )


def insert_json(db: sqlite3.Connection, table: str, values: dict[str, object]) -> None:
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    db.execute(
        f"INSERT OR REPLACE INTO {table} ({columns}) VALUES ({placeholders})",
        [json.dumps(value) if isinstance(value, (dict, list)) else value for value in values.values()],
    )
