"""Deterministic, offline-safe ingestion of registry and extension operations data."""
from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path

from .db import connect, initialize, insert_json

WARDS = ("Homa Bay Central", "Ndhiwa", "Suba South", "Karachuonyo")
CROPS = ("Maize WH-505", "Sorghum Gadam", "Beans Rosecoco")
STAGES = ("Germination_0_14d", "Vegetative_15_40d", "Flowering_Tasseling_41_65d")


def _telemetry(ward: str, index: int) -> dict[str, object]:
    moisture = (18.0 + index * 1.7) if ward != "Ndhiwa" else 42.0
    return {
        "ward": ward, "sensor_id": f"KJB-HB-{index + 1:02d}",
        "timestamp": datetime.now(UTC).isoformat(),
        "soil_moisture_pct": moisture, "soil_temp_c": 25.4,
        "precipitation_7d_mm": 12.0 if ward != "Ndhiwa" else 88.0,
        "rainfall_anomaly_mm": -31.0 if ward != "Ndhiwa" else 44.0,
        "raw_payload_json": {"source": "offline_fixture", "synthetic": True},
    }


def seed_registry() -> None:
    with connect() as db:
        for index in range(24):
            ward = WARDS[index // 6]
            farmer_id = f"SYNTH-HB-{index + 1:03d}"
            plot_id = f"PLOT-HB-{101 + index}"
            insert_json(db, "farmers", {
                "farmer_id": farmer_id, "full_name": f"Synthetic Farmer {index + 1:02d}",
                "phone_number": f"+2547{10000000 + index:08d}", "ward": ward,
                "agroclimatic_zone": "LM3" if index % 2 else "LM4",
                "cooperative_name": f"{ward} Growers Cooperative",
                "preferred_language": ("Swahili", "Dholuo", "English")[index % 3],
            })
            insert_json(db, "plots", {
                "plot_id": plot_id, "farmer_id": farmer_id,
                "latitude": -0.5273 + index * 0.001, "longitude": 34.4571 + index * 0.001,
                "crop_type": CROPS[index % len(CROPS)], "planting_date": str(date(2026, 10, 1)),
                "current_growth_stage": STAGES[index % len(STAGES)], "acreage": 1.0 + (index % 3) * 0.5,
                "kijanibox_sensor_id": f"KJB-HB-{index // 2 + 1:02d}",
                "repayment_score": 72 + index % 25,
                "subsidy_tier_eligible": "TIER_A_FULL" if index % 2 == 0 else "TIER_B_PARTIAL",
            })
        for index, ward in enumerate(WARDS):
            insert_json(db, "telemetry_cache", _telemetry(ward, index))
        partners = [
            ("AGV-HBC-001", "Homa Bay Farmers Supply", "AGROVET", "Homa Bay Central", -0.5273, 34.4571, 18.0, "Mary Achieng", "+254700000101"),
            ("AGV-NDW-001", "Ndhiwa Agri Input Centre", "AGROVET", "Ndhiwa", -0.4080, 34.3700, 22.0, "Peter Ouma", "+254700000102"),
            ("FRT-SUB-001", "Lake Victoria Soil & Fertility Co-op", "FERTILISER", "Suba South", -0.4800, 34.2000, 30.0, "Akinyi Odhiambo", "+254700000103"),
            ("SED-KAR-001", "Karachuonyo Certified Seed Hub", "SEED", "Karachuonyo", -0.6200, 34.6000, 25.0, "Tom Otieno", "+254700000104"),
        ]
        for partner in partners:
            insert_json(db, "partners", {
                "partner_id": partner[0], "name": partner[1], "partner_type": partner[2],
                "ward": partner[3], "latitude": partner[4], "longitude": partner[5],
                "service_radius_km": partner[6], "verified": 1, "contact_name": partner[7],
                "contact_phone": partner[8],
            })
        inputs = [
            ("INP-HYDRO-001", "Root-zone hydrogel", "SOIL_AMENDMENT", ["Maize WH-505"], ["sandy", "low_moisture"], ["LM3", "LM4"], "25 kg bag", 300.0, "AGV-HBC-001"),
            ("INP-FERT-001", "Balanced NPK 17:17:17", "FERTILISER", ["Maize WH-505", "Sorghum Gadam"], ["loam", "low_fertility"], ["LM3", "LM4"], "50 kg bag", 4200.0, "FRT-SUB-001"),
            ("INP-SEED-001", "Certified drought-tolerant maize seed", "SEED", ["Maize WH-505"], ["sandy", "loam"], ["LM3", "LM4"], "2 kg pack", 650.0, "SED-KAR-001"),
            ("INP-FUNG-001", "Maize fungicide package", "CROP_PROTECTION", ["Maize WH-505"], ["waterlogged", "loam"], ["LM3", "LM4"], "farm pack", 1800.0, "AGV-NDW-001"),
        ]
        for item in inputs:
            insert_json(db, "inputs", {
                "input_id": item[0], "name": item[1], "category": item[2],
                "crop_types_json": item[3], "soil_profiles_json": item[4],
                "climate_zones_json": item[5], "unit": item[6], "price_kes": item[7],
                "partner_id": item[8], "stock_status": "IN_STOCK",
            })


def write_bulletin() -> Path:
    path = Path("data/kalro_bulletins/homabay_agronomy_2026.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Homa Bay Agronomy Bulletin 2026\n\n"
        "Source IDs: `KMD-2026-10-14`, `KALRO-HB-2026-01`, `KALRO-HB-2026-02`, `KALRO-HB-2026-03`.\n\n"
        "- **KALRO-HB-2026-01**: In germination maize during a dry spell, block nitrogen top-dressing and protect roots with hydrogel.\n"
        "- **KALRO-HB-2026-02**: In flowering maize during a dry spell, use foliar potassium and targeted irrigation.\n"
        "- **KALRO-HB-2026-03**: In waterlogged plots, open drainage and use a fungicide package.\n",
        encoding="utf-8",
    )
    return path


def ingest(offline_fallback: bool = False) -> None:
    initialize()
    seed_registry()
    with connect() as db:
        db.execute("DELETE FROM telemetry_cache")
        for index, ward in enumerate(WARDS):
            insert_json(db, "telemetry_cache", _telemetry(ward, index))
    write_bulletin()
    print(json.dumps({"status": "ok", "offline": offline_fallback, "farmers": 24, "wards": len(WARDS)}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline-fallback", action="store_true")
    args = parser.parse_args()
    ingest(args.offline_fallback)


if __name__ == "__main__":
    main()
