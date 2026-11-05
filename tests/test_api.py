"""Exercise real HTTP routes, persistence, privacy, and expiry with an injected clock."""

import asyncio
from datetime import datetime, timedelta, timezone
import json
import time

from fastapi.testclient import TestClient
import pytest

import wifi_location.api as api_module
from wifi_location.api import create_app


TOKEN = "test-only-management-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
BASE = "http://127.0.0.1:8000"


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    # Settings from the developer's shell must not change test results.
    for name in ("WIFI_ADMIN_TOKEN", "WIFI_ALLOWED_HOSTS", "WIFI_RETENTION_SECONDS", "WIFI_DB_PATH"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def api(tmp_path):
    current = [datetime(2026, 11, 4, 9, tzinfo=timezone.utc)]
    app = create_app(str(tmp_path / "test.sqlite3"), admin_token=TOKEN, clock=lambda: current[0])
    with TestClient(app, base_url=BASE) as client:
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
    allowed = {"id", "name", "kana", "subject", "status", "area", "updated_at", "reason"}
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
    ("delete", "/api/admin/teachers/demo-1", None),
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
    with TestClient(first, base_url=BASE) as client:
        identifier = add_teacher(client)
        assert client.put("/api/admin/ap-areas", json={"ap_areas": mapping}, headers=AUTH).status_code == 200
        assert client.put("/api/admin/config", json={"algorithm": "connected_ap"}, headers=AUTH).status_code == 200
        assert measure(client, identifier).status_code == 200
    second = create_app(database, admin_token=TOKEN, clock=now)
    with TestClient(second, base_url=BASE) as client:
        assert client.get("/api/admin/ap-areas", headers=AUTH).json()["ap_areas"] == mapping
        assert client.get("/api/config").json()["algorithm"] == "connected_ap"
        assert public_teacher(client, identifier)["area"] == "3階 東側"


def test_untrusted_host_header_is_rejected(api):
    # A DNS-rebinding page reaches the loopback server under its own host name.
    client, _, _ = api
    assert client.get("/api/admin/teachers", headers={**AUTH, "Host": "attacker.example"}).status_code == 400
    assert client.get("/api/teachers", headers={"Host": "localhost:8000"}).status_code == 200
    assert client.get("/api/teachers", headers={"Host": "[::1]:8000"}).status_code == 200


def test_unset_token_is_random_per_launch(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("WIFI_ADMIN_TOKEN", raising=False)
    app = create_app(str(tmp_path / "generated.sqlite3"))
    with TestClient(app, base_url=BASE) as client:
        printed = capsys.readouterr().err
        generated = printed.rsplit(": ", 1)[-1].strip()
        assert len(generated) >= 20
        assert client.get("/api/admin/teachers", headers={"Authorization": "Bearer dev-demo-token"}).status_code == 401
        assert client.get("/api/admin/teachers", headers={"Authorization": f"Bearer {generated}"}).status_code == 200


def test_security_headers_and_no_store(api):
    client, _, _ = api
    response = client.get("/api/teachers")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/").headers["cache-control"] == "no-cache"
    assert "content-security-policy" not in client.get("/docs").headers


def test_oversized_bodies_are_rejected(api):
    client, _, _ = api
    padded = {"name": "仮名", "subject": "情報", "device_id": "x" * 40_000}
    assert client.post("/api/admin/teachers", json=padded, headers=AUTH).status_code == 413
    chunks = (b'{"name":"' + b"a" * 10_000 for _ in range(5))
    response = client.post("/api/admin/teachers", content=chunks,
                           headers={**AUTH, "Content-Type": "application/json"})
    assert response.status_code == 413


@pytest.mark.parametrize("name", ["仮名‮", "仮\u0000名", "仮\n名", "仮​名", "仮 名"])
def test_hidden_characters_in_names_are_rejected(api, name):
    client, _, _ = api
    response = client.post("/api/admin/teachers", json={"name": name, "subject": "情報", "device_id": "pc-x"}, headers=AUTH)
    assert response.status_code == 422


def test_unknown_fields_and_blank_connected_ap(api):
    client, _, _ = api
    identifier = add_teacher(client)
    assert client.post("/api/admin/teachers", json={"name": "仮名", "subject": "情報", "device_id": "pc-y", "role": "admin"},
                       headers=AUTH).status_code == 422
    assert client.put("/api/admin/config", json={"algorithm": "connected_ap"}, headers=AUTH).status_code == 200
    result = measure(client, identifier, connected_ap="   ")
    assert result.status_code == 200
    assert result.json()["reason"] == "unmapped_ap"
    message = measure(client, identifier, readings={"AP_A": 5}).json()["detail"]
    assert message.startswith("RSSIは") and "Value error" not in message


def test_kana_search_and_gojuon_order(api):
    client, _, _ = api
    names = [row["name"] for row in client.get("/api/teachers").json()["teachers"]]
    assert names == ["青木 はるか", "小林 ひなた", "佐藤 けん", "鈴木 りく", "高橋 みどり", "田中 あおい"]
    assert [row["name"] for row in client.get("/api/teachers", params={"q": "タカハシ"}).json()["teachers"]] == ["高橋 みどり"]
    assert [row["name"] for row in client.get("/api/teachers", params={"q": "すずき せんせい"}).json()["teachers"]] == ["鈴木 りく"]
    created = client.post("/api/admin/teachers", headers=AUTH,
                          json={"name": "星野 あかり", "kana": "ﾎｼﾉ　アカリ", "subject": "情報", "device_id": "pc-k"})
    assert created.status_code == 201 and created.json()["kana"] == "ホシノ アカリ"
    assert client.post("/api/admin/teachers", headers=AUTH,
                       json={"name": "仮名", "kana": "kamei", "subject": "情報", "device_id": "pc-z"}).status_code == 422
    assert client.get("/api/teachers", params={"q": "x" * 101}).status_code == 422


def test_old_database_gains_kana_column(tmp_path):
    import sqlite3
    database = tmp_path / "old.sqlite3"
    legacy = sqlite3.connect(database)
    legacy.executescript("""
        CREATE TABLE teachers (id TEXT PRIMARY KEY, name TEXT NOT NULL, subject TEXT NOT NULL,
                               device_id TEXT NOT NULL UNIQUE, private INTEGER NOT NULL DEFAULT 0);
        INSERT INTO teachers VALUES ('demo-1', '青木 はるか', '国語', 'demo-pc-1', 0);
        INSERT INTO teachers VALUES ('demo-2', '名前を変えた先生', '数学', 'demo-pc-2', 0);
        INSERT INTO teachers VALUES ('custom', '星野 あかり', '情報', 'pc-7', 0);
    """)
    legacy.commit()
    legacy.close()
    app = create_app(str(database), admin_token=TOKEN, clock=lambda: datetime(2026, 11, 4, tzinfo=timezone.utc))
    with TestClient(app, base_url=BASE) as client:
        rows = {row["id"]: row for row in client.get("/api/teachers").json()["teachers"]}
        assert rows["demo-1"]["kana"] == "あおき はるか"
        assert rows["demo-2"]["kana"] == ""  # a renamed demo row keeps no stale reading
        assert rows["custom"]["kana"] == ""


def test_delete_teacher_removes_current_measurement(api):
    client, app, _ = api
    identifier = add_teacher(client)
    assert measure(client, identifier).status_code == 200
    assert client.delete(f"/api/admin/teachers/{identifier}", headers=AUTH).status_code == 204
    assert app.state.store.rows("SELECT * FROM latest WHERE teacher_id=?", (identifier,)) == []
    assert all(row["id"] != identifier for row in client.get("/api/teachers").json()["teachers"])
    assert client.delete(f"/api/admin/teachers/{identifier}", headers=AUTH).status_code == 404


def test_retention_deletes_measurements_after_the_period(tmp_path):
    current = [datetime(2026, 11, 4, 9, tzinfo=timezone.utc)]
    app = create_app(str(tmp_path / "retention.sqlite3"), admin_token=TOKEN, clock=lambda: current[0],
                     retention_seconds=600)
    with TestClient(app, base_url=BASE) as client:
        identifier = add_teacher(client)
        assert measure(client, identifier).status_code == 200
        current[0] += timedelta(seconds=300)
        assert public_teacher(client, identifier)["reason"] == "stale"
        assert app.state.store.rows("SELECT * FROM latest WHERE teacher_id=?", (identifier,)) != []
        current[0] += timedelta(seconds=301)
        assert public_teacher(client, identifier)["reason"] == "no_data"
        assert app.state.store.rows("SELECT * FROM latest WHERE teacher_id=?", (identifier,)) == []
    with pytest.raises(ValueError):
        create_app(str(tmp_path / "bad.sqlite3"), admin_token=TOKEN, retention_seconds=0)


def test_research_dataset_switch(api):
    client, _, _ = api
    simulation = client.get("/api/research").json()
    assert simulation["dataset"] == "simulation" and simulation["source"] == "simulation"
    assert simulation["series"] and simulation["candidates"]
    ids = [dataset["id"] for dataset in simulation["datasets"]]
    assert ids[0] == "simulation"
    if "uji" in ids:
        uji = client.get("/api/research", params={"dataset": "uji"}).json()
        assert uji["source"] == "ujindoorloc" and uji["series"] == [] and uji["metrics"]
        assert uji["license"] == "CC BY 4.0"
    assert client.get("/api/research", params={"dataset": "../secret"}).status_code == 422


def test_engine_cache_follows_algorithm_and_mapping_changes(api):
    client, _, _ = api
    identifier = add_teacher(client)
    assert measure(client, identifier, readings={"AP_A": -40}).status_code == 200  # builds the k-NN engine
    assert public_teacher(client, identifier)["reason"] == "insufficient_data"
    assert client.put("/api/admin/config", json={"algorithm": "connected_ap"}, headers=AUTH).status_code == 200
    assert public_teacher(client, identifier)["area"] == "1階 西側"
    assert client.put("/api/admin/ap-areas", json={"ap_areas": {"AP_A": "3F-east"}}, headers=AUTH).status_code == 200
    assert public_teacher(client, identifier)["area"] == "3階 東側"


def test_blank_connected_ap_is_stored_as_unknown(api):
    client, app, _ = api
    identifier = add_teacher(client)
    assert measure(client, identifier, connected_ap="   ").status_code == 200
    stored = app.state.store.rows("SELECT observation FROM latest WHERE teacher_id=?", (identifier,))[0]
    assert json.loads(stored["observation"])["connected_ap"] is None


@pytest.mark.parametrize("ap", ["AP\u202eA", "AP\u200bA", "AP\nA"])
def test_hidden_characters_in_ap_identifiers_are_rejected(api, ap):
    client, _, _ = api
    assert measure(client, "demo-1", readings={ap: -50}).status_code == 422
    assert measure(client, "demo-1", connected_ap=ap).status_code == 422
    assert client.put("/api/admin/ap-areas", json={"ap_areas": {ap: "1F-west"}}, headers=AUTH).status_code == 422


@pytest.mark.parametrize("method,path,payload", [
    ("patch", "/api/admin/teachers/demo-1", {"private": True, "extra": 1}),
    ("put", "/api/admin/config", {"algorithm": "knn", "extra": 1}),
    ("put", "/api/admin/ap-areas", {"ap_areas": {"AP_A": "1F-west"}, "extra": 1}),
    ("post", "/api/admin/observations", {"teacher_id": "demo-1", "readings": {"AP_A": -50}, "source": "real"}),
])
def test_unknown_fields_are_rejected_on_every_input(api, method, path, payload):
    client, _, _ = api
    response = client.request(method.upper(), path, json=payload, headers=AUTH)
    assert response.status_code == 422
    assert response.json()["detail"] == "使用できない項目が含まれています"


@pytest.mark.parametrize("method,path,params", [
    ("get", "/api/teachers", {"subject": "x" * 31}),
    ("patch", "/api/admin/teachers/" + "x" * 81, None),
    ("delete", "/api/admin/teachers/" + "x" * 81, None),
])
def test_query_and_path_lengths_are_limited(api, method, path, params):
    client, _, _ = api
    kwargs = {"params": params} if params else {}
    if method == "patch":
        kwargs["json"] = {"private": True}
    assert client.request(method.upper(), path, headers=AUTH, **kwargs).status_code == 422


@pytest.mark.parametrize("payload,message", [
    ({"name": "あ" * 61, "subject": "情報", "device_id": "pc-1"}, "名前は60文字以内で入力してください"),
    ({"name": "仮名", "device_id": "pc-1"}, "教科を入力してください"),
    ({"name": "仮名", "subject": "情報", "device_id": "pc-1", "kana": "\u3316" * 11}, "よみがなは60文字以内で入力してください"),
])
def test_validation_messages_are_japanese(api, payload, message):
    client, _, _ = api
    response = client.post("/api/admin/teachers", json=payload, headers=AUTH)
    assert response.status_code == 422 and response.json()["detail"] == message
    broken = client.post("/api/admin/teachers", content=b"{", headers={**AUTH, "Content-Type": "application/json"})
    assert broken.json()["detail"] == "送信データの形式が正しくありません"


def test_foreign_names_in_katakana_are_accepted(api):
    client, _, _ = api
    response = client.post("/api/admin/teachers", headers=AUTH,
                           json={"name": "ジャン=ポール", "kana": "ジャン＝ポール", "subject": "フランス語", "device_id": "pc-f"})
    assert response.status_code == 201 and response.json()["kana"] == "ジャン=ポール"


def test_allowed_hosts_come_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("WIFI_ALLOWED_HOSTS", " Lab.test:8000 , ::1 ")
    with TestClient(create_app(str(tmp_path / "hosts.sqlite3"), admin_token=TOKEN), base_url=BASE) as client:
        assert client.get("/api/health", headers={"Host": "lab.test:8000"}).status_code == 200
        assert client.get("/api/health", headers={"Host": "[::1]:8000"}).status_code == 200
        assert client.get("/api/health", headers={"Host": "localhost:8000"}).status_code == 400


@pytest.mark.parametrize("token", ["ひみつのトークン1234567890", "has space in token 123", "tab\ttoken-1234567890"])
def test_tokens_that_cannot_travel_in_a_header_are_refused(tmp_path, token):
    with pytest.raises(ValueError, match="半角"):
        create_app(str(tmp_path / "token.sqlite3"), admin_token=token)


def test_default_retention_is_one_hour(tmp_path):
    current = [datetime(2026, 11, 4, 9, tzinfo=timezone.utc)]
    with TestClient(create_app(str(tmp_path / "default.sqlite3"), admin_token=TOKEN, clock=lambda: current[0]),
                    base_url=BASE) as client:
        identifier = add_teacher(client)
        assert measure(client, identifier).status_code == 200
        current[0] += timedelta(seconds=3599)
        assert public_teacher(client, identifier)["reason"] == "stale"
        current[0] += timedelta(seconds=2)
        assert public_teacher(client, identifier)["reason"] == "no_data"


def test_retention_from_environment_is_applied_at_startup(tmp_path, monkeypatch):
    database = str(tmp_path / "startup.sqlite3")
    start = datetime(2026, 11, 4, 9, tzinfo=timezone.utc)
    with TestClient(create_app(database, admin_token=TOKEN, clock=lambda: start), base_url=BASE) as client:
        identifier = add_teacher(client)
        assert measure(client, identifier).status_code == 200
    monkeypatch.setenv("WIFI_RETENTION_SECONDS", "600")
    later = create_app(database, admin_token=TOKEN, clock=lambda: start + timedelta(seconds=601))
    with TestClient(later, base_url=BASE):
        # No request yet: the startup purge alone must have removed the expired row.
        assert later.state.store.rows("SELECT * FROM latest") == []
    for value in ("0", "1e20", "nan", "一時間"):
        monkeypatch.setenv("WIFI_RETENTION_SECONDS", value)
        with pytest.raises(ValueError):
            create_app(database, admin_token=TOKEN)


def test_measurements_older_than_retention_are_not_stored(api):
    client, app, current = api
    identifier = add_teacher(client)
    response = measure(client, identifier, timestamp=(current[0] - timedelta(hours=2)).isoformat())
    assert response.status_code == 422 and response.json()["detail"] == "保持期間より古い測定は保存できません"
    assert app.state.store.rows("SELECT * FROM latest WHERE teacher_id=?", (identifier,)) == []


def test_expired_rows_are_purged_without_any_request(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "PURGE_INTERVAL_SECONDS", 0.05)
    current = [datetime(2026, 11, 4, 9, tzinfo=timezone.utc)]
    app = create_app(str(tmp_path / "background.sqlite3"), admin_token=TOKEN, clock=lambda: current[0],
                     retention_seconds=600)
    with TestClient(app, base_url=BASE) as client:
        identifier = add_teacher(client)
        assert measure(client, identifier).status_code == 200
        current[0] += timedelta(seconds=601)
        deadline = time.monotonic() + 3
        while app.state.store.rows("SELECT * FROM latest WHERE teacher_id=?", (identifier,)) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert app.state.store.rows("SELECT * FROM latest WHERE teacher_id=?", (identifier,)) == []


def test_hashed_assets_are_immutable_and_page_has_csp(tmp_path, monkeypatch):
    dist = tmp_path / "frontend/dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>t</title>")
    (dist / "assets/index-abc123.js").write_text("export {}")
    monkeypatch.setattr(api_module, "ROOT", tmp_path)
    with TestClient(create_app(str(tmp_path / "assets.sqlite3"), admin_token=TOKEN), base_url=BASE) as client:
        asset = client.get("/assets/index-abc123.js")
        assert asset.status_code == 200
        assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
        missing = client.get("/assets/missing-000.js")
        assert missing.status_code == 404 and missing.headers["cache-control"] == "no-cache"
        page = client.get("/")
        assert page.status_code == 200 and page.headers["cache-control"] == "no-cache"
        assert "script-src 'self'" in page.headers["content-security-policy"]
        assert page.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"


def test_large_body_sent_to_a_streaming_file_does_not_crash(tmp_path, monkeypatch):
    # A body that keeps arriving after the file response started must not raise inside the app.
    dist = tmp_path / "frontend/dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>t</title>")
    (dist / "assets/big-000.js").write_text("x" * 300_000)
    monkeypatch.setattr(api_module, "ROOT", tmp_path)
    app = create_app(str(tmp_path / "stream.sqlite3"), admin_token=TOKEN)

    async def run():
        pending = [b"x" * 16384] * 3
        sent = []

        async def receive():
            await asyncio.sleep(0.02)
            if pending:
                body = pending.pop(0)
                return {"type": "http.request", "body": body, "more_body": bool(pending)}
            await asyncio.sleep(3600)

        async def send(message):
            await asyncio.sleep(0.01)
            sent.append(message)

        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1",
                 "method": "GET", "scheme": "http", "path": "/assets/big-000.js", "raw_path": b"/assets/big-000.js",
                 "query_string": b"", "root_path": "", "client": ("127.0.0.1", 5555), "server": ("127.0.0.1", 8000),
                 "headers": [(b"host", b"127.0.0.1:8000"), (b"transfer-encoding", b"chunked")], "state": {}}
        await asyncio.wait_for(app(scope, receive, send), 10)
        return next(m["status"] for m in sent if m["type"] == "http.response.start")

    with TestClient(app, base_url=BASE):
        assert asyncio.run(run()) == 200


