import io
from datetime import date, datetime, timezone

from fastapi.testclient import TestClient


def test_health(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_driver_csv_upload_and_event_and_stats(client: TestClient):
    csv_body = "driver_id,name,phone,email,region\n7,Ada Lovelace,+15555550100,ada@example.com,north\n"
    r = client.post("/drivers/upload", files={"file": ("drivers.csv", io.BytesIO(csv_body.encode()), "text/csv")})
    assert r.status_code == 200
    body = r.json()
    assert body["created"] == 1
    assert body["updated"] == 0

    ts = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
    ev = {
        "package_id": "PKG-1",
        "driver_id": 7,
        "status": "delivered",
        "timestamp": ts.isoformat(),
    }
    r2 = client.post("/deliveries/events", json=ev)
    assert r2.status_code == 201

    start = date(2026, 5, 1)
    end = date(2026, 5, 31)
    r3 = client.get(
        "/statistics",
        params={
            "metric": "total_packages",
            "driver_ids": 7,
            "regions": "north",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        },
    )
    assert r3.status_code == 200
    assert r3.json()["value"] == 1.0

    r4 = client.get(
        "/statistics",
        params={
            "metric": "delivery_rate",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        },
    )
    assert r4.status_code == 200
    assert abs(r4.json()["value"] - 1.0) < 1e-6


def test_statistics_default_today_empty(client: TestClient):
    r = client.get("/statistics", params={"metric": "total_packages"})
    assert r.status_code == 200
    assert r.json()["value"] == 0.0


def test_date_range_validation(client: TestClient):
    start = date(2026, 1, 1)
    end = date(2026, 3, 1)
    r = client.get(
        "/statistics",
        params={"metric": "total_packages", "start_date": start.isoformat(), "end_date": end.isoformat()},
    )
    assert r.status_code == 400


def test_event_unknown_driver(client: TestClient):
    r = client.post(
        "/deliveries/events",
        json={"package_id": "x", "driver_id": 99, "status": "picked_up"},
    )
    assert r.status_code == 400
