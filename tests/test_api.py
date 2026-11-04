"""Exercise real HTTP routes, persistence, privacy, and expiry with an injected clock."""

from datetime import datetime, timedelta, timezone
import json

from fastapi.testclient import TestClient
import pytest

from wifi_location.api import create_app


TOKEN = "test-only-management-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def api(tmp_path):
    current = [datetime(2026, 11, 4, 9, tzinfo=timezone.utc)]
    app = create_app(str(tmp_path / "test.sqlite3"), admin_token=TOKEN, clock=lambda: current[0])
    with TestClient(app) as client:
        yield client, app, current


def add_teacher(client, **changes):
    payload = {"name": "実験 太郎", "subject": "情報", "device_id": "SENSITIVE-DEVICE-ID"}
    response = client.post("/api/admin/teachers", json={**payload, **changes}, headers=AUTH)
    assert response.status_code == 201
    return response.json()["id"]


def measure(client, identifier, **changes):
    return client.post("/api/admin/observations", headers=AUTH, json={
        "teacher_id": identifier,
        "readings": {"AP_A": -40, "AP_B": -80, "AP_C": -70, "AP_D": -90},
        "connected_ap": "AP_A", **changes,
    })


def public_teacher(client, identifier):
    return next(row for row in client.get("/api/teachers").json()["teachers"] if row["id"] == identifier)


def test_public_search_and_private_status(api):
    client, _, _ = api
    all_rows = client.get("/api/teachers").json()["teachers"]
    assert len(all_rows) == 6
    query = client.get("/api/teachers", params={"q": "青木", "subject": "国語"})
    assert len(query.json()["teachers"]) == 1
    assert client.get("/api/teachers", params={"q": "青木", "subject": "数学"}).json()["teachers"] == []
    private = next(row for row in all_rows if row["status"] == "private")
    assert private["area"] is None
    assert private["updated_at"] is None
    assert private["reason"] is None
    assert any(row["status"] == "unknown" for row in all_rows)
    assert client.get("/api/health").json()["network_collectors_enabled"] is False


def test_student_payload_never_contains_internal_identifiers(api):
    client, _, _ = api
    identifier = add_teacher(client)
    assert measure(client, identifier, readings={"SENSITIVE-AP-ID": -45}).status_code == 200
    allowed = {"id", "name", "subject", "status", "area", "updated_at", "reason"}
    for row in client.get("/api/teachers").json()["teachers"]:
        assert set(row).issubset(allowed)
    serialized = json.dumps(client.get("/api/teachers").json()) + json.dumps(client.get("/api/areas").json())
    for secret in ["SENSITIVE-DEVICE-ID", "SENSITIVE-AP-ID", "device_id", "readings", "connected_ap", "session_id", TOKEN]:
        assert secret not in serialized
    assert public_teacher(client, identifier)["reason"] == "unmapped_ap"


@pytest.mark.parametrize("method,path,payload", [
    ("get", "/api/admin/teachers", None),
    ("get", "/api/admin/ap-areas", None),
    ("post", "/api/admin/teachers", {"name": "仮名", "subject": "情報", "device_id": "pc"}),
    ("put", "/api/admin/config", {"algorithm": "knn"}),
    ("put", "/api/admin/ap-areas", {"ap_areas": {"a": "1F-west"}}),
    ("patch", "/api/admin/teachers/demo-1", {"private": True}),
    ("post", "/api/admin/observations", {"teacher_id": "demo-1", "readings": {}}),
    ("post", "/api/admin/demo-refresh", None),
])
def test_management_routes_require_token(api, method, path, payload):
    client, _, _ = api
    kwargs = {} if payload is None else {"json": payload}
    assert client.request(method.upper(), path, **kwargs).status_code == 401
    assert client.request(method.upper(), path, headers={"Authorization": "Bearer wrong-token"}, **kwargs).status_code == 401


def test_real_engine_integration_and_stale_ttl(api):
    client, _, current = api
    identifier = add_teacher(client)
    assert client.put("/api/admin/config", json={"algorithm": "connected_ap"}, headers=AUTH).status_code == 200
    result = measure(client, identifier)
    assert result.status_code == 200
    assert result.json()["estimate"]["area"] == "1F-west"
    assert public_teacher(client, identifier)["area"] == "1階 西側"
    current[0] += timedelta(seconds=181)
    expired = public_teacher(client, identifier)
    assert expired["status"] == "unknown"
    assert expired["area"] is None
    assert expired["reason"] == "stale"


