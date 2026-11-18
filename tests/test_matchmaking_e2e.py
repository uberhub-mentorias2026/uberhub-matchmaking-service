import os
import sys
from pathlib import Path
from uuid import uuid4
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app
from app.origin_client import ResilientOriginClient

client = TestClient(app)


def _sample_payload() -> dict:
    return {
        "mentee_need_text": "Preciso evoluir na arquitetura de microsserviços com Java e Spring Boot.",
        "tags": ["java", "microsservicos", "arquitetura"],
        "filters": {
            "language": "pt-BR",
            "format": "online",
            "availability_slots": ["SEG_NOITE"],
            "min_experience_years": 5,
        },
        "limit": 3,
        "include_explanation": True,
    }


def test_idempotency_and_validated_match_flow() -> None:
    ResilientOriginClient.reset_circuit()
    os.environ["SIMULATE_ORIGIN_FAILURE"] = "false"
    idem_key = f"test-idem-{uuid4()}"

    r1 = client.post(
        "/match-requests",
        json=_sample_payload(),
        headers={"Idempotency-Key": idem_key},
    )
    assert r1.status_code == 202
    req_id = r1.json()["match_request_id"]

    # Reenvio com mesma Idempotency-Key deve retornar exatamente o mesmo UUID
    r2 = client.post(
        "/match-requests",
        json=_sample_payload(),
        headers={"Idempotency-Key": idem_key},
    )
    assert r2.status_code == 202
    assert r2.json()["match_request_id"] == req_id

    res = client.get(f"/match-requests/{req_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "completed"
    assert body["revalidation_status"] == "validated"
    assert len(body["candidates"]) >= 1
    assert body["candidates"][0]["mentor_id"] == "m_001"
    assert body["candidates"][0]["explanation"] is not None

    # Submete feedback positivo para a mentora recomendada
    fb = client.post(
        f"/match-requests/{req_id}/feedback",
        json={"mentor_id": "m_001", "decision": "accepted", "reason": "Excelente fit técnico"},
    )
    assert fb.status_code == 201
    assert fb.json()["decision"] == "accepted"


def test_origin_failure_graceful_fallback() -> None:
    ResilientOriginClient.reset_circuit()
    os.environ["SIMULATE_ORIGIN_FAILURE"] = "true"
    try:
        r = client.post("/match-requests", json=_sample_payload())
        assert r.status_code == 202
        req_id = r.json()["match_request_id"]

        res = client.get(f"/match-requests/{req_id}")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "completed"
        assert body["revalidation_status"] == "unrevalidated"
        assert len(body["candidates"]) >= 1
    finally:
        os.environ["SIMULATE_ORIGIN_FAILURE"] = "false"
        ResilientOriginClient.reset_circuit()


if __name__ == "__main__":
    test_idempotency_and_validated_match_flow()
    print("[OK] test_idempotency_and_validated_match_flow")
    test_origin_failure_graceful_fallback()
    print("[OK] test_origin_failure_graceful_fallback")