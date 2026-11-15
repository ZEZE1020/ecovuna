"""FastAPI HTTP interface for the agent console."""
from __future__ import annotations

import json
import math
import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .agent import decide, triage
from .db import connect, initialize, storage_backend
from .evals.summary import summary as evaluation_summary
from .foundation import get_agent_foundation
from .observability import configure_fastapi, telemetry_status


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize()
    yield


app = FastAPI(title="Ecovuna Desk API", version="1.0.0", lifespan=lifespan)
configure_fastapi(app)
allowed_origins = [
    origin for origin in (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        os.getenv("FRONTEND_ORIGIN", "").rstrip("/"),
    ) if origin
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)


class TriageRequest(BaseModel):
    ward: str = Field(default="Homa Bay Central", min_length=1, max_length=100)
    scenario_override: str = ""


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    ward: str = Field(default="Homa Bay Central", min_length=1, max_length=100)


class DecisionRequest(BaseModel):
    run_id: str
    approved: bool
    wao_officer_name: str
    notes: str = ""


class RecommendationRequest(BaseModel):
    ward: str | None = None
    crop_type: str | None = None
    category: str | None = None
    limit: int = 20


class AssignmentRequest(BaseModel):
    plot_id: str
    partner_id: str
    input_id: str | None = None
    officer_id: str = "WAO-KE-043"


class FarmerOnboardingRequest(BaseModel):
    full_name: str
    phone_number: str
    ward: str
    agroclimatic_zone: str = "lake_victoria_basin"
    cooperative_name: str = "Independent farmer"
    preferred_language: str = "English"


class PlotOnboardingRequest(BaseModel):
    farmer_id: str
    latitude: float
    longitude: float
    crop_type: str
    planting_date: str
    current_growth_stage: str
    acreage: float
    kijanibox_sensor_id: str = ""


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "storage_backend": storage_backend(),
        "telemetry": telemetry_status(),
        "agent_foundation": get_agent_foundation().as_dict(),
    }


@app.get("/api/agent/foundation")
def agent_foundation() -> dict[str, object]:
    """Expose the active model, grounding, and approval contract to operators."""
    return get_agent_foundation().as_dict()


@app.get("/api/evaluations/summary")
def evaluations_summary(trials: int = 1) -> dict[str, Any]:
    """Return small, repeatable quality signals for the operator console."""
    return evaluation_summary(trials)


@app.post("/api/agent/triage")
def run_triage(request: TriageRequest) -> dict[str, Any]:
    try:
        return triage(request.ward, request.scenario_override)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/agent/chat")
def agent_chat(request: ChatRequest) -> dict[str, Any]:
    """Translate a plain-language question into a grounded, inspectable run."""
    normalized = request.message.lower()
    scenario = (
        "flash flood waterlogging"
        if "flood" in normalized or "water" in normalized
        else "flowering maize dry spell"
        if "flower" in normalized
        else "sudden dry spell"
    )
    try:
        result = triage(request.ward, scenario)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "message": "I found grounded evidence and prepared an advisory for your review.",
        "question": request.message,
        "run": result,
    }


@app.get("/api/mcp/registry")
def mcp_registry() -> dict[str, Any]:
    """Expose the configured MCP servers and recent tool activity."""
    servers = [
        {
            "id": "ecovuna-telemetry",
            "name": "Ecovuna Telemetry",
            "transport": "local process",
            "tools": [
                "fetch_kijanibox_telemetry",
                "fetch_open_meteo_context",
                "fetch_kalro_guidelines",
                "stage_advisory_for_wao_approval",
            ],
            "status": "ready",
        },
        {
            "id": "kalro-reference-fetch",
            "name": "KALRO Reference Fetch",
            "transport": "MCP subprocess",
            "tools": ["fetch"],
            "status": "configured",
        },
    ]
    with connect() as db:
        activity = [
            dict(row) for row in db.execute(
                "SELECT server, tool_name, timestamp FROM mcp_audit_log ORDER BY id DESC LIMIT 10"
            )
        ]
    return {"servers": servers, "recent_activity": activity}


