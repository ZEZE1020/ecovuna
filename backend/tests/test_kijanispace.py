from backend.kijanispace import normalize_land


def test_normalize_land_preserves_live_provenance_and_latest_values() -> None:
    payload = {
        "location": {"elevation": 1180},
        "forecast_data": {
            "time": ["2026-11-14T00:00:00Z", "2026-11-15T00:00:00Z"],
            "precipitation": [1.5, 2.5],
            "soilmoisture_0to10cm": [18, 22],
            "soiltemperature_0to10cm": [24, 25],
        },
        "data": {
            "dataset": {"landuse": "maize"},
            "vegetation_indices": {"NDVI": 0.61},
        },
        "forecast_info": {"model_run": "2026-11-14T06:00:00Z"},
    }
    reading = normalize_land("Homa Bay Central", "KJ-01", -0.5, 34.7, payload)
    assert reading["soil_moisture_pct"] == 22
    assert reading["precipitation_7d_mm"] == 4
    assert reading["raw_payload_json"]["source"] == "kijanispace"
    assert reading["raw_payload_json"]["forecast_model_run"] == "2026-11-14T06:00:00Z"
