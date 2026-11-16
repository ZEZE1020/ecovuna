"""Extension partner matching, input catalog, and farm assignments router."""

from __future__ import annotations

import json
import math
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter

from ..contracts import (
    AssignmentRequest,
    AssignmentResponse,
    InputCatalogResponse,
    OperationsSummaryResponse,
    PartnerResponse,
    RecommendationInputResponse,
    RecommendationItemResponse,
    RecommendationPartnerResponse,
    RecommendationRequest,
)
from ..db import connect
from ..errors import NotFoundError

router = APIRouter(tags=["operations"])


def _distance_km(
    latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float
) -> float:
    """Approximate distance for local matching; replace with GIS service at scale."""
    latitude_delta = (latitude_a - latitude_b) * 111.0
    longitude_delta = (
        (longitude_a - longitude_b) * 111.0 * math.cos(math.radians(latitude_a))
    )
    return round(math.sqrt(latitude_delta**2 + longitude_delta**2), 1)


@router.get("/api/partners", response_model=list[PartnerResponse])
def partners(
    partner_type: str | None = None, ward: str | None = None
) -> list[PartnerResponse]:
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
        return [
            PartnerResponse.model_validate(dict(row))
            for row in db.execute(query, params)
        ]


@router.get("/api/inputs", response_model=list[InputCatalogResponse])
def inputs(category: str | None = None) -> list[InputCatalogResponse]:
    query = "SELECT * FROM inputs"
    params: tuple[str, ...] = ()
    if category:
        query += " WHERE category = ?"
        params = (category,)
    query += " ORDER BY name"
    with connect() as db:
        records = [dict(row) for row in db.execute(query, params)]
    catalog: list[InputCatalogResponse] = []
    for record in records:
        for field in ("crop_types_json", "soil_profiles_json", "climate_zones_json"):
            record[field.removesuffix("_json")] = json.loads(record.pop(field))
        catalog.append(InputCatalogResponse.model_validate(record))
    return catalog


@router.get("/api/operations/summary", response_model=OperationsSummaryResponse)
def operations_summary() -> OperationsSummaryResponse:
    with connect() as db:
        return OperationsSummaryResponse(
            verified_partners=db.execute(
                "SELECT COUNT(*) FROM partners WHERE verified = 1"
            ).fetchone()[0],
            in_stock_inputs=db.execute(
                "SELECT COUNT(*) FROM inputs WHERE stock_status = 'IN_STOCK'"
            ).fetchone()[0],
            recommended_assignments=db.execute(
                "SELECT COUNT(*) FROM farm_assignments WHERE status = 'RECOMMENDED'"
            ).fetchone()[0],
            confirmed_assignments=db.execute(
                "SELECT COUNT(*) FROM farm_assignments WHERE status = 'CONFIRMED'"
            ).fetchone()[0],
        )


@router.get(
    "/api/operations/recommendations",
    response_model=list[RecommendationItemResponse],
)
def recommendations_get(
    ward: str | None = None,
    crop_type: str | None = None,
    category: str | None = None,
    limit: int = 20,
) -> list[RecommendationItemResponse]:
    clamped_limit = max(1, min(limit, 100))
    return recommendations(
        RecommendationRequest(
            ward=ward, crop_type=crop_type, category=category, limit=clamped_limit
        )
    )


@router.post(
    "/api/operations/recommendations",
    response_model=list[RecommendationItemResponse],
)
def recommendations(request: RecommendationRequest) -> list[RecommendationItemResponse]:
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
        partners_rows = [
            dict(row) for row in db.execute("SELECT * FROM partners WHERE verified = 1")
        ]
        inputs_rows = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM inputs WHERE stock_status = 'IN_STOCK'"
            )
        ]

    recommendations_list: list[RecommendationItemResponse] = []
    for plot in plots:
        moisture = plot["soil_moisture_pct"]
        soil_profile = (
            "waterlogged"
            if moisture is not None and moisture > 35
            else ("low_moisture" if moisture is not None and moisture < 20 else "loam")
        )
        candidates = []
        for item in inputs_rows:
            crop_types = json.loads(item["crop_types_json"])
            soil_profiles = json.loads(item["soil_profiles_json"])
            climate_zones = json.loads(item["climate_zones_json"])
            partner = next(
                (p for p in partners_rows if p["partner_id"] == item["partner_id"]),
                None,
            )
            if not partner:
                continue
            distance = _distance_km(
                plot["latitude"],
                plot["longitude"],
                partner["latitude"],
                partner["longitude"],
            )
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
                reasons.append(
                    f"approved for {plot['agroclimatic_zone']} climate zone"
                )
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
        recommendations_list.append(
            RecommendationItemResponse(
                plot_id=plot["plot_id"],
                farmer_id=plot["farmer_id"],
                ward=plot["ward"],
                crop_type=plot["crop_type"],
                soil_profile=soil_profile,
                soil_moisture_pct=plot["soil_moisture_pct"],
                agroclimatic_zone=plot["agroclimatic_zone"],
                partner=RecommendationPartnerResponse(
                    partner_id=partner["partner_id"],
                    name=partner["name"],
                    partner_type=partner["partner_type"],
                ),
                input=RecommendationInputResponse(
                    input_id=item["input_id"],
                    name=item["name"],
                    category=item["category"],
                    unit=item["unit"],
                    price_kes=item["price_kes"],
                ),
                score=score,
                reasons=reasons,
            )
        )
    return recommendations_list[:limit]


@router.post("/api/operations/assignments", response_model=AssignmentResponse)
def create_assignment(request: AssignmentRequest) -> AssignmentResponse:
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
            raise NotFoundError(
                "Plot or verified partner was not found.",
                error_code="ASSIGNMENT_TARGET_NOT_FOUND",
            )
        if request.input_id:
            input_row = db.execute(
                "SELECT input_id FROM inputs WHERE input_id = ? AND stock_status = 'IN_STOCK'",
                (request.input_id,),
            ).fetchone()
            if not input_row:
                raise NotFoundError(
                    "Input is not in stock.",
                    error_code="INPUT_OUT_OF_STOCK",
                )
        db.execute(
            """
            INSERT INTO farm_assignments
              (assignment_id, plot_id, partner_id, input_id, status, reason_json, created_at, officer_id)
            VALUES (?, ?, ?, ?, 'CONFIRMED', ?, ?, ?)
            """,
            (
                assignment_id,
                request.plot_id,
                request.partner_id,
                request.input_id,
                json.dumps(
                    {"source": "officer_confirmed", "partner_name": partner["name"]}
                ),
                datetime.now(UTC).isoformat(),
                request.officer_id,
            ),
        )
    return AssignmentResponse(
        assignment_id=assignment_id,
        status="CONFIRMED",
        plot_id=request.plot_id,
        partner_id=request.partner_id,
        input_id=request.input_id,
    )
