"""Deterministic, offline-safe ingestion of registry and extension operations data."""
from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path

from .db import connect, initialize, insert_json

WARDS = (
    "Homa Bay Central",
    "Ndhiwa",
    "Suba South",
    "Karachuonyo",
    "Rachuonyo North",
)
WARD_CENTRES = {
    "Homa Bay Central": (-0.5273, 34.4571),
    "Ndhiwa": (-0.4080, 34.3700),
    "Suba South": (-0.4800, 34.2000),
    "Karachuonyo": (-0.6200, 34.6000),
    "Rachuonyo North": (-0.3812, 34.6341),
}
CROPS = ("Maize WH-505", "Sorghum Gadam", "Beans Rosecoco")
STAGES = ("Germination_0_14d", "Vegetative_15_40d", "Flowering_Tasseling_41_65d")

FARMER_COUNT = 1850
FARMERS_PER_WARD = FARMER_COUNT // len(WARDS)

# Deterministic name pools keep the registry realistic without shipping fixture rows in the UI.
FIRST_NAMES = (
    "Atieno", "Beatrice", "John", "Millicent", "Patrick", "Grace", "Samuel",
    "Rose", "Peter", "Jane", "Michael", "Esther", "Daniel", "Linet", "George",
    "Mary", "Joseph", "Nancy", "Kevin", "Faith", "Alice", "Christine",
    "Wycliffe", "Agnes", "Dennis", "Emmanuel", "Caroline", "Maurice",
    "Judith", "Collins",
)
MIDDLE_INITIALS = tuple("ABCDEFGHJKLMNPRSTW")
SURNAMES = (
    "Odhiambo", "Auma", "Owino", "Akinyi", "Onyango", "Adhiambo", "Ouma",
    "Anyango", "Otieno", "Awuor", "Ochieng", "Akoth", "Ogola", "Achieng",
    "Omondi", "Odera", "Odongo", "Kerubo", "Nyambura", "Owade", "Obonyo",
    "Oloo", "Okech", "Nyakwar",
)


