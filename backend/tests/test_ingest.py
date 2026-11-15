from backend.db import connect
from backend.ingest import ingest


def test_ingest_creates_synthetic_registry() -> None:
    ingest(offline_fallback=True)
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM farmers").fetchone()[0] == 24
        assert db.execute("SELECT COUNT(*) FROM plots").fetchone()[0] == 24
