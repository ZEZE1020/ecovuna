from fastapi.testclient import TestClient

from backend.ingest import ingest
from backend.main import app


def setup_module() -> None:
    ingest(offline_fallback=True)


def test_ussd_callback() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/ussd",
        data={"phoneNumber": "+254712345678", "text": "SYNTH-HB-001"},
    )
    assert response.status_code == 200
    assert "CON Your subsidy status is: TIER_A_FULL" in response.text
