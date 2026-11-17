"""Farm registry, ward telemetry, staged advisories, and USSD router."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Form, Response
from fastapi.responses import PlainTextResponse

from ..contracts import (
    AdvisoryResponse,
    DashboardCountsResponse,
    DashboardResponse,
    FarmerOnboardingRequest,
    FarmerResponse,
    PlotOnboardingRequest,
    PlotResponse,
    TelemetryReadingResponse,
    TelemetryResponse,
    WardSummaryResponse,
)
from ..db import connect
from ..errors import InvalidRequestError, NotFoundError

router = APIRouter(tags=["registry"])


@router.get("/api/dashboard", response_model=DashboardResponse)
def dashboard() -> DashboardResponse:
    """Return operational counts and ward summaries from the local registry."""
    with connect() as db:
        counts = DashboardCountsResponse(
            households=db.execute("SELECT COUNT(*) FROM farmers").fetchone()[0],
            plots=db.execute("SELECT COUNT(*) FROM plots").fetchone()[0],
            advisories=db.execute("SELECT COUNT(*) FROM staged_advisories").fetchone()[0],
            pending_advisories=db.execute(
                "SELECT COUNT(*) FROM staged_advisories WHERE status = 'PENDING_WAO_APPROVAL'"
            ).fetchone()[0],
            field_visits_due=0,
        )
        wards = [
            WardSummaryResponse.model_validate(dict(row))
            for row in db.execute(
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
            )
        ]
    return DashboardResponse(counts=counts, wards=wards)


@router.get("/api/advisories", response_model=list[AdvisoryResponse])
def advisories(status: str | None = None) -> list[AdvisoryResponse]:
    """Return staged advisory records with their JSON fields decoded."""
    query = "SELECT * FROM staged_advisories"
    params: tuple[str, ...] = ()
    if status:
        query += " WHERE status = ?"
        params = (status,)
    query += " ORDER BY rowid DESC LIMIT 50"
    with connect() as db:
        records = [dict(row) for row in db.execute(query, params)]
    decoded: list[AdvisoryResponse] = []
    for record in records:
        for field in ("affected_plot_ids_json", "citations_json"):
            record[field.removesuffix("_json")] = json.loads(record.pop(field))
        decoded.append(AdvisoryResponse.model_validate(record))
    return decoded


@router.get("/api/telemetry", response_model=TelemetryResponse)
def telemetry(ward: str | None = None) -> TelemetryResponse:
    """Return normalized readings with live-source provenance for the console."""
    query = "SELECT * FROM telemetry_cache"
    params: tuple[str, ...] = ()
    if ward:
        query += " WHERE ward = ?"
        params = (ward,)
    query += " ORDER BY timestamp DESC, id DESC LIMIT 20"
    with connect() as db:
        readings = [dict(row) for row in db.execute(query, params)]
    normalized_readings: list[TelemetryReadingResponse] = []
    for reading in readings:
        raw_payload = reading.get("raw_payload_json")
        if isinstance(raw_payload, str):
            try:
                reading["raw_payload_json"] = json.loads(raw_payload)
            except json.JSONDecodeError:
                reading["raw_payload_json"] = {"source": "unknown"}
        payload = reading["raw_payload_json"]
        reading["source"] = payload.get("source", "telemetry_cache")
        reading["freshness"] = (
            "live" if payload.get("source") == "kijanispace" else "cached"
        )
        normalized_readings.append(TelemetryReadingResponse.model_validate(reading))
    return TelemetryResponse(ward=ward, readings=normalized_readings)


@router.get("/api/farmers", response_model=list[FarmerResponse])
def farmers(
    ward: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[FarmerResponse]:
    """Return a paginated page of the county registry; totals come from /api/dashboard."""
    query = """
        SELECT farmers.*, COUNT(plots.plot_id) AS plot_count
        FROM farmers LEFT JOIN plots ON plots.farmer_id = farmers.farmer_id
        WHERE (? IS NULL OR farmers.ward = ?)
          AND (? IS NULL OR farmers.full_name LIKE ? OR farmers.phone_number LIKE ?)
        GROUP BY farmers.farmer_id ORDER BY farmers.full_name
        LIMIT ? OFFSET ?
    """
    search_value = f"%{search}%" if search else None
    page_size = max(1, min(limit, 200))
    page_offset = max(0, offset)
    with connect() as db:
        return [
            FarmerResponse.model_validate(dict(row))
            for row in db.execute(
                query,
                (
                    ward,
                    ward,
                    search_value,
                    search_value,
                    search_value,
                    page_size,
                    page_offset,
                ),
            )
        ]


@router.post("/api/farmers", status_code=201, response_model=FarmerResponse)
def onboard_farmer(request: FarmerOnboardingRequest) -> FarmerResponse:
    if (
        not request.full_name.strip()
        or not request.phone_number.strip()
        or not request.ward.strip()
    ):
        raise InvalidRequestError(
            "Name, phone number, and ward are required.",
            error_code="INVALID_FARMER_INPUT",
        )
    farmer_id = f"FARM-{uuid.uuid4().hex[:10].upper()}"
    with connect() as db:
        db.execute(
            """INSERT INTO farmers
            (farmer_id, full_name, phone_number, ward, agroclimatic_zone,
             cooperative_name, preferred_language)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                farmer_id,
                request.full_name.strip(),
                request.phone_number.strip(),
                request.ward.strip(),
                request.agroclimatic_zone.strip(),
                request.cooperative_name.strip(),
                request.preferred_language,
            ),
        )
        db.execute(
            "INSERT INTO mcp_audit_log VALUES (NULL, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(UTC).isoformat(),
                f"ONBOARD-{farmer_id}",
                "registry",
                "farmer_onboarding",
                "create",
                json.dumps(request.model_dump()),
                json.dumps({"farmer_id": farmer_id}),
            ),
        )
        row = db.execute(
            "SELECT * FROM farmers WHERE farmer_id = ?", (farmer_id,)
        ).fetchone()
    return FarmerResponse.model_validate(dict(row))