def test_teachers_without_reading_follow_and_katakana_sorts_as_hiragana(api):
    client, _, _ = api
    add_teacher(client, name="いとう れい", device_id="pc-no-kana")
    add_teacher(client, name="安藤 ゆう", kana="アンドウ ユウ", device_id="pc-katakana")
    names = [row["name"] for row in client.get("/api/teachers").json()["teachers"]]
    assert names == ["青木 はるか", "安藤 ゆう", "小林 ひなた", "佐藤 けん", "鈴木 りく", "高橋 みどり", "田中 あおい", "いとう れい"]


def test_unset_token_differs_between_launches(tmp_path, capsys):
    tokens = []
    for name in ("first", "second"):
        with TestClient(create_app(str(tmp_path / f"{name}.sqlite3")), base_url=BASE):
            tokens.append(capsys.readouterr().err.rsplit(": ", 1)[-1].strip())
    assert len(tokens[0]) >= 20 and tokens[0] != tokens[1]


def test_short_configured_token_prints_a_warning(tmp_path, capsys):
    with TestClient(create_app(str(tmp_path / "short.sqlite3"), admin_token="short"), base_url=BASE):
        assert "16文字以上" in capsys.readouterr().err


def test_body_limit_boundary_is_32_kib(api):
    client, _, _ = api
    headers = {**AUTH, "Content-Type": "application/json"}
    body = json.dumps({"private": False}).encode()
    exact = body + b" " * (32 * 1024 - len(body))
    assert client.patch("/api/admin/teachers/demo-1", content=exact, headers=headers).status_code == 200
    assert client.patch("/api/admin/teachers/demo-1", content=exact + b" ", headers=headers).status_code == 413


