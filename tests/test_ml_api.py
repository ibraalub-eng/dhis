from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_ml_api_no_month():
    resp = client.get("/analysis/ml")
    assert resp.status_code == 422


def test_ml_api_no_data():
    resp = client.get("/analysis/ml?month=2099-12")
    assert resp.status_code == 200
    assert resp.json() == {}