@router.post("/api/plots", status_code=201, response_model=PlotResponse)
def onboard_plot(request: PlotOnboardingRequest) -> PlotResponse:
    if (
        request.acreage <= 0
        or not (-5 <= request.latitude <= 5)
        or not (33 <= request.longitude <= 42)
    ):
        raise InvalidRequestError(
            "Enter a positive acreage and a valid Kenya coordinate.",
            error_code="INVALID_PLOT_COORDINATES",
        )
    plot_id = f"PLOT-{uuid.uuid4().hex[:10].upper()}"
    with connect() as db:
        if not db.execute(
            "SELECT 1 FROM farmers WHERE farmer_id = ?", (request.farmer_id,)
        ).fetchone():
            raise NotFoundError(
                "Farmer was not found.",
                error_code="FARMER_NOT_FOUND",
            )
        db.execute(
            """INSERT INTO plots
            (plot_id, farmer_id, latitude, longitude, crop_type, planting_date,
             current_growth_stage, acreage, kijanibox_sensor_id, repayment_score,
             subsidy_tier_eligible)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'PENDING')""",
            (
                plot_id,
                request.farmer_id,
                request.latitude,
                request.longitude,
                request.crop_type.strip(),
                request.planting_date,
                request.current_growth_stage.strip(),
                request.acreage,
                request.kijanibox_sensor_id.strip(),
            ),
        )
        db.execute(
            "INSERT INTO mcp_audit_log VALUES (NULL, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(UTC).isoformat(),
                f"ONBOARD-{plot_id}",
                "registry",
                "plot_onboarding",
                "create",
                json.dumps(request.model_dump()),
                json.dumps({"plot_id": plot_id}),
            ),
        )
        row = db.execute("SELECT * FROM plots WHERE plot_id = ?", (plot_id,)).fetchone()
    return PlotResponse.model_validate(dict(row))


@router.post("/api/ussd")
async def ussd_callback(
    phoneNumber: str = Form(...), text: str = Form(...)
) -> Response:
    """USSD endpoint allowing farmers to check their subsidy status."""
    _ = phoneNumber
    if text:
        farmer_id = text.strip()
        with connect() as db:
            plot = db.execute(
                "SELECT subsidy_tier_eligible FROM plots WHERE farmer_id = ?",
                (farmer_id,),
            ).fetchone()
        if plot:
            response_text = f"CON Your subsidy status is: {plot['subsidy_tier_eligible']}"
        else:
            response_text = "CON We could not find a farmer with that ID."
    else:
        response_text = "CON Please enter your farmer ID to check your subsidy status."
    return PlainTextResponse(response_text)