def test_uji_metrics_are_normalized_and_hidden_without_results(api, monkeypatch, tmp_path):
    client, _, _ = api
    summary = tmp_path / "uji-summary.json"
    metric = {"algorithm": "1nn", "accuracy": .9, "false_display_rate": .05,
              "unknown_rate": .05, "precision": .9 / .95, "latency_ms": .1}
    summary.write_text(json.dumps({"experiment_id": "uji-test", "metrics": [metric]}))
    monkeypatch.setitem(api_module.RESEARCH_SETS, "uji", (str(summary), "UJIIndoorLoc（大学の建物・階）"))
    uji = client.get("/api/research", params={"dataset": "uji"}).json()
    assert uji["experiment_id"] == "uji-test"
    assert uji["metrics"] == [{"id": None, "preprocessing": "none", **metric}]
    monkeypatch.setitem(api_module.RESEARCH_SETS, "uji", ("missing/summary.json", "UJIIndoorLoc（大学の建物・階）"))
    assert [d["id"] for d in client.get("/api/research").json()["datasets"]] == ["simulation"]


@pytest.mark.parametrize("length", [b"999999", b"abc", b"9" * 5000, b"0" * 5000 + b"32769"])
def test_declared_oversized_body_is_refused_before_reading(api, length):
    # The declared size alone decides: the app must answer 413 without waiting for any body bytes.
    _, app, _ = api

    async def run():
        sent = []

        async def receive():
            await asyncio.sleep(3600)

        async def send(message):
            sent.append(message)

        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1",
                 "method": "POST", "scheme": "http", "path": "/api/admin/teachers", "raw_path": b"/api/admin/teachers",
                 "query_string": b"", "root_path": "", "client": ("127.0.0.1", 5555), "server": ("127.0.0.1", 8000),
                 "headers": [(b"host", b"127.0.0.1:8000"), (b"content-length", length),
                             (b"content-type", b"application/json"), (b"authorization", f"Bearer {TOKEN}".encode())],
                 "state": {}}
        await asyncio.wait_for(app(scope, receive, send), 2)
        return next(m["status"] for m in sent if m["type"] == "http.response.start")

    assert asyncio.run(run()) == 413


