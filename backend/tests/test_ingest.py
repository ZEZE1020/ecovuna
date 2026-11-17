from backend.db import connect
from backend.ingest import FARMER_COUNT, ingest


def test_ingest_creates_synthetic_registry() -> None:
    ingest(offline_fallback=True)
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM farmers").fetchone()[0] == FARMER_COUNT
        assert db.execute("SELECT COUNT(*) FROM plots").fetchone()[0] == FARMER_COUNT
        assert db.execute("SELECT COUNT(*) FROM partners WHERE verified = 1").fetchone()[0] == 5
