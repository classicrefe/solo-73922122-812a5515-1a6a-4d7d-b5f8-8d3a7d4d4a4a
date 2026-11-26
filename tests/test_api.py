"""API 层测试: 正常方案、冲突 409、录入校验 422。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

BASE_BODY = {
    "floor_language": "ja",
    "booths": [
        {"id": "A", "output_language": "en", "understands": ["ja"]},
        {"id": "B", "output_language": "fr", "understands": ["en"]},
        {"id": "C", "output_language": "de", "understands": ["ja", "en"]},
        {"id": "D", "output_language": "ko", "understands": ["fr"]},
    ],
    "existing": [{"booth": "A", "source": "ja"}, {"booth": "B", "source": "en"}],
    "locks": [],
}


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200 and resp.json()["status"] == "ok"


def test_plan_ok_shape():
    resp = client.post("/plan", json=BASE_BODY)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    by_booth = {a["booth"]: a for a in body["assignments"]}
    assert by_booth["A"]["source_kind"] == "floor" and by_booth["A"]["depth"] == 1
    assert by_booth["B"]["source_kind"] == "booth" and by_booth["B"]["source_booth"] == "A"
    assert by_booth["D"]["source_kind"] == "none"
    assert body["unsupplied_languages"] == ["ko"]
    assert body["removed_connections"] == []
    assert body["summary"]["kept"] == 2


def test_plan_with_locks():
    body = dict(BASE_BODY, locks=[{"booth": "C", "source": "en"}])
    resp = client.post("/plan", json=body)
    assert resp.status_code == 200
    by_booth = {a["booth"]: a for a in resp.json()["assignments"]}
    assert by_booth["C"]["source_language"] == "en" and by_booth["C"]["depth"] == 2


def test_plan_conflict_returns_409_only_conflicts():
    body = dict(BASE_BODY, locks=[{"booth": "D", "source": "fr"}])
    resp = client.post("/plan", json=body)
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["status"] == "conflict"
    assert detail["conflicts"][0]["code"] == "source_booth_not_relayable"
    assert "assignments" not in detail  # 只报冲突, 不出方案


def test_duplicate_output_language_422():
    body = dict(BASE_BODY)
    body["booths"] = [
        {"id": "A", "output_language": "en", "understands": ["ja"]},
        {"id": "B", "output_language": "en", "understands": ["ja"]},
    ]
    assert client.post("/plan", json=body).status_code == 422


def test_more_than_16_booths_422():
    body = dict(BASE_BODY)
    body["booths"] = [
        {"id": f"B{i}", "output_language": f"L{i}", "understands": ["ja"]} for i in range(17)
    ]
    assert client.post("/plan", json=body).status_code == 422


def test_unknown_booth_in_locks_422():
    body = dict(BASE_BODY, locks=[{"booth": "ZZ", "source": "ja"}])
    assert client.post("/plan", json=body).status_code == 422


def test_output_equals_floor_422():
    body = dict(BASE_BODY)
    body["booths"] = [{"id": "A", "output_language": "ja", "understands": ["en"]}]
    assert client.post("/plan", json=body).status_code == 422


def test_duplicate_connection_for_same_booth_422():
    body = dict(BASE_BODY)
    body["existing"] = [{"booth": "A", "source": "ja"}, {"booth": "A", "source": "en"}]
    assert client.post("/plan", json=body).status_code == 422