def test_body_limit_accepts_long_zero_prefix_on_an_in_range_length(api):
    client, _, _ = api
    response = client.get("/api/health", headers={"Content-Length": "0" * 5000})
    assert response.status_code == 200


def test_deleting_every_teacher_survives_restart(tmp_path):
    database = str(tmp_path / "empty-directory.sqlite3")
    with TestClient(create_app(database, admin_token=TOKEN), base_url=BASE) as client:
        rows = client.get("/api/teachers").json()["teachers"]
        assert len(rows) == 6
        for row in rows:
            assert client.delete(f"/api/admin/teachers/{row['id']}", headers=AUTH).status_code == 204
        assert client.get("/api/teachers").json()["teachers"] == []
    app = create_app(database, admin_token=TOKEN)
    with TestClient(app, base_url=BASE) as client:
        assert client.get("/api/teachers").json()["teachers"] == []
        assert app.state.store.rows("SELECT * FROM latest") == []
        assert client.post("/api/admin/demo-refresh", headers=AUTH).json()["updated_count"] == 0


def test_empty_legacy_database_is_not_reseeded(tmp_path):
    import sqlite3
    database = str(tmp_path / "legacy-empty.sqlite3")
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE teachers (id TEXT PRIMARY KEY, name TEXT NOT NULL, subject TEXT NOT NULL, "
                   "device_id TEXT NOT NULL UNIQUE, private INTEGER NOT NULL DEFAULT 0)")
    app = create_app(database, admin_token=TOKEN)
    with TestClient(app, base_url=BASE) as client:
        assert client.get("/api/teachers").json()["teachers"] == []
        assert app.state.store.setting("demo_initialized", False) is True
        assert add_teacher(client)


