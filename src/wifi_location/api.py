"""Loopback research API. SQLite stores one current snapshot per fictitious PC."""

import asyncio
from contextlib import asynccontextmanager, contextmanager, suppress
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hmac
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import sys
from threading import RLock
from typing import Callable, Literal
import unicodedata
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Path as PathParam, Query, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .algorithms import Engine
from .models import Observation
from .simulation import AP_AREAS, generate

ROOT = Path(__file__).resolve().parents[2]
AREAS = {"1F-west": "1階 西側", "1F-east": "1階 東側", "2F-west": "2階 西側",
         "2F-east": "2階 東側", "3F-west": "3階 西側", "3F-east": "3階 東側"}
ALGORITHMS = {"connected_ap": "接続先AP", "strongest_ap": "最強AP", "1nn": "1-NN",
              "knn": "k-NN", "weighted_knn": "距離重み付きk-NN", "rank": "RSSI順位", "gaussian": "確率的分類"}
DEMO_TEACHERS = [("青木 はるか", "あおき はるか", "国語"), ("佐藤 けん", "さとう けん", "数学"),
                 ("高橋 みどり", "たかはし みどり", "英語"), ("田中 あおい", "たなか あおい", "情報"),
                 ("鈴木 りく", "すずき りく", "理科"), ("小林 ひなた", "こばやし ひなた", "地歴公民")]
RESEARCH_SETS = {"simulation": ("results/latest/summary.json", "模擬データ（学校6エリア）"),
                 "uji": ("results/uji/summary.json", "UJIIndoorLoc（大学の建物・階）")}
# A DNS-rebinding page reaches 127.0.0.1 under its own host name, so only loopback names are served.
DEFAULT_HOSTS = ["127.0.0.1", "localhost", "[::1]"]
MAX_BODY_BYTES = 32 * 1024
DEFAULT_RETENTION_SECONDS = 3600
MAX_RETENTION_SECONDS = 10 * 365 * 24 * 3600
PURGE_INTERVAL_SECONDS = 60
# Hiragana, katakana (incl. ゠ ・ ー), iteration marks, spaces, and = for names like ジャン＝ポール.
KANA = re.compile(r"[ぁ-ゖゝゞ゠-ヺ・-ヾ =]+")
# A Bearer token travels in an HTTP header, so only visible ASCII can ever match.
TOKEN_CHARACTERS = re.compile(r"[\x21-\x7e]+")
FIELD_LABELS = {"name": "名前", "kana": "よみがな", "subject": "教科", "device_id": "実験端末ID",
                "teacher_id": "先生", "readings": "RSSI", "connected_ap": "接続AP", "timestamp": "測定日時",
                "private": "公開設定", "algorithm": "推定方式", "ap_areas": "APとエリアの対応",
                "q": "検索語", "dataset": "データ", "identifier": "ID"}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
       "form-action 'self'; frame-ancestors 'none'")


def has_hidden_characters(value: str) -> bool:
    # Control, format (bidi overrides, zero-width), surrogate, private-use and line-separator characters.
    # Unassigned code points (Cn) stay allowed: newer CJK characters are unassigned in older Unicode data.
    return any(unicodedata.category(c) in ("Cc", "Cf", "Cs", "Co", "Zl", "Zp") for c in value)


def plain_text(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("空欄は使用できません")
    if has_hidden_characters(value):
        raise ValueError("改行・制御文字・書式文字は使用できません")
    return value


def host_pattern(value: str) -> str:
    """One WIFI_ALLOWED_HOSTS entry as Starlette compares it: lower case, IPv6 in brackets, no port."""
    value = value.strip().lower()
    if value.startswith("[") and "]" in value:
        return value[:value.index("]") + 1]
    with suppress(ValueError):
        if ipaddress.ip_address(value).version == 6:
            return f"[{value}]"
    return value.split(":")[0] if value.count(":") == 1 else value


def validation_message(error) -> str:
    """A short Japanese message for one pydantic error, without echoing the submitted value."""
    field = next((x for x in reversed(error["loc"]) if isinstance(x, str) and x in FIELD_LABELS), None)
    label = FIELD_LABELS.get(field, "入力")
    kind, limit = error["type"], (error.get("ctx") or {}).get("max_length")
    if kind == "value_error":
        return error["msg"].removeprefix("Value error, ")
    if kind in ("missing", "string_too_short"):
        return f"{label}を入力してください"
    if kind == "string_too_long":
        return f"{label}は{limit}文字以内で入力してください"
    if kind == "too_long":
        return f"{label}は{limit}件以内にしてください"
    if kind == "extra_forbidden":
        return "使用できない項目が含まれています"
    if kind in ("json_invalid", "model_attributes_type", "dict_type"):
        return "送信データの形式が正しくありません"
    return f"{label}の値が正しくありません"


def search_key(value: str) -> str:
    """Comparable form: NFKC, no spaces, katakana as hiragana, without a trailing 先生."""
    text = "".join(unicodedata.normalize("NFKC", value).casefold().split())
    text = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)
    return text.removesuffix("先生").removesuffix("せんせい")


class TeacherInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=60)
    kana: str = Field(default="", max_length=60)
    subject: str = Field(min_length=1, max_length=30)
    device_id: str = Field(min_length=1, max_length=80)

    @field_validator("name", "subject", "device_id")
    @classmethod
    def clean(cls, value):
        return plain_text(value)

    @field_validator("kana")
    @classmethod
    def reading(cls, value):
        # NFKC can lengthen text (e.g. ㌖ becomes キロメートル), so the length is checked again here.
        value = " ".join(unicodedata.normalize("NFKC", value).split())
        if value and not KANA.fullmatch(value):
            raise ValueError("よみがなはひらがなかカタカナで入力してください")
        if len(value) > 60:
            raise ValueError("よみがなは60文字以内で入力してください")
        return value


class VisibilityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    private: bool


class ConfigInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    algorithm: Literal["connected_ap", "strongest_ap", "1nn", "knn", "weighted_knn", "rank", "gaussian"]


class MappingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ap_areas: dict[str, str] = Field(max_length=100)


class MeasurementInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    teacher_id: str = Field(min_length=1, max_length=80)
    readings: dict[str, float] = Field(max_length=100)
    connected_ap: str | None = Field(default=None, max_length=80)
    timestamp: datetime | None = None

    @field_validator("readings")
    @classmethod
    def readings_valid(cls, values):
        if any(not key.strip() or len(key) > 80 or has_hidden_characters(key)
               or not math.isfinite(value) or not -120 <= value <= 0 for key, value in values.items()):
            raise ValueError("RSSIは-120〜0 dBmの数値、AP識別子は制御文字を含まない1〜80文字です")
        return values

    @field_validator("connected_ap")
    @classmethod
    def connected(cls, value):
        # A blank selection means the connected AP is unknown.
        if value is None or not value.strip():
            return None
        return plain_text(value)

    @field_validator("timestamp")
    @classmethod
    def aware(cls, value):
        if value is not None and value.utcoffset() is None:
            raise ValueError("日時にタイムゾーンが必要です")
        return value


class ResearchMetric(BaseModel):
    """Validate the fields the browser renders, rather than forwarding a partial JSON file."""
    model_config = ConfigDict(strict=True, allow_inf_nan=False)
    algorithm: str
    accuracy: float = Field(ge=0, le=1)
    false_display_rate: float = Field(ge=0, le=1)
    unknown_rate: float = Field(ge=0, le=1)
    precision: float | None = Field(ge=0, le=1)
    latency_ms: float = Field(ge=0)
    id: str | None = None
    preprocessing: str = "none"
    k: int | None = Field(default=None, ge=1)
    selection: str | None = None
    selected_aps: list[str] | None = None


class ResearchSummary(BaseModel):
    model_config = ConfigDict(strict=True)
    experiment_id: str
    metrics: list[ResearchMetric]
    counts: list[int] = Field(default_factory=list)
    created_at: str | None = None
    citation: str | None = None
    license: str | None = None

    @field_validator("counts")
    @classmethod
    def split_counts(cls, value):
        if (value and len(value) != 3) or any(count < 0 for count in value):
            raise ValueError("counts must contain the training, validation and test sizes")
        return value


