import sys
import os

# Add current folder to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from main import app
from app.config import settings

client = TestClient(app)

def test_milestone_1():
    res = client.get("/health")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    assert res.json() == {"status": "ok"}
    print("PASS: /health returned status: ok")

    docs_res = client.get("/openapi.json")
    assert docs_res.status_code == 200, f"Expected 200 for openapi.json, got {docs_res.status_code}"
    print("PASS: OpenAPI schema generated successfully (for /docs)")

def test_milestone_2():
    # 1. Without token -> 401
    payload = {
        "projectId": "prj_test_123",
        "brief": "Test brief",
        "templates": []
    }
    res_no_auth = client.post("/internal/day-one/suggestions", json=payload)
    assert res_no_auth.status_code == 401, f"Expected 401 without token, got {res_no_auth.status_code}"
    print("PASS: Request without token returned 401 Unauthorized")

    # 2. With wrong token -> 401
    res_wrong_auth = client.post(
        "/internal/day-one/suggestions",
        json=payload,
        headers={"X-Service-Token": "wrong-token"}
    )
    assert res_wrong_auth.status_code == 401, f"Expected 401 with wrong token, got {res_wrong_auth.status_code}"
    print("PASS: Request with wrong token returned 401 Unauthorized")

    # 3. With correct token -> 200
    res_with_auth = client.post(
        "/internal/day-one/suggestions",
        json=payload,
        headers={"X-Service-Token": settings.INTERNAL_SERVICE_TOKEN}
    )
    assert res_with_auth.status_code == 200, f"Expected 200 with correct token, got {res_with_auth.status_code}"
    assert "briefTooThin" in res_with_auth.json()
    print("PASS: Request with valid token returned 200 OK")

if __name__ == "__main__":
    test_milestone_1()
    test_milestone_2()
    print("\nALL TESTS FOR MILESTONE 1 & 2 PASSED!")