@app.post("/api/agent/decide")
def make_decision(request: DecisionRequest) -> dict[str, Any]:
    try:
        return decide(request.run_id, request.approved, request.wao_officer_name, request.notes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/audit-logs")
def audit_logs() -> list[dict[str, Any]]:
    with connect() as db:
        return [dict(row) for row in db.execute(
            "SELECT * FROM mcp_audit_log ORDER BY id DESC LIMIT 100"
        )]


@app.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    """Return operational counts and ward summaries from the local registry."""
    with connect() as db:
        counts = {
            "households": db.execute("SELECT COUNT(*) FROM farmers").fetchone()[0],
            "plots": db.execute("SELECT COUNT(*) FROM plots").fetchone()[0],
            "advisories": db.execute("SELECT COUNT(*) FROM staged_advisories").fetchone()[0],
            "pending_advisories": db.execute(
                "SELECT COUNT(*) FROM staged_advisories WHERE status = 'PENDING_WAO_APPROVAL'"
            ).fetchone()[0],
            "field_visits_due": 0,
        }
        wards = [dict(row) for row in db.execute(
            """
            SELECT farmers.ward, COUNT(DISTINCT farmers.farmer_id) AS households,
                   COUNT(plots.plot_id) AS plots,
                   ROUND(AVG(telemetry_cache.soil_moisture_pct), 1) AS soil_moisture_pct,
                   MAX(telemetry_cache.timestamp) AS last_telemetry_at
            FROM farmers
            LEFT JOIN plots ON plots.farmer_id = farmers.farmer_id
            LEFT JOIN telemetry_cache ON telemetry_cache.ward = farmers.ward
            GROUP BY farmers.ward ORDER BY farmers.ward
            """
        )]
    return {"counts": counts, "wards": wards}


@app.get("/api/advisories")
def advisories(status: str | None = None) -> list[dict[str, Any]]:
    """Return staged advisory records with their JSON fields decoded."""
    query = "SELECT * FROM staged_advisories"
    params: tuple[str, ...] = ()
    if status:
        query += " WHERE status = ?"
        params = (status,)
    query += " ORDER BY rowid DESC LIMIT 50"
    with connect() as db:
        records = [dict(row) for row in db.execute(query, params)]
    for record in records:
        for field in ("affected_plot_ids_json", "citations_json"):
            record[field.removesuffix("_json")] = json.loads(record.pop(field))
    return records


@app.get("/api/telemetry")
def telemetry(ward: str | None = None) -> dict[str, Any]:
    """Return normalized readings with live-source provenance for the console."""
    query = "SELECT * FROM telemetry_cache"
    params: tuple[str, ...] = ()
    if ward:
        query += " WHERE ward = ?"
        params = (ward,)
    query += " ORDER BY timestamp DESC, id DESC LIMIT 20"
    with connect() as db:
        readings = [dict(row) for row in db.execute(query, params)]
    for reading in readings:
        raw_payload = reading.get("raw_payload_json")
        if isinstance(raw_payload, str):
            try:
                reading["raw_payload_json"] = json.loads(raw_payload)
            except json.JSONDecodeError:
                reading["raw_payload_json"] = {"source": "unknown"}
        payload = reading["raw_payload_json"]
        reading["source"] = payload.get("source", "telemetry_cache")
        reading["freshness"] = "live" if payload.get("source") == "kijanispace" else "cached"
    return {"ward": ward, "readings": readings}


@app.get("/api/farmers")
def farmers(ward: str | None = None, search: str | None = None) -> list[dict[str, Any]]:
    query = """
        SELECT farmers.*, COUNT(plots.plot_id) AS plot_count
        FROM farmers LEFT JOIN plots ON plots.farmer_id = farmers.farmer_id
        WHERE (? IS NULL OR farmers.ward = ?)
          AND (? IS NULL OR farmers.full_name LIKE ? OR farmers.phone_number LIKE ?)
        GROUP BY farmers.farmer_id ORDER BY farmers.full_name
    """
    search_value = f"%{search}%" if search else None
    with connect() as db:
        return [dict(row) for row in db.execute(
            query, (ward, ward, search_value, search_value, search_value)
        )]


@app.post("/api/farmers", status_code=201)
def onboard_farmer(request: FarmerOnboardingRequest) -> dict[str, Any]:
    if not request.full_name.strip() or not request.phone_number.strip() or not request.ward.strip():
        raise HTTPException(status_code=422, detail="Name, phone number, and ward are required.")
    farmer_id = f"FARM-{uuid.uuid4().hex[:10].upper()}"
    with connect() as db:
        db.execute(
            """INSERT INTO farmers
            (farmer_id, full_name, phone_number, ward, agroclimatic_zone,
             cooperative_name, preferred_language)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (farmer_id, request.full_name.strip(), request.phone_number.strip(),
             request.ward.strip(), request.agroclimatic_zone.strip(),
             request.cooperative_name.strip(), request.preferred_language),
        )
        db.execute(
            "INSERT INTO mcp_audit_log VALUES (NULL, ?, ?, ?, ?, ?, ?, ?)",
            (datetime.now(UTC).isoformat(), f"ONBOARD-{farmer_id}", "registry",
             "farmer_onboarding", "create",
             json.dumps(request.model_dump()), json.dumps({"farmer_id": farmer_id})),
        )
        row = db.execute("SELECT * FROM farmers WHERE farmer_id = ?", (farmer_id,)).fetchone()
    return dict(row)


@app.post("/api/plots", status_code=201)
def onboard_plot(request: PlotOnboardingRequest) -> dict[str, Any]:
    if request.acreage <= 0 or not (-5 <= request.latitude <= 5) or not (33 <= request.longitude <= 42):
        raise HTTPException(status_code=422, detail="Enter a positive acreage and a valid Kenya coordinate.")
    plot_id = f"PLOT-{uuid.uuid4().hex[:10].upper()}"
    with connect() as db:
        if not db.execute("SELECT 1 FROM farmers WHERE farmer_id = ?", (request.farmer_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Farmer was not found.")
        db.execute(
            """INSERT INTO plots
            (plot_id, farmer_id, latitude, longitude, crop_type, planting_date,
             current_growth_stage, acreage, kijanibox_sensor_id, repayment_score,
             subsidy_tier_eligible)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'PENDING')""",
            (plot_id, request.farmer_id, request.latitude, request.longitude,
             request.crop_type.strip(), request.planting_date,
             request.current_growth_stage.strip(), request.acreage,
             request.kijanibox_sensor_id.strip()),
        )
        db.execute(
            "INSERT INTO mcp_audit_log VALUES (NULL, ?, ?, ?, ?, ?, ?, ?)",
            (datetime.now(UTC).isoformat(), f"ONBOARD-{plot_id}", "registry",
             "plot_onboarding", "create", json.dumps(request.model_dump()),
             json.dumps({"plot_id": plot_id})),
        )
        row = db.execute("SELECT * FROM plots WHERE plot_id = ?", (plot_id,)).fetchone()
    return dict(row)


def _distance_km(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> float:
    """Approximate distance for local matching; replace with GIS service at scale."""
    latitude_delta = (latitude_a - latitude_b) * 111.0
    longitude_delta = (longitude_a - longitude_b) * 111.0 * math.cos(math.radians(latitude_a))
    return round(math.sqrt(latitude_delta**2 + longitude_delta**2), 1)


@app.get("/api/partners")
def partners(partner_type: str | None = None, ward: str | None = None) -> list[dict[str, Any]]:
    query = "SELECT * FROM partners WHERE 1=1"
    params: list[str] = []
    if partner_type:
        query += " AND partner_type = ?"
        params.append(partner_type)
    if ward:
        query += " AND ward = ?"
        params.append(ward)
    query += " ORDER BY verified DESC, name"
    with connect() as db:
        return [dict(row) for row in db.execute(query, params)]


@app.get("/api/inputs")
def inputs(category: str | None = None) -> list[dict[str, Any]]:
    query = "SELECT * FROM inputs"
    params: tuple[str, ...] = ()
    if category:
        query += " WHERE category = ?"
        params = (category,)
    query += " ORDER BY name"
    with connect() as db:
        records = [dict(row) for row in db.execute(query, params)]
    for record in records:
        for field in ("crop_types_json", "soil_profiles_json", "climate_zones_json"):
            record[field.removesuffix("_json")] = json.loads(record.pop(field))
    return records


@app.get("/api/operations/summary")
def operations_summary() -> dict[str, int]:
    with connect() as db:
        return {
            "verified_partners": db.execute("SELECT COUNT(*) FROM partners WHERE verified = 1").fetchone()[0],
            "in_stock_inputs": db.execute("SELECT COUNT(*) FROM inputs WHERE stock_status = 'IN_STOCK'").fetchone()[0],
            "recommended_assignments": db.execute(
                "SELECT COUNT(*) FROM farm_assignments WHERE status = 'RECOMMENDED'"
            ).fetchone()[0],
            "confirmed_assignments": db.execute(
                "SELECT COUNT(*) FROM farm_assignments WHERE status = 'CONFIRMED'"
            ).fetchone()[0],
        }


@app.get("/api/operations/recommendations")
def recommendations_get(
    ward: str | None = None,
    crop_type: str | None = None,
    category: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    return recommendations(RecommendationRequest(
        ward=ward, crop_type=crop_type, category=category, limit=limit
    ))


@app.post("/api/operations/recommendations")
def recommendations(request: RecommendationRequest) -> list[dict[str, Any]]:
    limit = max(1, min(request.limit, 100))
    with connect() as db:
        plots = db.execute(
            """
            SELECT plots.*, farmers.ward, farmers.agroclimatic_zone,
                   telemetry_cache.soil_moisture_pct
            FROM plots
            JOIN farmers ON farmers.farmer_id = plots.farmer_id
            LEFT JOIN telemetry_cache ON telemetry_cache.ward = farmers.ward
            WHERE (? IS NULL OR farmers.ward = ?)
              AND (? IS NULL OR plots.crop_type = ?)
            ORDER BY plots.plot_id
            """,
            (request.ward, request.ward, request.crop_type, request.crop_type),
        ).fetchall()
        partners_rows = [dict(row) for row in db.execute("SELECT * FROM partners WHERE verified = 1")]
        inputs_rows = [dict(row) for row in db.execute(
            "SELECT * FROM inputs WHERE stock_status = 'IN_STOCK'"
        )]

    recommendations_list: list[dict[str, Any]] = []
    for plot in plots:
        moisture = plot["soil_moisture_pct"]
        soil_profile = "waterlogged" if moisture is not None and moisture > 35 else (
            "low_moisture" if moisture is not None and moisture < 20 else "loam"
        )
        candidates = []
        for item in inputs_rows:
            crop_types = json.loads(item["crop_types_json"])
            soil_profiles = json.loads(item["soil_profiles_json"])
            climate_zones = json.loads(item["climate_zones_json"])
            partner = next((p for p in partners_rows if p["partner_id"] == item["partner_id"]), None)
            if not partner:
                continue
            distance = _distance_km(plot["latitude"], plot["longitude"], partner["latitude"], partner["longitude"])
            if distance > partner["service_radius_km"]:
                continue
            score = 2
            reasons = [f"{distance} km from {partner['name']}"]
            if plot["crop_type"] in crop_types:
                score += 3
                reasons.append(f"supports {plot['crop_type']}")
            if soil_profile in soil_profiles:
                score += 3
                reasons.append(f"fits {soil_profile} soil conditions")
            if plot["agroclimatic_zone"] in climate_zones:
                score += 2
                reasons.append(f"approved for {plot['agroclimatic_zone']} climate zone")
            if item["category"] == (request.category or item["category"]):
                score += 2
            elif request.category:
                continue
            candidates.append((score, distance, item, partner, reasons, soil_profile))
        if not candidates:
            continue
        score, distance, item, partner, reasons, soil_profile = min(
            candidates, key=lambda candidate: (-candidate[0], candidate[1])
        )
        recommendations_list.append({
            "plot_id": plot["plot_id"], "farmer_id": plot["farmer_id"], "ward": plot["ward"],
            "crop_type": plot["crop_type"], "soil_profile": soil_profile,
            "soil_moisture_pct": plot["soil_moisture_pct"], "agroclimatic_zone": plot["agroclimatic_zone"],
            "partner": {"partner_id": partner["partner_id"], "name": partner["name"], "partner_type": partner["partner_type"]},
            "input": {"input_id": item["input_id"], "name": item["name"], "category": item["category"],
                      "unit": item["unit"], "price_kes": item["price_kes"]},
            "score": score, "reasons": reasons,
        })
    return recommendations_list[:limit]


@app.post("/api/operations/assignments")
def create_assignment(request: AssignmentRequest) -> dict[str, Any]:
    assignment_id = f"ASN-{uuid.uuid4().hex[:10].upper()}"
    with connect() as db:
        plot = db.execute(
            "SELECT plot_id FROM plots WHERE plot_id = ?", (request.plot_id,)
        ).fetchone()
        partner = db.execute(
            "SELECT partner_id, name FROM partners WHERE partner_id = ? AND verified = 1",
            (request.partner_id,),
        ).fetchone()
        if not plot or not partner:
            raise HTTPException(status_code=404, detail="Plot or verified partner was not found.")
        if request.input_id:
            input_row = db.execute(
                "SELECT input_id FROM inputs WHERE input_id = ? AND stock_status = 'IN_STOCK'",
                (request.input_id,),
            ).fetchone()
            if not input_row:
                raise HTTPException(status_code=404, detail="Input is not in stock.")
        db.execute(
            """
            INSERT INTO farm_assignments
              (assignment_id, plot_id, partner_id, input_id, status, reason_json, created_at, officer_id)
            VALUES (?, ?, ?, ?, 'CONFIRMED', ?, ?, ?)
            """,
            (assignment_id, request.plot_id, request.partner_id, request.input_id,
             json.dumps({"source": "officer_confirmed", "partner_name": partner["name"]}),
             datetime.now(UTC).isoformat(), request.officer_id),
        )
    return {"assignment_id": assignment_id, "status": "CONFIRMED", "plot_id": request.plot_id,
            "partner_id": request.partner_id, "input_id": request.input_id}