def test_latest_only_and_old_future_requests_rejected(api):
    client, app, current = api
    identifier = add_teacher(client)
    original_count = app.state.store.rows("SELECT COUNT(*) AS n FROM latest")[0]["n"]
    assert measure(client, identifier).status_code == 200
    for _ in range(3):
        current[0] += timedelta(seconds=1)
        assert measure(client, identifier).status_code == 200
    assert app.state.store.rows("SELECT COUNT(*) AS n FROM latest")[0]["n"] == original_count+1
    assert measure(client, identifier, timestamp=(current[0]-timedelta(seconds=1)).isoformat()).status_code == 409
    assert measure(client, identifier, timestamp=(current[0]+timedelta(seconds=6)).isoformat()).status_code == 422
    assert measure(client, identifier, timestamp="2026-11-04T09:00:00").status_code == 422
    assert measure(client, "does-not-exist").status_code == 404


def test_private_erases_current_measurement_and_blocks_collection(api):
    client, app, _ = api
    identifier = add_teacher(client)
    assert measure(client, identifier).status_code == 200
    response = client.patch(f"/api/admin/teachers/{identifier}", json={"private": True}, headers=AUTH)
    assert response.status_code == 200
    assert app.state.store.rows("SELECT * FROM latest WHERE teacher_id=?", (identifier,)) == []
    row = public_teacher(client, identifier)
    assert row["status"] == "private"
    assert row["area"] is None and row["updated_at"] is None and row["reason"] is None
    assert measure(client, identifier).status_code == 409
    assert client.post("/api/admin/demo-refresh", headers=AUTH).status_code == 200
    assert app.state.store.rows("SELECT * FROM latest WHERE teacher_id=?", (identifier,)) == []
    assert client.patch(f"/api/admin/teachers/{identifier}", json={"private": False}, headers=AUTH).status_code == 200
    assert public_teacher(client, identifier)["reason"] == "no_data"


@pytest.mark.parametrize("readings", [{"a": "NaN"}, {"a": "Infinity"}, {"a": 1}, {"a": -121}, {" ": -50}])
def test_invalid_measurements_are_validation_errors(api, readings):
    client, _, _ = api
    assert measure(client, "demo-1", readings=readings).status_code == 422


def test_nonfinite_json_token_rejected_without_server_error(api):
    client, _, _ = api
    response = client.post("/api/admin/observations", headers={**AUTH, "Content-Type": "application/json"},
                           content='{"teacher_id":"demo-1","readings":{"AP_A":NaN}}')
    assert response.status_code in {400, 422}


def test_profile_and_configuration_validation(api):
    client, _, _ = api
    assert client.post("/api/admin/teachers", json={"name": "  ", "subject": "情報", "device_id": "pc"}, headers=AUTH).status_code == 422
    add_teacher(client)
    assert client.post("/api/admin/teachers", json={"name": "別名", "subject": "情報", "device_id": "SENSITIVE-DEVICE-ID"}, headers=AUTH).status_code == 409
    assert client.put("/api/admin/config", json={"algorithm": "not-real"}, headers=AUTH).status_code == 422
    assert client.put("/api/admin/ap-areas", json={"ap_areas": {"a": "unknown-place"}}, headers=AUTH).status_code == 422


def test_mapping_and_config_persist_restart(tmp_path):
    database = str(tmp_path / "persistent.sqlite3")
    now = lambda: datetime(2026, 11, 4, tzinfo=timezone.utc)
    first = create_app(database, admin_token=TOKEN, clock=now)
    mapping = {"AP_A": "3F-east"}
    with TestClient(first) as client:
        identifier = add_teacher(client)
        assert client.put("/api/admin/ap-areas", json={"ap_areas": mapping}, headers=AUTH).status_code == 200
        assert client.put("/api/admin/config", json={"algorithm": "connected_ap"}, headers=AUTH).status_code == 200
        assert measure(client, identifier).status_code == 200
    second = create_app(database, admin_token=TOKEN, clock=now)
    with TestClient(second) as client:
        assert client.get("/api/admin/ap-areas", headers=AUTH).json()["ap_areas"] == mapping
        assert client.get("/api/config").json()["algorithm"] == "connected_ap"
        assert public_teacher(client, identifier)["area"] == "3階 東側"
