"""Loopback research API. SQLite stores one current snapshot per fictitious PC."""

from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hmac
import json
import os
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Callable, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .algorithms import Engine
from .models import Observation
from .simulation import AP_AREAS, generate

ROOT = Path(__file__).resolve().parents[2]
AREAS = {"1F-west": "1階 西側", "1F-east": "1階 東側", "2F-west": "2階 西側",
         "2F-east": "2階 東側", "3F-west": "3階 西側", "3F-east": "3階 東側"}
ALGORITHMS = {"connected_ap": "接続先AP", "strongest_ap": "最強AP", "1nn": "1-NN",
              "knn": "k-NN", "weighted_knn": "距離重み付きk-NN", "rank": "RSSI順位", "gaussian": "確率的分類"}


class TeacherInput(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    subject: str = Field(min_length=1, max_length=30)
    device_id: str = Field(min_length=1, max_length=80)

    @field_validator("name", "subject", "device_id")
    @classmethod
    def clean(cls, value):
        if not value.strip():
            raise ValueError("空欄は使用できません")
        return value.strip()


class VisibilityInput(BaseModel):
    private: bool


class ConfigInput(BaseModel):
    algorithm: Literal["connected_ap", "strongest_ap", "1nn", "knn", "weighted_knn", "rank", "gaussian"]


class MappingInput(BaseModel):
    ap_areas: dict[str, str] = Field(max_length=100)


class MeasurementInput(BaseModel):
    teacher_id: str = Field(min_length=1, max_length=80)
    readings: dict[str, float] = Field(max_length=100)
    connected_ap: str | None = Field(default=None, max_length=80)
    timestamp: datetime | None = None

    @field_validator("readings")
    @classmethod
    def readings_valid(cls, values):
        import math
        if any(not key.strip() or len(key) > 80 or not math.isfinite(value) or not -120 <= value <= 0
               for key, value in values.items()):
            raise ValueError("RSSIは有限の-120〜0 dBm、AP識別子は1〜80文字です")
        return values

    @field_validator("timestamp")
    @classmethod
    def aware(cls, value):
        if value is not None and value.utcoffset() is None:
            raise ValueError("日時にタイムゾーンが必要です")
        return value


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = RLock()
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS teachers (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, subject TEXT NOT NULL,
                device_id TEXT NOT NULL UNIQUE, private INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS latest (
                teacher_id TEXT PRIMARY KEY REFERENCES teachers(id), observation TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        self.db.commit()

    def rows(self, query, params=()):
        with self.lock:
            return [dict(row) for row in self.db.execute(query, params).fetchall()]

    def execute(self, query, params=()):
        with self.lock, self.db:
            self.db.execute(query, params)

    def setting(self, key, fallback):
        rows = self.rows("SELECT value FROM settings WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else fallback

    def save_setting(self, key, value):
        self.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))


def create_app(db_path: str | None = None, admin_token: str | None = None,
               clock: Callable[[], datetime] | None = None) -> FastAPI:
    clock = clock or (lambda: datetime.now(timezone.utc))
    token = admin_token if admin_token is not None else os.getenv("WIFI_ADMIN_TOKEN", "dev-demo-token")
    if not token:
        raise ValueError("管理トークンを空にすることはできません")

    @asynccontextmanager
    async def lifespan(app):
        store = Store(db_path or os.getenv("WIFI_DB_PATH", str(ROOT / "data/demo.sqlite3")))
        app.state.store = store
        app.state.training = generate(seed=42, sessions=6, samples_per_area=12)
        if not store.rows("SELECT id FROM teachers"):
            for index, (name, subject) in enumerate([("青木 はるか", "国語"), ("佐藤 けん", "数学"),
                    ("高橋 みどり", "英語"), ("田中 あおい", "情報"), ("鈴木 りく", "理科"), ("小林 ひなた", "地歴公民")]):
                store.execute("INSERT INTO teachers VALUES (?,?,?,?,?)",
                              (f"demo-{index+1}", name, subject, f"demo-pc-{index+1}", int(index == 4)))
            refresh(app, initial=True)
        yield
        store.db.close()

    app = FastAPI(title="市川昴 PCエリア案内・研究プロトタイプ", lifespan=lifespan)
    security = HTTPBearer(auto_error=False)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Raw nonfinite JSON input cannot itself be encoded in a JSON response.
        # Return human-readable validation messages without echoing raw inputs.
        messages = [".".join(str(x) for x in error["loc"]) + ": " + error["msg"] for error in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": "; ".join(messages)})

    def authorized(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
        if credentials is None or not hmac.compare_digest(credentials.credentials.encode(), token.encode()):
            raise HTTPException(401, "開発用管理トークンが必要です", headers={"WWW-Authenticate": "Bearer"})

    def engine():
        store = app.state.store
        algorithm = store.setting("algorithm", "knn")
        return Engine(app.state.training, store.setting("ap_areas", AP_AREAS),
                      algorithm=algorithm, max_distance=16,
                      min_margin={"rank": 0.0, "gaussian": .1}.get(algorithm, .25))

    def teacher(identifier):
        rows = app.state.store.rows("SELECT * FROM teachers WHERE id=?", (identifier,))
        if not rows:
            raise HTTPException(404, "先生が見つかりません")
        return rows[0]

    def put_observation(identifier, observation):
        # Replaces current measurement; there is intentionally no observation-history table.
        store = app.state.store
        # Serialize opt-out and ingestion so a concurrent request cannot restore
        # a measurement after the teacher has switched to private.
        with store.lock:
            if teacher(identifier)["private"]:
                raise HTTPException(409, "非公開の先生には測定を保存しません")
            existing = store.rows("SELECT observation FROM latest WHERE teacher_id=?", (identifier,))
            if existing and datetime.fromisoformat(json.loads(existing[0]["observation"])["timestamp"]) > observation.timestamp:
                raise HTTPException(409, "保存済みの測定より古いデータです")
            payload = asdict(observation)
            payload["timestamp"] = observation.timestamp.isoformat()
            store.execute("INSERT OR REPLACE INTO latest VALUES (?,?)", (identifier, json.dumps(payload)))

    def snapshot(row, admin=False):
        public = {"id": row["id"], "name": row["name"], "subject": row["subject"],
                  "status": "unknown", "area": None, "updated_at": None, "reason": "no_data"}
        if row["private"] and not admin:
            return {**public, "status": "private", "reason": None}
        observations = app.state.store.rows("SELECT observation FROM latest WHERE teacher_id=?", (row["id"],))
        if observations:
            data = json.loads(observations[0]["observation"])
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
            result = engine().predict(Observation(**data), now=clock())
            public.update(status="unknown" if result.area == "unknown" else "located",
                          area=AREAS.get(result.area, result.area) if result.area != "unknown" else None,
                          reason=result.reason, updated_at=data["timestamp"].isoformat())
            if admin:
                public.update(estimate=asdict(result), readings=data["readings"])
        if admin:
            public.update(device_id=row["device_id"], private=bool(row["private"]))
            if row["private"]:
                public.update(status="private", area=None, updated_at=None, reason=None)
        return public

    def refresh(application, initial=False):
        pool = application.state.training
        for index, row in enumerate(application.state.store.rows("SELECT * FROM teachers ORDER BY id")):
            if row["private"]:
                continue
            area = list(AREAS)[index % len(AREAS)]
            representative = next(o for o in pool if o.area == area and len(o.readings) >= 3)
            readings = representative.readings if index != 5 else {}
            timestamp = clock() - timedelta(seconds=600 if initial and index == 3 else 0)
            put_observation(row["id"], Observation(timestamp, readings, row["device_id"],
                            "manual-static-demo", connected_ap=representative.connected_ap, source="simulation"))

    @app.get("/api/health")
    def health():
        return {"status": "ok", "demo": True, "network_collectors_enabled": False}

    @app.get("/api/teachers")
    def teachers(q: str = "", subject: str = ""):
        rows = app.state.store.rows("SELECT * FROM teachers ORDER BY name")
        return {"teachers": [snapshot(row) for row in rows if q.casefold() in row["name"].casefold()
                             and (not subject or subject == row["subject"])], "demo": True}

    @app.get("/api/areas")
    def areas():
        return {"areas": [{"id": key, "label": value} for key, value in AREAS.items()]}

    @app.get("/api/config")
    def config():
        return {"algorithm": app.state.store.setting("algorithm", "knn"),
                "algorithms": [{"id": key, "label": value} for key, value in ALGORITHMS.items()], "demo": True}

    @app.get("/api/admin/teachers", dependencies=[Depends(authorized)])
    def admin_teachers():
        return {"teachers": [snapshot(row, admin=True) for row in app.state.store.rows("SELECT * FROM teachers ORDER BY name")], "demo": True}

    @app.post("/api/admin/teachers", dependencies=[Depends(authorized)], status_code=201)
    def add_teacher(data: TeacherInput):
        identifier = uuid4().hex
        try:
            app.state.store.execute("INSERT INTO teachers VALUES (?,?,?,?,0)",
                (identifier, data.name, data.subject, data.device_id))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "この実験端末IDは登録済みです")
        return snapshot(teacher(identifier), admin=True)

    @app.patch("/api/admin/teachers/{identifier}", dependencies=[Depends(authorized)])
    def visibility(identifier: str, data: VisibilityInput):
        with app.state.store.lock:
            teacher(identifier)
            app.state.store.execute("UPDATE teachers SET private=? WHERE id=?", (int(data.private), identifier))
            if data.private:
                app.state.store.execute("DELETE FROM latest WHERE teacher_id=?", (identifier,))
        return snapshot(teacher(identifier), admin=True)

    @app.get("/api/admin/ap-areas", dependencies=[Depends(authorized)])
    def ap_areas():
        return {"ap_areas": app.state.store.setting("ap_areas", AP_AREAS)}

    @app.put("/api/admin/ap-areas", dependencies=[Depends(authorized)])
    def mapping(data: MappingInput):
        if any(not key.strip() or len(key) > 80 or value not in AREAS for key, value in data.ap_areas.items()):
            raise HTTPException(422, "AP識別子と既知のエリアを指定してください")
        app.state.store.save_setting("ap_areas", data.ap_areas)
        return data

    @app.put("/api/admin/config", dependencies=[Depends(authorized)])
    def configure(data: ConfigInput):
        app.state.store.save_setting("algorithm", data.algorithm)
        return config()

    @app.post("/api/admin/observations", dependencies=[Depends(authorized)])
    def observation(data: MeasurementInput):
        row = teacher(data.teacher_id)
        if row["private"]:
            raise HTTPException(409, "非公開の先生には測定を保存しません")
        stamp = data.timestamp or clock()
        if stamp > clock() + timedelta(seconds=5):
            raise HTTPException(422, "未来の測定日時は使用できません")
        put_observation(row["id"], Observation(stamp, data.readings, row["device_id"],
                        "manual-static-demo", connected_ap=data.connected_ap, source="simulation"))
        return snapshot(row, admin=True)

    @app.post("/api/admin/demo-refresh", dependencies=[Depends(authorized)])
    def demo_refresh():
        refresh(app)
        return admin_teachers()

    @app.get("/api/research")
    def research():
        # This endpoint serves ONLY synthetic, identity-free research artifacts.
        result_path = ROOT / "results/latest/summary.json"
        summary = json.loads(result_path.read_text()) if result_path.exists() else {}
        first_session = app.state.training[0].session_id
        series = [{"time": o.timestamp.isoformat(), **o.readings} for o in app.state.training if o.session_id == first_session]
        sample = next(o for o in app.state.training if len(o.readings) >= 3)
        candidates = engine().predict(sample, now=sample.timestamp).scores
        return {"source": "simulation", "experiment_id": summary.get("experiment_id", "not-run"),
                "metrics": summary.get("metrics", []), "series": series,
                "candidates": [{"area": AREAS.get(key, key), "score": value} for key, value in candidates.items()],
                "note": "模擬データの結果です。実環境性能や先生本人の現在地を示しません。候補スコアは学習サンプルを入力した説明用の例で、正解確率ではありません。"}

    dist = ROOT / "frontend/dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()