def _farmer_name(index: int) -> str:
    first = FIRST_NAMES[index % len(FIRST_NAMES)]
    middle = MIDDLE_INITIALS[(index // len(FIRST_NAMES)) % len(MIDDLE_INITIALS)]
    surname = SURNAMES[(index // (len(FIRST_NAMES) * len(MIDDLE_INITIALS))) % len(SURNAMES)]
    return f"{first} {middle}. {surname}"


def _telemetry(ward: str, index: int) -> dict[str, object]:
    if ward == "Rachuonyo North":
        return {
            "ward": ward,
            "sensor_id": "KJB-HB-04",
            "timestamp": datetime.now(UTC).isoformat(),
            "soil_moisture_pct": 13.4,
            "soil_temp_c": 29.8,
            "precipitation_7d_mm": 6.5,
            "rainfall_anomaly_mm": -28.0,
            "raw_payload_json": {
                "source": "KijaniBox IoT + Sentinel-2 NDVI",
                "moisture_delta_pct": -28.0,
                "ndvi_anomaly_status": "SEVERE_DEFICIT (-0.24 NDVI)",
                "pest_thermal_alert": "Fall Armyworm (Spodoptera frugiperda) thermal threshold crossed",
                "registered_smallholders": FARMERS_PER_WARD,
                "lead_persona": "Mama Atieno",
                "wao_officer": "David Ochieng — WAO-HB-014",
                "vegetation_indices": {
                    "NDVI": 0.31,
                    "vegetation_health_index": 38,
                    "vegetation_condition_index": 34,
                },
            },
        }
    moisture = (18.0 + index * 1.7) if ward != "Ndhiwa" else 42.0
    return {
        "ward": ward, "sensor_id": f"KJB-HB-{index + 1:02d}",
        "timestamp": datetime.now(UTC).isoformat(),
        "soil_moisture_pct": moisture, "soil_temp_c": 25.4,
        "precipitation_7d_mm": 12.0 if ward != "Ndhiwa" else 88.0,
        "rainfall_anomaly_mm": -31.0 if ward != "Ndhiwa" else 44.0,
        "raw_payload_json": {
            "source": "offline_fixture",
            "synthetic": True,
            "moisture_delta_pct": -18.0 if ward != "Ndhiwa" else 24.0,
            "ndvi_anomaly_status": "MODERATE_STRESS" if ward != "Ndhiwa" else "WATERLOGGED_LOWLAND",
            "registered_smallholders": FARMERS_PER_WARD,
            "vegetation_indices": {
                "NDVI": 0.44 if ward != "Ndhiwa" else 0.52,
                "vegetation_health_index": 54,
            },
        },
    }


def seed_registry() -> None:
    with connect() as db:
        db.execute("DELETE FROM farm_assignments")
        db.execute("DELETE FROM staged_advisories")
        db.execute("DELETE FROM phone_messages")
        db.execute("DELETE FROM mcp_audit_log")
        db.execute("DELETE FROM plots")
        db.execute("DELETE FROM farmers")
        db.execute("DELETE FROM partners")
        db.execute("DELETE FROM inputs")
        for ward_index, ward in enumerate(WARDS):
            centre_latitude, centre_longitude = WARD_CENTRES[ward]
            for local_index in range(FARMERS_PER_WARD):
                index = ward_index * FARMERS_PER_WARD + local_index
                farmer_id = f"HB-FRM-{index + 1:04d}"
                plot_id = f"PLOT-HB-{index + 1:04d}"
                # Keep the lead persona from the Rachuonyo North field story.
                is_lead_persona = ward == "Rachuonyo North" and local_index == 0
                name = "Mama Atieno" if is_lead_persona else _farmer_name(index)
                insert_json(db, "farmers", {
                    "farmer_id": farmer_id, "full_name": name,
                    "phone_number": f"+2547{20000000 + index:08d}", "ward": ward,
                    "agroclimatic_zone": "LM3" if index % 2 else "LM4",
                    "cooperative_name": f"{ward} Smallholders Union",
                    "preferred_language": ("Swahili", "Dholuo", "English")[index % 3],
                })
                insert_json(db, "plots", {
                    "plot_id": plot_id, "farmer_id": farmer_id,
                    "latitude": round(centre_latitude + ((index % 17) - 8) * 0.006, 5),
                    "longitude": round(centre_longitude + ((index % 13) - 6) * 0.006, 5),
                    "crop_type": CROPS[index % len(CROPS)], "planting_date": str(date(2026, 10, 1)),
                    "current_growth_stage": STAGES[index % len(STAGES)],
                    "acreage": 1.0 + (index % 3) * 0.5,
                    "kijanibox_sensor_id": f"KJB-HB-{ward_index + 1:02d}",
                    "repayment_score": 72 + index % 25,
                    "subsidy_tier_eligible": "TIER_A_FULL" if index % 2 == 0 else "TIER_B_PARTIAL",
                })
        for index, ward in enumerate(WARDS):
            insert_json(db, "telemetry_cache", _telemetry(ward, index))
        partners = [
            ("PARTNER-001", "Oyugis Agrovet Ltd", "Agro-dealer", "Rachuonyo North", -0.4333, 34.9167, 80.0, "Mary Achieng", "+254700000101"),
            ("PARTNER-002", "Kendu Bay Farm Supplies", "Agro-dealer", "Rachuonyo North", -0.3812, 34.6341, 80.0, "Peter Ouma", "+254700000102"),
            ("PARTNER-003", "Rachuonyo Seed & Soil Hub", "Agro-dealer", "Rachuonyo North", -0.4000, 34.6500, 80.0, "Akinyi Odhiambo", "+254700000103"),
            ("PARTNER-004", "Homa Bay Farmers Cooperative Store", "Cooperative", "Homa Bay Central", -0.5273, 34.4571, 80.0, "Tom Otieno", "+254700000104"),
            ("PARTNER-005", "Mbita Agri-Inputs", "Agro-dealer", "Suba South", -0.4800, 34.2000, 100.0, "Mama Atieno Co-op Desk", "+254700000105"),
        ]
        for partner in partners:
            insert_json(db, "partners", {
                "partner_id": partner[0], "name": partner[1], "partner_type": partner[2],
                "ward": partner[3], "latitude": partner[4], "longitude": partner[5],
                "service_radius_km": partner[6], "verified": 1, "contact_name": partner[7],
                "contact_phone": partner[8],
            })
        inputs = [
            ("INP-HYDRO-001", "Root-zone hydrogel", "SOIL_AMENDMENT", list(CROPS), ["sandy", "loam", "low_moisture", "clay"], ["LM3", "LM4"], "25 kg bag", 300.0, "PARTNER-004"),
            ("INP-FERT-DAP", "DAP Fertilizer", "FERTILISER", list(CROPS), ["loam", "clay", "low_moisture", "sandy"], ["LM3", "LM4"], "50 kg bag", 3500.0, "PARTNER-001"),
            ("INP-FERT-UREA", "Urea Fertilizer", "FERTILISER", list(CROPS), ["loam", "sandy", "low_moisture", "clay"], ["LM3", "LM4"], "50 kg bag", 3200.0, "PARTNER-002"),
            ("INP-FERT-NPK", "Balanced NPK 17:17:17", "FERTILISER", list(CROPS), ["loam", "clay", "sandy"], ["LM3", "LM4"], "50 kg bag", 4200.0, "PARTNER-004"),
            ("INP-SEED-SORG", "Certified Sorghum Seeds", "SEED", ["Sorghum Gadam"], ["sandy", "loam", "low_moisture", "clay"], ["LM3", "LM4"], "2 kg bag", 800.0, "PARTNER-003"),
            ("INP-SEED-BEAN", "Certified Bean Seeds", "SEED", ["Beans Rosecoco"], ["loam", "clay", "sandy", "low_moisture"], ["LM3", "LM4"], "1 kg bag", 400.0, "PARTNER-005"),
            ("INP-SEED-MAIZE", "Certified drought-tolerant maize seed", "SEED", ["Maize WH-505"], ["sandy", "loam", "low_moisture", "clay"], ["LM3", "LM4"], "2 kg pack", 650.0, "PARTNER-003"),
            ("INP-FUNG-001", "Maize fungicide package", "CROP_PROTECTION", ["Maize WH-505"], ["waterlogged", "loam", "clay"], ["LM3", "LM4"], "farm pack", 1800.0, "PARTNER-002"),
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
    print(json.dumps({
        "status": "ok",
        "offline": offline_fallback,
        "farmers": FARMER_COUNT,
        "wards": len(WARDS),
    }))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline-fallback", action="store_true")
    args = parser.parse_args()
    ingest(args.offline_fallback)


if __name__ == "__main__":
    main()
