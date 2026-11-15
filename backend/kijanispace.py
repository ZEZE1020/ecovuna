"""Authenticated KijaniSpace client and telemetry normalization."""
from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import httpx


class KijaniSpaceError(RuntimeError):
    """Raised when KijaniSpace cannot provide a valid response."""


def configured() -> bool:
    return all(os.getenv(name) for name in (
        "KIJANISPACE_API_BASE_URL",
        "KIJANISPACE_USERNAME",
        "KIJANISPACE_PASSWORD",
    ))


def _latest(values: list[Any], default: float = 0.0) -> float:
    numeric = [float(value) for value in values if isinstance(value, (int, float))]
    return numeric[-1] if numeric else default


def fetch_land(latitude: float, longitude: float) -> dict[str, Any]:
    if not configured():
        raise KijaniSpaceError("KijaniSpace credentials are not configured")
    base_url = os.environ["KIJANISPACE_API_BASE_URL"].rstrip("/")
    timeout = float(os.getenv("KIJANISPACE_TIMEOUT_SECONDS", "15"))
    try:
        response = httpx.get(
            f"{base_url}/v1/agro_climate/land",
            params={"lat": latitude, "lon": longitude},
            auth=(
                os.environ["KIJANISPACE_USERNAME"],
                os.environ["KIJANISPACE_PASSWORD"],
            ),
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise KijaniSpaceError("KijaniSpace land request failed") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("forecast_data"), dict):
        raise KijaniSpaceError("KijaniSpace land response has an unexpected shape")
    return payload


def normalize_land(ward: str, sensor_id: str, latitude: float, longitude: float,
                   payload: dict[str, Any]) -> dict[str, Any]:
    forecast = payload["forecast_data"]
    location = payload.get("location", {})
    vegetation = payload.get("data", {}).get("vegetation_indices", {})
    precipitation = forecast.get("precipitation", [])
    soil_moisture = forecast.get("soilmoisture_0to10cm", [])
    soil_temperature = forecast.get("soiltemperature_0to10cm", [])
    timestamp = (forecast.get("time") or [datetime.now(UTC).isoformat()])[-1]
    return {
        "ward": ward,
        "sensor_id": sensor_id,
        "timestamp": timestamp,
        "soil_moisture_pct": _latest(soil_moisture),
        "soil_temp_c": _latest(soil_temperature),
        "precipitation_7d_mm": round(sum(
            float(value) for value in precipitation if isinstance(value, (int, float))
        ), 2),
        "rainfall_anomaly_mm": 0.0,
        "raw_payload_json": {
            "source": "kijanispace",
            "synthetic": False,
            "latitude": latitude,
            "longitude": longitude,
            "elevation_m": location.get("elevation"),
            "vegetation_indices": vegetation,
            "landuse": payload.get("data", {}).get("dataset", {}).get("landuse"),
            "forecast_model_run": payload.get("forecast_info", {}).get("model_run"),
        },
    }