def test_refresh_preserves_newer_measurements_and_updates_the_other_rows(api):
    client, app, current = api
    future = (current[0] + timedelta(seconds=3)).isoformat()
    assert measure(client, "demo-3", timestamp=future).status_code == 200
    saved = app.state.store.rows("SELECT observation FROM latest WHERE teacher_id='demo-3'")
    response = client.post("/api/admin/demo-refresh", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["updated_count"] == 4
    assert response.json()["skipped_newer_count"] == 1
    assert app.state.store.rows("SELECT observation FROM latest WHERE teacher_id='demo-3'") == saved
    assert public_teacher(client, "demo-4")["updated_at"] == current[0].isoformat()
    assert public_teacher(client, "demo-5")["status"] == "private"


def test_refresh_rolls_back_the_whole_batch_if_a_write_fails(api, monkeypatch):
    client, app, current = api
    store = app.state.store
    before = store.rows("SELECT * FROM latest ORDER BY teacher_id")
    current[0] += timedelta(seconds=1)
    execute = store.execute
    written = []

    def fail_second_write(query, params=()):
        if query.startswith("INSERT OR REPLACE INTO latest"):
            written.append(params[0])
            if len(written) == 2:
                raise RuntimeError("simulated storage failure")
        return execute(query, params)

    monkeypatch.setattr(store, "execute", fail_second_write)
    with pytest.raises(RuntimeError, match="simulated storage failure"):
        client.post("/api/admin/demo-refresh", headers=AUTH)
    assert len(written) == 2
    assert store.rows("SELECT * FROM latest ORDER BY teacher_id") == before
    monkeypatch.setattr(store, "execute", execute)
    assert client.post("/api/admin/demo-refresh", headers=AUTH).status_code == 200


@pytest.mark.parametrize("broken", ["{", "[]", '{"experiment_id":"broken","metrics":null}',
                                  '{"experiment_id":"broken","metrics":[{"algorithm":"knn"}]}',
                                  '{"experiment_id":"broken","metrics":[],"counts":[-1,2,3]}'])
def test_invalid_research_results_are_retryable_errors(api, monkeypatch, tmp_path, broken):
    client, _, _ = api
    summary = tmp_path / "summary.json"
    summary.write_text(broken)
    monkeypatch.setitem(api_module.RESEARCH_SETS, "simulation", (str(summary), "模擬データ"))
    response = client.get("/api/research")
    assert response.status_code == 503
    assert "再試行" in response.json()["detail"]
    assert str(tmp_path) not in response.text
    summary.write_text(json.dumps({"experiment_id": "recovered", "metrics": [], "counts": [1, 2, 3]}))
    response = client.get("/api/research")
    assert response.status_code == 200
    assert response.json()["experiment_id"] == "recovered"


def test_nonfinite_research_metric_is_not_sent_to_the_browser(api, monkeypatch, tmp_path):
    client, _, _ = api
    metric = {"algorithm": "knn", "accuracy": .9, "false_display_rate": .05, "unknown_rate": .05,
              "precision": .9 / .95, "latency_ms": float("nan")}
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({"experiment_id": "invalid-number", "metrics": [metric]}))
    monkeypatch.setitem(api_module.RESEARCH_SETS, "simulation", (str(summary), "模擬データ"))
    assert client.get("/api/research").status_code == 503