def read_research_summary(path: Path) -> dict:
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError):
        raise HTTPException(503, "実験結果を読み込めません。結果ファイルを確認してから再試行してください。") from None
    try:
        return ResearchSummary.model_validate_json(content).model_dump(exclude_unset=True)
    except ValidationError:
        raise HTTPException(503, "実験結果が書き込み途中か、形式が正しくありません。実験の完了後に再試行してください。") from None


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = RLock()
        self._transaction_depth = 0
        # An existing empty directory may be intentional. Never reseed it on restart.
        self.is_new = not self.rows("SELECT name FROM sqlite_master WHERE type='table' AND name='teachers'")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS teachers (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, subject TEXT NOT NULL,
                device_id TEXT NOT NULL UNIQUE, private INTEGER NOT NULL DEFAULT 0,
                kana TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS latest (
                teacher_id TEXT PRIMARY KEY REFERENCES teachers(id), observation TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        # Databases created before the reading column existed are migrated in place.
        if "kana" not in {row["name"] for row in self.rows("PRAGMA table_info(teachers)")}:
            self.execute("ALTER TABLE teachers ADD COLUMN kana TEXT NOT NULL DEFAULT ''")
        for index, (name, kana, _) in enumerate(DEMO_TEACHERS):
            self.execute("UPDATE teachers SET kana=? WHERE id=? AND name=? AND kana=''",
                         (kana, f"demo-{index+1}", name))
        self.db.commit()

    def rows(self, query, params=()):
        with self.lock:
            return [dict(row) for row in self.db.execute(query, params).fetchall()]

    def execute(self, query, params=()):
        with self.transaction():
            self.db.execute(query, params)

    @contextmanager
    def transaction(self):
        """Serialize a group of writes, committing nested helpers only at the outer boundary."""
        with self.lock:
            outer = self._transaction_depth == 0
            if outer:
                self.db.execute("BEGIN IMMEDIATE")
            self._transaction_depth += 1
            try:
                yield
                if outer:
                    self.db.commit()
            except BaseException:
                if outer:
                    self.db.rollback()
                raise
            finally:
                self._transaction_depth -= 1

    def setting(self, key, fallback):
        rows = self.rows("SELECT value FROM settings WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else fallback

    def save_setting(self, key, value):
        self.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))

    def purge_before(self, cutoff: datetime) -> int:
        """Delete current measurements older than the retention cutoff."""
        with self.transaction():
            expired = [row["teacher_id"] for row in self.db.execute("SELECT * FROM latest").fetchall()
                       if datetime.fromisoformat(json.loads(row["observation"])["timestamp"]) < cutoff]
            self.db.executemany("DELETE FROM latest WHERE teacher_id=?", [(x,) for x in expired])
        return len(expired)


class BrowserSafetyMiddleware:
    """Caps request bodies and adds hardening headers to every HTTP response."""

    def __init__(self, app, max_body: int = MAX_BODY_BYTES):
        self.app, self.max_body = app, max_body

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        started = False

        async def send_with_headers(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = [(b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer"),
                           (b"x-frame-options", b"DENY"), (b"cross-origin-opener-policy", b"same-origin"),
                           (b"permissions-policy", b"camera=(), microphone=(), geolocation=()")]
                # Swagger UI at /docs loads its own inline script, so it keeps the default policy.
                if not path.startswith(("/docs", "/redoc")):
                    headers.append((b"content-security-policy", CSP.encode()))
                if path.startswith("/api/"):
                    headers.append((b"cache-control", b"no-store"))
                elif path.startswith("/assets/") and message["status"] == 200:
                    # Vite puts a content hash in each asset name, so a rebuilt file always gets a new URL.
                    headers.append((b"cache-control", b"public, max-age=31536000, immutable"))
                elif not path.startswith(("/docs", "/redoc", "/openapi.json")):
                    # index.html must be revalidated, or a browser keeps loading the previous build.
                    headers.append((b"cache-control", b"no-cache"))
                message = {**message, "headers": [*message.get("headers", []), *headers]}
            await send(message)

        length = dict(scope["headers"]).get(b"content-length")
        # Compare decimal text before converting: a hostile, thousands-of-digits
        # value can exceed Python's integer conversion limit even without a body.
        normalized_length = (length.lstrip(b"0") or b"0") if length is not None else b"0"
        limit = str(self.max_body).encode("ascii")
        if length is not None and (not length.isdigit() or len(normalized_length) > len(limit)
                                   or (len(normalized_length) == len(limit) and normalized_length > limit)):
            response = JSONResponse({"detail": "送信データが大きすぎます"}, status_code=413)
            await response(scope, receive, send_with_headers)
            return
        received = 0

        async def limited_receive():
            # Chunked bodies have no Content-Length, so count what actually arrives.
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body:
                    if started:
                        # A response (e.g. a static file) is already streaming: stop reading quietly.
                        return {"type": "http.disconnect"}
                    raise HTTPException(413, "送信データが大きすぎます")
            return message

        await self.app(scope, limited_receive, send_with_headers)


def create_app(db_path: str | None = None, admin_token: str | None = None,
               clock: Callable[[], datetime] | None = None, allowed_hosts: list[str] | None = None,
               retention_seconds: float | None = None) -> FastAPI:
    clock = clock or (lambda: datetime.now(timezone.utc))
    token = admin_token if admin_token is not None else os.getenv("WIFI_ADMIN_TOKEN")
    # Without a configured token, every launch gets an unguessable one instead of a shared default.
    generated = token is None
    if generated:
        token = secrets.token_urlsafe(18)
    if not token:
        raise ValueError("管理トークンを空にすることはできません")
    if not TOKEN_CHARACTERS.fullmatch(token):
        raise ValueError("管理トークンには半角の英数字と記号だけを使ってください（空白や全角文字は使えません）")
    if allowed_hosts is None:
        allowed_hosts = [x for x in os.getenv("WIFI_ALLOWED_HOSTS", "").split(",") if x.strip()] or DEFAULT_HOSTS
    allowed_hosts = [host_pattern(x) for x in allowed_hosts]
    if retention_seconds is None:
        try:
            retention_seconds = float(os.getenv("WIFI_RETENTION_SECONDS", DEFAULT_RETENTION_SECONDS))
        except ValueError:
            raise ValueError("WIFI_RETENTION_SECONDS には保持する秒数を数字で指定してください") from None
    if not math.isfinite(retention_seconds) or not 0 < retention_seconds <= MAX_RETENTION_SECONDS:
        raise ValueError("保持期間は1秒〜10年の範囲の秒数で指定してください")

    @asynccontextmanager
    async def lifespan(app):
        store = Store(db_path or os.getenv("WIFI_DB_PATH", str(ROOT / "data/demo.sqlite3")))
        app.state.store = store
        app.state.training = generate(seed=42, sessions=6, samples_per_area=12)
        app.state.engine = None
        with store.transaction():
            if store.setting("demo_initialized", False) is False:
                if store.is_new:
                    for index, (name, kana, subject) in enumerate(DEMO_TEACHERS):
                        store.execute("INSERT INTO teachers (id, name, subject, device_id, private, kana) VALUES (?,?,?,?,?,?)",
                                      (f"demo-{index+1}", name, subject, f"demo-pc-{index+1}", int(index == 4), kana))
                    refresh(app, initial=True)
                store.save_setting("demo_initialized", True)
        purge_expired()
        if generated:
            print(f"[wifi-location] 管理画面のトークン（この起動中のみ有効）: {token}", file=sys.stderr, flush=True)
        elif len(token) < 16:
            print("[wifi-location] 注意: WIFI_ADMIN_TOKEN が短すぎます。16文字以上を推奨します。", file=sys.stderr, flush=True)

        async def purge_periodically():
            # Expired rows are deleted even when nobody opens the list.
            while True:
                await asyncio.sleep(PURGE_INTERVAL_SECONDS)
                await asyncio.to_thread(purge_expired)

        purger = asyncio.create_task(purge_periodically())
        yield
        purger.cancel()
        with suppress(asyncio.CancelledError):
            await purger
        store.db.close()

    app = FastAPI(title="市川昴 PCエリア案内・研究プロトタイプ", lifespan=lifespan)
    security = HTTPBearer(auto_error=False)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Raw nonfinite JSON input cannot itself be encoded in a JSON response.
        # Return human-readable validation messages without echoing raw inputs.
        messages = list(dict.fromkeys(validation_message(error) for error in exc.errors()))
        return JSONResponse(status_code=422, content={"detail": " / ".join(messages)})

    def authorized(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
        if credentials is None or not hmac.compare_digest(credentials.credentials.encode(), token.encode()):
            raise HTTPException(401, "管理トークンが正しくありません", headers={"WWW-Authenticate": "Bearer"})

    def engine():
        # Reuse the classifier until the algorithm or AP mapping changes.
        store = app.state.store
        algorithm = store.setting("algorithm", "knn")
        mapping = store.setting("ap_areas", AP_AREAS)
        key = (algorithm, json.dumps(mapping, sort_keys=True))
        if app.state.engine is None or app.state.engine[0] != key:
            app.state.engine = (key, Engine(app.state.training, mapping, algorithm=algorithm, max_distance=16,
                                            min_margin={"rank": 0.0, "gaussian": .1}.get(algorithm, .25)))
        return app.state.engine[1]

    def purge_expired():
        app.state.store.purge_before(clock() - timedelta(seconds=retention_seconds))

    def teacher(identifier):
        rows = app.state.store.rows("SELECT * FROM teachers WHERE id=?", (identifier,))
        if not rows:
            raise HTTPException(404, "先生が見つかりません")
        return rows[0]

    def ordered(rows):
        # 五十音順 by reading; teachers without a reading follow, ordered by name.
        return sorted(rows, key=lambda row: (not row["kana"], search_key(row["kana"] or row["name"]), row["name"]))

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

    def snapshot(row, admin=False, estimator=None):
        public = {"id": row["id"], "name": row["name"], "kana": row["kana"], "subject": row["subject"],
                  "status": "unknown", "area": None, "updated_at": None, "reason": "no_data"}
        if row["private"] and not admin:
            return {**public, "status": "private", "reason": None}
        observations = app.state.store.rows("SELECT observation FROM latest WHERE teacher_id=?", (row["id"],))
        if observations:
            data = json.loads(observations[0]["observation"])
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
            result = (estimator or engine()).predict(Observation(**data), now=clock())
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

    def snapshots(admin=False, match=lambda row: True):
        # One lock and one classifier per response, so every row reflects the same state.
        store = app.state.store
        with store.lock:
            purge_expired()
            estimator = engine()
            return [snapshot(row, admin, estimator) for row in ordered(store.rows("SELECT * FROM teachers")) if match(row)]

    def refresh(application, initial=False):
        pool = application.state.training
        store, stamp = application.state.store, clock()
        updated = skipped = 0
        # Keep newer permitted measurements and make the remaining batch all-or-nothing.
        with store.transaction():
            for index, row in enumerate(store.rows("SELECT * FROM teachers ORDER BY id")):
                if row["private"]:
                    continue
                timestamp = stamp - timedelta(seconds=600 if initial and index == 3 else 0)
                existing = store.rows("SELECT observation FROM latest WHERE teacher_id=?", (row["id"],))
                if existing and datetime.fromisoformat(json.loads(existing[0]["observation"])["timestamp"]) > timestamp:
                    skipped += 1
                    continue
                area = list(AREAS)[index % len(AREAS)]
                representative = next(o for o in pool if o.area == area and len(o.readings) >= 3)
                readings = representative.readings if index != 5 else {}
                put_observation(row["id"], Observation(timestamp, readings, row["device_id"],
                                "manual-static-demo", connected_ap=representative.connected_ap, source="simulation"))
                updated += 1
        return {"updated_count": updated, "skipped_newer_count": skipped}

    @app.get("/api/health")
    def health():
        return {"status": "ok", "demo": True, "network_collectors_enabled": False}

    @app.get("/api/teachers")
    def teachers(q: str = Query("", max_length=100), subject: str = Query("", max_length=30)):
        key = search_key(q)
        match = lambda row: ((key in search_key(row["name"]) or key in search_key(row["kana"]))
                             and (not subject or subject == row["subject"]))
        return {"teachers": snapshots(match=match), "demo": True}

    @app.get("/api/areas")
    def areas():
        return {"areas": [{"id": key, "label": value} for key, value in AREAS.items()]}

    @app.get("/api/config")
    def config():
        return {"algorithm": app.state.store.setting("algorithm", "knn"),
                "algorithms": [{"id": key, "label": value} for key, value in ALGORITHMS.items()], "demo": True}

    @app.get("/api/admin/teachers", dependencies=[Depends(authorized)])
    def admin_teachers():
        return {"teachers": snapshots(admin=True), "demo": True}

    @app.post("/api/admin/teachers", dependencies=[Depends(authorized)], status_code=201)
    def add_teacher(data: TeacherInput):
        identifier = uuid4().hex
        try:
            app.state.store.execute("INSERT INTO teachers (id, name, subject, device_id, private, kana) VALUES (?,?,?,?,0,?)",
                (identifier, data.name, data.subject, data.device_id, data.kana))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "この実験端末IDは登録済みです")
        return snapshot(teacher(identifier), admin=True)

    @app.patch("/api/admin/teachers/{identifier}", dependencies=[Depends(authorized)])
    def visibility(data: VisibilityInput, identifier: str = PathParam(max_length=80)):
        with app.state.store.transaction():
            teacher(identifier)
            app.state.store.execute("UPDATE teachers SET private=? WHERE id=?", (int(data.private), identifier))
            if data.private:
                app.state.store.execute("DELETE FROM latest WHERE teacher_id=?", (identifier,))
        return snapshot(teacher(identifier), admin=True)

    @app.delete("/api/admin/teachers/{identifier}", dependencies=[Depends(authorized)], status_code=204)
    def remove_teacher(identifier: str = PathParam(max_length=80)):
        store = app.state.store
        with store.transaction():
            teacher(identifier)
            store.db.execute("DELETE FROM latest WHERE teacher_id=?", (identifier,))
            store.db.execute("DELETE FROM teachers WHERE id=?", (identifier,))
        return Response(status_code=204)

    @app.get("/api/admin/ap-areas", dependencies=[Depends(authorized)])
    def ap_areas():
        return {"ap_areas": app.state.store.setting("ap_areas", AP_AREAS)}

    @app.put("/api/admin/ap-areas", dependencies=[Depends(authorized)])
    def mapping(data: MappingInput):
        if any(not key.strip() or len(key) > 80 or has_hidden_characters(key) or value not in AREAS
               for key, value in data.ap_areas.items()):
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
        if stamp < clock() - timedelta(seconds=retention_seconds):
            raise HTTPException(422, "保持期間より古い測定は保存できません")
        put_observation(row["id"], Observation(stamp, data.readings, row["device_id"],
                        "manual-static-demo", connected_ap=data.connected_ap, source="simulation"))
        return snapshot(row, admin=True)

    @app.post("/api/admin/demo-refresh", dependencies=[Depends(authorized)])
    def demo_refresh():
        counts = refresh(app)
        return {**admin_teachers(), **counts}

    @app.get("/api/research")
    def research(dataset: Literal["simulation", "uji"] = "simulation"):
        # This endpoint serves ONLY synthetic or public, identity-free research artifacts.
        summaries = {key: ROOT / path for key, (path, _) in RESEARCH_SETS.items()}
        available = [{"id": key, "label": label} for key, (_, label) in RESEARCH_SETS.items()
                     if key == "simulation" or summaries[key].exists()]
        summary = read_research_summary(summaries[dataset])
        common = {"dataset": dataset, "datasets": available, "experiment_id": summary.get("experiment_id", "not-run"),
                  "counts": summary.get("counts", []), "created_at": summary.get("created_at")}
        if dataset == "uji":
            metrics = [{"id": None, "preprocessing": "none", **metric} for metric in summary.get("metrics", [])]
            return {**common, "source": "ujindoorloc", "metrics": metrics, "series": [], "candidates": [],
                    "citation": summary.get("citation"), "license": summary.get("license"),
                    "note": "公開データセットによる独立評価です。対象は大学の建物・階の分類で、学校の6エリアとは異なるため、模擬データの正解率とは直接比べられません。"}
        first_session = app.state.training[0].session_id
        series = [{"time": o.timestamp.isoformat(), **o.readings} for o in app.state.training if o.session_id == first_session]
        sample = next(o for o in app.state.training if len(o.readings) >= 3)
        candidates = engine().predict(sample, now=sample.timestamp).scores
        return {**common, "source": "simulation",
                "metrics": summary.get("metrics", []), "series": series,
                "candidates": [{"area": AREAS.get(key, key), "score": value} for key, value in candidates.items()],
                "note": "模擬データの結果です。実環境性能や先生本人の現在地を示しません。候補スコアは学習サンプルを入力した説明用の例で、正解確率ではありません。"}

    dist = ROOT / "frontend/dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    app.add_middleware(BrowserSafetyMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    return app


app = create_app()
