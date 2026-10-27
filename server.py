#!/usr/bin/env python3
"""
MiniBient - Ambient (ambidata.io) 互換の小さな IoT データ可視化サーバー

  * Python 3.8 以降の標準ライブラリだけで動きます（pip install 不要）
  * Ambient と同じ API でデータを受け取ります
      POST /api/v2/channels/{id}/data       {"writeKey":..., "d1":..., ..., "d8":..., "lat", "lng", "created", "cmnt"}
      POST /api/v2/channels/{id}/dataarray  {"writeKey":..., "data":[{...}, ...]}
      GET  /api/v2/channels/{id}/data?readKey=...&n=10   (新しい順)
      GET  /api/v2/channels/{id}?readKey=...             (チャネル情報)
  * データは SQLite ファイル (minibient.db) に保存します

起動:  python3 server.py              (http://0.0.0.0:8080)
設定は環境変数またはコマンドライン引数で（python3 server.py --help）
"""
import argparse
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

VERSION = "1.0.0"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

FIELDS = ["d1", "d2", "d3", "d4", "d5", "d6", "d7", "d8"]
DEFAULT_COLORS = ["#2563eb", "#dc2626", "#16a34a", "#d97706",
                  "#7c3aed", "#0891b2", "#db2777", "#4b5563"]


# ---------------------------------------------------------------- settings
class Config:
    host = "0.0.0.0"
    port = 8080
    db = os.path.join(BASE_DIR, "minibient.db")
    admin_password = ""          # 空なら起動時に自動生成して表示
    registration = "invite"      # ユーザー登録: "invite"=招待コードが必要 / "open"=誰でも / "closed"=受け付けない
    invite_code = ""             # 招待コードを固定したい場合に指定（空なら管理画面で表示・作り直し）
    max_channels = 3             # 1ユーザーが持てるチャネル数
    session_days = 45            # ログインしたままでいられる日数
    prefer_https = False         # True: ブラウザーは https に切り替え、送信方法も https を案内（http の送信も受け付ける）
    tz_offset = 9.0              # date/start/end 指定や画面表示に使う時差（時間）
    max_rows = 200_000           # 1チャネルあたりの最大保存件数（超えたら古い順に削除）
    min_interval = 25.0          # 同一チャネルへの最短送信間隔（秒）。これより短い間隔の送信は 429 で拒否。0 で無制限
    max_body = 2 * 1024 * 1024   # 受け付ける最大リクエストサイズ
    base_path = ""               # サブフォルダーに置く場合のURLの先頭（例 "/minibient"）
    journal_mode = "WAL"         # CGI（レンタルサーバー）では "DELETE" を使う


CFG = Config()


def local_tz():
    return timezone(timedelta(hours=CFG.tz_offset))


# ---------------------------------------------------------------- database
class DB:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=15)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=%s" % CFG.journal_mode)
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS channels (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            write_key   TEXT NOT NULL,
            read_key    TEXT NOT NULL,
            is_public   INTEGER NOT NULL DEFAULT 1,
            fields      TEXT NOT NULL DEFAULT '{}',
            created_at  INTEGER NOT NULL,
            last_post   INTEGER
        );
        CREATE TABLE IF NOT EXISTS data (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            created    INTEGER NOT NULL,
            d1 REAL, d2 REAL, d3 REAL, d4 REAL, d5 REAL, d6 REAL, d7 REAL, d8 REAL,
            lat REAL, lng REAL,
            cmnt TEXT,
            hide INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_data_ch_created ON data(channel_id, created);
        CREATE TABLE IF NOT EXISTS users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT NOT NULL UNIQUE COLLATE NOCASE,
            display_name TEXT NOT NULL DEFAULT '',
            pw_hash      TEXT NOT NULL,
            must_change  INTEGER NOT NULL DEFAULT 0,
            failed       INTEGER NOT NULL DEFAULT 0,
            locked_until INTEGER NOT NULL DEFAULT 0,
            created_at   INTEGER NOT NULL,
            last_login   INTEGER
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id    INTEGER NOT NULL,
            expires    INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """)
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(channels)")]
        if "owner_id" not in cols:  # 旧バージョンの DB からの移行
            self.conn.execute("ALTER TABLE channels ADD COLUMN owner_id INTEGER")
        # チャネルIDを Ambient 風の5桁から始める
        cur = self.conn.execute("SELECT seq FROM sqlite_sequence WHERE name='channels'")
        if cur.fetchone() is None and self.conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0] == 0:
            self.conn.execute("INSERT INTO sqlite_sequence(name, seq) VALUES('channels', 10000)")
        self.conn.commit()

    def q(self, sql, args=(), one=False):
        with self.lock:
            cur = self.conn.execute(sql, args)
            rows = cur.fetchall()
        return (rows[0] if rows else None) if one else rows

    def x(self, sql, args=()):
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur

    def xmany(self, fn):
        """fn(conn) をトランザクション内で実行"""
        with self.lock:
            try:
                r = fn(self.conn)
                self.conn.commit()
                return r
            except Exception:
                self.conn.rollback()
                raise


DBH = None  # type: DB


def gen_key():
    return secrets.token_hex(8)  # 16文字（Ambient と同じ長さ）


def default_fields():
    return {f: {"name": f, "unit": "", "color": DEFAULT_COLORS[i], "show": i == 0, "chart": i + 1}
            for i, f in enumerate(FIELDS)}


def load_fields(raw):
    base = default_fields()
    try:
        user = json.loads(raw or "{}")
    except ValueError:
        user = {}
    for f in FIELDS:
        if isinstance(user.get(f), dict):
            base[f].update({k: v for k, v in user[f].items() if k in base[f]})
    return base


def create_channel(name, description="", is_public=True, fields=None, owner_id=None):
    now = int(time.time() * 1000)
    cur = DBH.x("INSERT INTO channels(name, description, write_key, read_key, is_public, fields, created_at, owner_id) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (name, description, gen_key(), gen_key(), 1 if is_public else 0,
                 json.dumps(fields or default_fields(), ensure_ascii=False), now, owner_id))
    return get_channel(cur.lastrowid)


def get_channel(cid):
    return DBH.q("SELECT * FROM channels WHERE id=?", (cid,), one=True)


def channel_public_info(ch, with_keys=False):
    info = {
        "ch": str(ch["id"]),
        "chId": ch["id"],
        "name": ch["name"],
        "description": ch["description"],
        "public": bool(ch["is_public"]),
        "fields": load_fields(ch["fields"]),
        "created": iso(ch["created_at"]),
        "lastpost": iso(ch["last_post"]) if ch["last_post"] else None,
        "ownerId": ch["owner_id"],
    }
    # Ambient の getprop と似た形 (d1: {name, color}) も付けておく
    for f, v in info["fields"].items():
        info[f] = {"name": v["name"], "color": v["color"]}
    if with_keys:
        info["writeKey"] = ch["write_key"]
        info["readKey"] = ch["read_key"]
    return info


# ---------------------------------------------------------------- time helpers
def iso(ms):
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (int(ms) % 1000)


_LOCAL_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{1,2})(?::(\d{1,2})(?:\.(\d{1,6}))?)?)?$")


def parse_time(v, now_ms):
    """created の解釈。数値=UNIX時刻(秒/ミリ秒)、文字列=ISO8601 か "YYYY-MM-DD HH:mm:ss.sss"(ローカル時刻)"""
    if v is None or v == "":
        return now_ms
    if isinstance(v, (int, float)) or (isinstance(v, str) and re.fullmatch(r"-?\d+(\.\d+)?", v.strip())):
        n = float(v)
        if n < 0:  # 負数: 現在からの相対ミリ秒（例: -60000 = 1分前）
            return int(now_ms + n)
        return int(n if n > 1e11 else n * 1000)
    s = str(v).strip()
    m = _LOCAL_RE.match(s)
    if m:
        y, mo, d, hh, mi, ss, frac = m.groups()
        dt = datetime(int(y), int(mo), int(d), int(hh or 0), int(mi or 0), int(ss or 0),
                      int((frac or "0").ljust(6, "0")[:6]), tzinfo=local_tz())
        return int(dt.timestamp() * 1000)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=local_tz())
        return int(dt.timestamp() * 1000)
    except ValueError:
        raise ValueError("created の形式が不正です: %s" % s)


def to_num(v):
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


# ---------------------------------------------------------------- data ops


def insert_rows(ch, items, limit=True):
    """limit=True なら最短送信間隔（CFG.min_interval）をチェックする。
    チェックと受信時刻の更新を同じトランザクションで行うので、同時に届いても二重には通らない"""
    now = int(time.time() * 1000)
    rows = []
    for it in items:
        if not isinstance(it, dict):
            raise ValueError("data の要素はオブジェクトである必要があります")
        created = parse_time(it.get("created"), now)
        vals = [to_num(it.get(f)) for f in FIELDS]
        lat, lng = to_num(it.get("lat")), to_num(it.get("lng"))
        cmnt = it.get("cmnt")
        cmnt = str(cmnt)[:256] if cmnt not in (None, "") else None
        if all(v is None for v in vals) and lat is None and lng is None and cmnt is None:
            continue
        rows.append((ch["id"], created, *vals, lat, lng, cmnt))
    if not rows:
        return 0

    def tx(conn):
        if limit and CFG.min_interval > 0:
            gap = int(CFG.min_interval * 1000)
            cur = conn.execute("UPDATE channels SET last_post=? WHERE id=? AND (last_post IS NULL OR last_post<=?)",
                               (now, ch["id"], now - gap))
            if cur.rowcount == 0:
                last = conn.execute("SELECT last_post FROM channels WHERE id=?", (ch["id"],)).fetchone()[0] or now
                raise RateLimited((last + gap - now) / 1000)
        conn.executemany("INSERT INTO data(channel_id, created, d1,d2,d3,d4,d5,d6,d7,d8, lat,lng,cmnt) "
                         "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        conn.execute("UPDATE channels SET last_post=? WHERE id=?", (now, ch["id"]))
        # 設定をまだ一度も保存していないチャネルでは、データが来たフィールドを自動でグラフ表示にする
        raw = conn.execute("SELECT fields FROM channels WHERE id=?", (ch["id"],)).fetchone()[0]
        try:
            fj = json.loads(raw or "{}")
        except ValueError:
            fj = {}
        if fj.get("_auto", True):
            cur_f = load_fields(raw)
            changed = False
            for i, f in enumerate(FIELDS):
                if not cur_f[f]["show"] and any(r[2 + i] is not None for r in rows):
                    cur_f[f]["show"] = True
                    changed = True
            if changed:
                cur_f["_auto"] = True
                conn.execute("UPDATE channels SET fields=? WHERE id=?",
                             (json.dumps(cur_f, ensure_ascii=False), ch["id"]))
        cnt = conn.execute("SELECT COUNT(*) FROM data WHERE channel_id=?", (ch["id"],)).fetchone()[0]
        if cnt > CFG.max_rows:
            conn.execute("DELETE FROM data WHERE id IN (SELECT id FROM data WHERE channel_id=? "
                         "ORDER BY created ASC, id ASC LIMIT ?)", (ch["id"], cnt - CFG.max_rows))
        return len(rows)

    if CFG.journal_mode.upper() != "WAL":
        # CGI では複数プロセスが同時に書くので、先に書き込みロックを取る
        def tx_locked(conn):
            conn.execute("BEGIN IMMEDIATE")
            return tx(conn)
        fn = tx_locked
    else:
        fn = tx
    try:
        return DBH.xmany(fn)
    except RateLimited as e:
        raise _rate_error(e.wait)


def row_to_json(r):
    o = {"created": iso(r["created"])}
    for f in FIELDS:
        if r[f] is not None:
            o[f] = r[f]
    if r["lat"] is not None:
        o["lat"] = r["lat"]
    if r["lng"] is not None:
        o["lng"] = r["lng"]
    if r["cmnt"]:
        o["cmnt"] = r["cmnt"]
    return o


def local_day_range(date_str):
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", date_str.strip())
    if not m:
        raise ValueError("date は YYYY-MM-DD 形式で指定してください")
    start = datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=local_tz())
    return int(start.timestamp() * 1000), int((start + timedelta(days=1)).timestamp() * 1000)


def query_data(ch, params):
    """Ambient の GET /data と同じパラメーター + 拡張 (after=ミリ秒, limit)"""
    p = {k: v[0] for k, v in params.items()}
    now = int(time.time() * 1000)
    where, args = ["channel_id=?", "hide=0"], [ch["id"]]
    limit, offset = None, 0
    if "date" in p:
        s, e = local_day_range(p["date"])
        where += ["created>=?", "created<?"]
        args += [s, e]
    elif "start" in p and "end" in p:
        where += ["created>=?", "created<=?"]
        args += [parse_time(p["start"], now), parse_time(p["end"], now)]
    elif "after" in p:  # 画面の差分更新用（拡張）
        where.append("created>?")
        args.append(int(float(p["after"])))
    else:
        limit = max(1, min(int(p.get("n", 1)), 100000))
        offset = max(0, int(p.get("skip", 0)))
    if limit is None:
        limit = max(1, min(int(p.get("limit", 100000)), 100000))
    sql = "SELECT * FROM data WHERE %s ORDER BY created DESC, id DESC LIMIT ? OFFSET ?" % " AND ".join(where)
    rows = DBH.q(sql, (*args, limit, offset))
    return [row_to_json(r) for r in rows]


# ---------------------------------------------------------------- HTTP
class ApiError(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status = status
        self.msg = msg


MIME = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
        ".ico": "image/x-icon", ".json": "application/json", ".txt": "text/plain; charset=utf-8"}

ROUTES = []


def route(method, pattern):
    rx = re.compile("^" + pattern + "$")

    def deco(fn):
        ROUTES.append((method, rx, fn))
        return fn
    return deco


class Handler(BaseHTTPRequestHandler):
    server_version = "MiniBient/" + VERSION
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s - %s\n" % (datetime.now().strftime("%H:%M:%S"),
                                           self.client_address[0], fmt % args))

    # --- helpers
    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in getattr(self, "_extra_headers", []):
            self.send_header(k, v)
        self.cors()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_text(self, text, status=200, ctype="text/plain; charset=utf-8", extra=None):
        body = text.encode("utf-8") if isinstance(text, str) else text
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.cors()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Admin-Password, X-Write-Key")

    def _read_body(self):
        # keep-alive で次のリクエストが崩れないよう、ハンドラーが使わなくても必ず読み切る
        length = int(self.headers.get("Content-Length") or 0)
        if length > CFG.max_body:
            self.close_connection = True
            raise ApiError(413, "リクエストが大きすぎます")
        self._body = self.rfile.read(length) if length else b""

    def read_json(self):
        raw = self._body
        if not raw.strip():
            return {}
        try:
            # 末尾の \r\n や NUL が付いてくるマイコンもあるので除去
            return json.loads(raw.decode("utf-8", "replace").strip().strip("\x00"))
        except ValueError:
            raise ApiError(400, "JSON の形式が正しくありません")

    def is_admin(self):
        pw = (self.headers.get("X-Admin-Password", "") or "").strip()
        return bool(CFG.admin_password) and secrets.compare_digest(pw, CFG.admin_password)

    def require_admin(self):
        if not self.is_admin():
            raise ApiError(401, "管理パスワードが違います")

    def add_header(self, k, v):
        if not hasattr(self, "_extra_headers"):
            self._extra_headers = []
        self._extra_headers.append((k, v))

    def session_token(self):
        raw = self.headers.get("Cookie", "") or ""
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == SESSION_COOKIE and v:
                return v
        return ""

    def user(self):
        """ログイン中のユーザー（sqlite Row）。未ログインなら None"""
        if not hasattr(self, "_user"):
            self._user = session_user(self.session_token())
        return self._user

    def require_user(self):
        u = self.user()
        if u is None:
            raise ApiError(401, "ログインしてください")
        # Cookie で認証する書き込みは JSON の送信に限る（他サイトからのフォーム送信を防ぐ）
        if self.command != "GET" and not (self.headers.get("Content-Type") or "").startswith("application/json"):
            raise ApiError(415, "Content-Type: application/json で送ってください")
        return u

    # --- dispatch
    def do_OPTIONS(self):
        self.send_response(204)
        self.cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self.dispatch("GET")

    def do_HEAD(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_PUT(self):
        self.dispatch("PUT")

    def do_DELETE(self):
        self.dispatch("DELETE")

    def dispatch(self, method):
        u = urlparse(self.path)
        path = u.path
        bp = CFG.base_path.rstrip("/")
        if bp and (path == bp or path.startswith(bp + "/")):
            path = path[len(bp):]
        path = path.rstrip("/") or "/"
        self.query = parse_qs(u.query, keep_blank_values=True)
        self._body = b""
        # keep-alive では同じ Handler が複数のリクエストを処理するので、リクエストごとの状態を消す
        self._extra_headers = []
        self.__dict__.pop("_user", None)
        try:
            if self.command in ("POST", "PUT", "DELETE"):
                self._read_body()
            for m, rx, fn in ROUTES:
                if m == method:
                    mt = rx.match(path)
                    if mt:
                        return fn(self, *mt.groups())
            if method == "GET":
                return self.serve_static(path)
            raise ApiError(404, "見つかりません")
        except ApiError as e:
            self.send_json({"error": e.msg}, e.status)
        except ValueError as e:
            self.send_json({"error": str(e)}, 400)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # pragma: no cover
            import traceback
            traceback.print_exc()
            self.send_json({"error": "サーバー内部エラー: %s" % e}, 500)

    def serve_static(self, path):
        pages = {"/": "index.html", "/admin": "admin.html", "/login": "login.html",
                 "/me": "me.html", "/new": "me.html", "/guide": "guide.html"}
        m = re.fullmatch(r"/ch/(\d+)", path)
        if path in pages:
            rel = pages[path]
        elif m:
            rel = "channel.html"
        elif path.startswith("/static/"):
            rel = path[len("/static/"):]
        elif path == "/favicon.ico":
            rel = "favicon.svg"
        else:
            raise ApiError(404, "見つかりません")
        full = os.path.normpath(os.path.join(STATIC_DIR, rel))
        if not full.startswith(STATIC_DIR + os.sep) or not os.path.isfile(full):
            raise ApiError(404, "見つかりません")
        with open(full, "rb") as fp:
            body = fp.read()
        ext = os.path.splitext(full)[1].lower()
        if ext == ".html":
            # 画面内のリンクは相対パスなので、置き場所（サブフォルダー）を <base> で教える
            base = CFG.base_path.rstrip("/") + "/"
            body = body.replace(b"<head>", b'<head>\n<base href="' + base.encode("utf-8") + b'">', 1)
        cache = "public, max-age=86400" if rel.startswith("vendor/") else "no-cache"
        self.send_text(body, 200, MIME.get(ext, "application/octet-stream"), {"Cache-Control": cache})


# ---------------------------------------------------------------- Ambient compatible API
def _channel_or_404(cid):
    ch = get_channel(int(cid))
    if ch is None:
        raise ApiError(404, "チャネル %s は存在しません" % cid)
    return ch


def _check_write(h, ch, body):
    key = body.get("writeKey") or h.headers.get("X-Write-Key") or ""
    if not (secrets.compare_digest(str(key), ch["write_key"]) or h.is_admin()):
        raise ApiError(403, "writeKey が違います")


def _check_read(h, ch):
    if ch["is_public"] or h.is_admin() or _owns(h, ch):
        return
    key = (h.query.get("readKey") or [""])[0]
    wkey = (h.query.get("writeKey") or [""])[0]
    if secrets.compare_digest(key, ch["read_key"]) or (wkey and secrets.compare_digest(wkey, ch["write_key"])):
        return
    raise ApiError(403, "このチャネルは非公開です。readKey を指定してください")


class RateLimited(Exception):
    def __init__(self, wait):
        super().__init__(wait)
        self.wait = wait


def _rate_error(wait):
    return ApiError(429, "前回の受信から %g 秒たっていないため受け付けませんでした（あと %d 秒）"
                    % (CFG.min_interval, max(1, int(wait + 0.999))))


@route("POST", r"/api/v2/channels/(\d+)/data")
def api_post_data(h, cid):
    ch = _channel_or_404(cid)
    body = h.read_json()
    if not isinstance(body, dict):
        raise ApiError(400, "JSON オブジェクトを送ってください")
    _check_write(h, ch, body)
    # {"writeKey":..., "data":[...]} 形式で /data に送られた場合も受け付ける
    items = body["data"] if isinstance(body.get("data"), list) else [body]
    n = insert_rows(ch, items, limit=not h.is_admin())
    h.send_json({"status": "ok", "count": n})


@route("POST", r"/api/v2/channels/(\d+)/dataarray")
def api_post_dataarray(h, cid):
    ch = _channel_or_404(cid)
    body = h.read_json()
    if not isinstance(body, dict):
        raise ApiError(400, "JSON オブジェクトを送ってください")
    _check_write(h, ch, body)
    items = body.get("data")
    if not isinstance(items, list):
        raise ApiError(400, "data は配列である必要があります")
    if len(items) > 10000:
        raise ApiError(413, "一度に送れるのは 10000 件までです")
    n = insert_rows(ch, items, limit=not h.is_admin())
    h.send_json({"status": "ok", "count": n})


@route("GET", r"/api/v2/channels/(\d+)/data")
def api_get_data(h, cid):
    ch = _channel_or_404(cid)
    _check_read(h, ch)
    h.send_json(query_data(ch, h.query))


@route("PUT", r"/api/v2/channels/(\d+)/data")
def api_put_data(h, cid):
    """Ambient の putcmnt / sethide 互換: {"writeKey","created","cmnt"} or {"writeKey","created","hide"}"""
    ch = _channel_or_404(cid)
    body = h.read_json()
    _check_write(h, ch, body)
    t = parse_time(body.get("created"), 0)
    if "cmnt" in body:
        cur = DBH.x("UPDATE data SET cmnt=? WHERE channel_id=? AND created=?", (str(body["cmnt"])[:256], ch["id"], t))
    elif "hide" in body:
        cur = DBH.x("UPDATE data SET hide=? WHERE channel_id=? AND created=?", (1 if body["hide"] else 0, ch["id"], t))
    else:
        raise ApiError(400, "cmnt または hide を指定してください")
    h.send_json({"status": "ok", "count": cur.rowcount})


@route("DELETE", r"/api/v2/channels/(\d+)/data")
def api_delete_data(h, cid):
    """全データ削除。writeKey（クエリ or ヘッダー）か管理パスワードが必要"""
    ch = _channel_or_404(cid)
    key = (h.query.get("writeKey") or h.query.get("userKey") or [""])[0] or h.headers.get("X-Write-Key", "")
    if _owns(h, ch):
        h.require_user()
    elif not (h.is_admin() or (key and secrets.compare_digest(key, ch["write_key"]))):
        raise ApiError(403, "writeKey が違います")
    cur = DBH.x("DELETE FROM data WHERE channel_id=?", (ch["id"],))
    h.send_json({"status": "ok", "deleted": cur.rowcount})


@route("GET", r"/api/v2/channels/(\d+)")
def api_get_channel(h, cid):
    ch = _channel_or_404(cid)
    _check_read(h, ch)
    info = channel_public_info(ch)
    info["dataperday"] = DBH.q("SELECT COUNT(*) FROM data WHERE channel_id=? AND created>?",
                               (ch["id"], int(time.time() * 1000) - 86400000), one=True)[0]
    info["total"] = DBH.q("SELECT COUNT(*) FROM data WHERE channel_id=?", (ch["id"],), one=True)[0]
    h.send_json(info)


# ---------------------------------------------------------------- UI / management API
@route("GET", r"/api/ui/info")
def ui_info(h):
    u = h.user()
    h.send_json({"version": VERSION, "registration": CFG.registration, "tzOffset": CFG.tz_offset,
                 "user": user_info(u) if u else None, "maxChannels": CFG.max_channels,
                 "serverTime": iso(int(time.time() * 1000)), "minInterval": CFG.min_interval,
                 "basePath": CFG.base_path.rstrip("/"), "preferHttps": CFG.prefer_https})


@route("GET", r"/api/ui/overview")
def ui_overview(h):
    """公開チャネル一覧 + 最新値 + 先頭の表示フィールドの直近の推移（スパークライン用）"""
    admin = h.is_admin()
    chans = DBH.q("SELECT * FROM channels %s ORDER BY id" % ("" if admin else "WHERE is_public=1"))
    spark_n = max(2, min(int((h.query.get("spark") or ["60"])[0]), 500))
    out = []
    for ch in chans:
        info = channel_public_info(ch)
        latest = DBH.q("SELECT * FROM data WHERE channel_id=? AND hide=0 ORDER BY created DESC, id DESC LIMIT 1",
                       (ch["id"],), one=True)
        info["latest"] = row_to_json(latest) if latest else None
        fields = info["fields"]
        shown = [f for f in FIELDS if fields[f]["show"]] or ["d1"]
        sf = shown[0]
        rows = DBH.q("SELECT created, %s FROM data WHERE channel_id=? AND hide=0 AND %s IS NOT NULL "
                     "ORDER BY created DESC, id DESC LIMIT ?" % (sf, sf), (ch["id"], spark_n))
        info["spark"] = {"field": sf, "points": [[r[0], r[1]] for r in reversed(rows)]}
        out.append(info)
    h.send_json(out)


def _owns(h, ch):
    u = h.user()
    return u is not None and ch["owner_id"] is not None and u["id"] == ch["owner_id"]


def _check_owner(h, ch, body=None):
    if _owns(h, ch):
        h.require_user()  # CSRF 対策のチェック
        return
    key = (body or {}).get("writeKey") or h.headers.get("X-Write-Key", "")
    if not (h.is_admin() or (key and secrets.compare_digest(str(key), ch["write_key"]))):
        raise ApiError(403, "ライトキーが違います（持ち主の方はログインしてください）")


def _apply_settings(ch, body):
    name = str(body.get("name", ch["name"]))[:64].strip() or ch["name"]
    desc = str(body.get("description", ch["description"]))[:500]
    pub = ch["is_public"] if "public" not in body else (1 if body["public"] else 0)
    fields = load_fields(ch["fields"])
    if isinstance(body.get("fields"), dict):
        for f in FIELDS:
            v = body["fields"].get(f)
            if isinstance(v, dict):
                if "name" in v:
                    fields[f]["name"] = str(v["name"])[:32] or f
                if "unit" in v:
                    fields[f]["unit"] = str(v["unit"])[:16]
                if "color" in v and re.fullmatch(r"#[0-9a-fA-F]{6}", str(v["color"])):
                    fields[f]["color"] = v["color"]
                if "show" in v:
                    fields[f]["show"] = bool(v["show"])
                if "chart" in v:
                    try:
                        fields[f]["chart"] = max(1, min(8, int(v["chart"])))
                    except (TypeError, ValueError):
                        pass
    fields["_auto"] = False  # 利用者が設定したので以後は自動表示しない
    DBH.x("UPDATE channels SET name=?, description=?, is_public=?, fields=? WHERE id=?",
          (name, desc, pub, json.dumps(fields, ensure_ascii=False), ch["id"]))


@route("POST", r"/api/ui/channels/(\d+)/verify")
def ui_verify(h, cid):
    ch = _channel_or_404(cid)
    body = h.read_json()
    _check_owner(h, ch, body)
    h.send_json(channel_public_info(ch, with_keys=True))


@route("PUT", r"/api/ui/channels/(\d+)")
def ui_update_channel(h, cid):
    ch = _channel_or_404(cid)
    body = h.read_json()
    _check_owner(h, ch, body)
    _apply_settings(ch, body)
    h.send_json(channel_public_info(get_channel(ch["id"])))


@route("POST", r"/api/ui/channels/(\d+)/regenerate")
def ui_regen(h, cid):
    ch = _channel_or_404(cid)
    body = h.read_json()
    _check_owner(h, ch, body)
    which = body.get("which", "read")
    col = {"read": "read_key", "write": "write_key"}.get(which)
    if not col:
        raise ApiError(400, "which は read か write")
    DBH.x("UPDATE channels SET %s=? WHERE id=?" % col, (gen_key(), ch["id"]))
    h.send_json(channel_public_info(get_channel(ch["id"]), with_keys=True))


@route("GET", r"/api/ui/channels/(\d+)/csv")
def ui_csv(h, cid):
    ch = _channel_or_404(cid)
    _check_read(h, ch)
    q = dict(h.query)
    if not any(k in q for k in ("date", "start", "after", "n")):
        q["n"] = ["100000"]
    rows = list(reversed(query_data(ch, q)))
    fields = load_fields(ch["fields"])
    tz = local_tz()
    lines = ["created(local),created(UTC)," + ",".join('"%s"' % fields[f]["name"].replace('"', "'") for f in FIELDS)
             + ",lat,lng,cmnt"]
    for r in rows:
        t = datetime.fromisoformat(r["created"].replace("Z", "+00:00"))
        cells = [t.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S"), r["created"]]
        cells += ["" if r.get(f) is None else repr(r[f]) for f in FIELDS]
        cells += ["" if r.get(k) is None else str(r[k]) for k in ("lat", "lng")]
        cells.append('"%s"' % (r.get("cmnt") or "").replace('"', "'"))
        lines.append(",".join(cells))
    fname = "channel_%s_%s.csv" % (ch["id"], datetime.now(tz).strftime("%Y%m%d_%H%M"))
    h.send_text("﻿" + "\r\n".join(lines) + "\r\n", 200, "text/csv; charset=utf-8",
                {"Content-Disposition": 'attachment; filename="%s"' % fname})


# ---- admin
@route("POST", r"/api/admin/login")
def admin_login(h):
    h.require_admin()
    h.send_json({"status": "ok"})


@route("GET", r"/api/admin/channels")
def admin_list(h):
    h.require_admin()
    chans = DBH.q("SELECT c.*, (SELECT COUNT(*) FROM data d WHERE d.channel_id=c.id) AS total, "
                  "u.username AS owner_name FROM channels c LEFT JOIN users u ON u.id=c.owner_id ORDER BY c.id")
    out = []
    for ch in chans:
        info = channel_public_info(ch, with_keys=True)
        info["total"] = ch["total"]
        info["ownerName"] = ch["owner_name"]
        out.append(info)
    h.send_json(out)


@route("POST", r"/api/admin/channels")
def admin_create(h):
    """{"count": 30, "prefix": "受講者", "start": 1, "public": true, "fields": {...}} で一括作成"""
    h.require_admin()
    body = h.read_json()
    count = max(1, min(int(body.get("count", 1)), 200))
    prefix = str(body.get("prefix", "チャネル"))[:48]
    start = int(body.get("start", 1))
    width = max(2, len(str(start + count - 1)))
    fields = default_fields()
    if isinstance(body.get("fields"), dict):
        for f in FIELDS:
            v = body["fields"].get(f)
            if isinstance(v, dict):
                fields[f].update({k: v[k] for k in ("name", "unit", "show", "color", "chart") if k in v})
    created = []
    for i in range(count):
        name = prefix if count == 1 and not body.get("numbered") else "%s%0*d" % (prefix, width, start + i)
        ch = create_channel(name, str(body.get("description", ""))[:500], bool(body.get("public", True)), fields)
        created.append(channel_public_info(ch, with_keys=True))
    h.send_json(created)


@route("DELETE", r"/api/admin/channels/(\d+)")
def admin_delete(h, cid):
    h.require_admin()
    ch = _channel_or_404(cid)
    DBH.xmany(lambda c: (c.execute("DELETE FROM data WHERE channel_id=?", (ch["id"],)),
                         c.execute("DELETE FROM channels WHERE id=?", (ch["id"],))))
    h.send_json({"status": "ok"})


@route("GET", r"/api/admin/keys.csv")
def admin_keys_csv(h):
    # ブラウザのダウンロードリンク用に ?pw= も受け付ける
    pw = (h.query.get("pw") or [""])[0]
    if not (h.is_admin() or (CFG.admin_password and secrets.compare_digest(pw, CFG.admin_password))):
        raise ApiError(401, "管理パスワードが違います")
    lines = ["channelId,name,writeKey,readKey,public"]
    for ch in DBH.q("SELECT * FROM channels ORDER BY id"):
        lines.append('%d,"%s",%s,%s,%d' % (ch["id"], ch["name"].replace('"', "'"), ch["write_key"], ch["read_key"], ch["is_public"]))
    h.send_text("﻿" + "\r\n".join(lines) + "\r\n", 200, "text/csv; charset=utf-8",
                {"Content-Disposition": 'attachment; filename="minibient_keys.csv"'})



# ---------------------------------------------------------------- users / login
SESSION_COOKIE = "mb_session"
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,32}$")
PBKDF2_ITER = 120_000


def hash_password(pw):
    import hashlib
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, PBKDF2_ITER)
    return "pbkdf2_sha256$%d$%s$%s" % (PBKDF2_ITER, salt.hex(), dk.hex())


def verify_password(pw, stored):
    import hashlib
    try:
        algo, it, salt, dk = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(salt), int(it))
        return secrets.compare_digest(calc.hex(), dk)
    except (ValueError, TypeError):
        return False


def _token_hash(token):
    import hashlib
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_user(token):
    if not token or len(token) > 200:
        return None
    now = int(time.time() * 1000)
    return DBH.q("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id "
                 "WHERE s.token_hash=? AND s.expires>?", (_token_hash(token), now), one=True)


def user_info(u):
    return {"id": u["id"], "username": u["username"], "displayName": u["display_name"] or u["username"],
            "mustChangePassword": bool(u["must_change"])}


def get_setting(key, default=None):
    r = DBH.q("SELECT value FROM settings WHERE key=?", (key,), one=True)
    return r[0] if r else default


def set_setting(key, value):
    DBH.x("INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", (key, value))


def new_invite_code():
    # 読み間違えやすい文字（0/O, 1/l/I）を除いた8文字
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


def invite_code():
    if CFG.invite_code:
        return CFG.invite_code
    code = get_setting("invite_code")
    if not code:
        code = new_invite_code()
        set_setting("invite_code", code)
    return code


def _is_https(h):
    env = getattr(h, "environ", {}) or {}
    return (str(env.get("HTTPS", "")).lower() == "on"
            or str(env.get("REQUEST_SCHEME", "")).lower() == "https"
            or str(env.get("SERVER_PORT", "")) == "443"
            or (h.headers.get("X-Forwarded-Proto") or "").lower() == "https"
            # さくらのレンタルサーバーの共有SSL/SNI SSL では HTTPS が渡らず、このヘッダーが付く
            or bool(h.headers.get("X-Sakura-Forwarded-For")))


def _set_session_cookie(h, token, max_age):
    path = (CFG.base_path.rstrip("/") or "") + "/"
    cookie = "%s=%s; Path=%s; Max-Age=%d; HttpOnly; SameSite=Lax" % (SESSION_COOKIE, token, path, max_age)
    if _is_https(h):
        cookie += "; Secure"
    h.add_header("Set-Cookie", cookie)


def start_session(h, user_id):
    token = secrets.token_urlsafe(32)
    now = int(time.time() * 1000)
    expires = now + CFG.session_days * 86400000
    DBH.xmany(lambda c: (c.execute("DELETE FROM sessions WHERE expires<?", (now,)),
                         c.execute("INSERT INTO sessions(token_hash, user_id, expires) VALUES(?,?,?)",
                                   (_token_hash(token), user_id, expires)),
                         c.execute("UPDATE users SET last_login=?, failed=0 WHERE id=?", (now, user_id))))
    _set_session_cookie(h, token, CFG.session_days * 86400)


def _check_password_rule(pw):
    if not isinstance(pw, str) or len(pw) < 8:
        raise ApiError(400, "パスワードは8文字以上にしてください")
    if len(pw) > 128:
        raise ApiError(400, "パスワードが長すぎます")


def my_channels(user_id):
    rows = DBH.q("SELECT c.*, (SELECT COUNT(*) FROM data d WHERE d.channel_id=c.id) AS total "
                 "FROM channels c WHERE owner_id=? ORDER BY id", (user_id,))
    out = []
    for ch in rows:
        info = channel_public_info(ch, with_keys=True)
        info["total"] = ch["total"]
        out.append(info)
    return out


@route("POST", r"/api/auth/register")
def auth_register(h):
    if CFG.registration == "closed":
        raise ApiError(403, "現在、新しいユーザー登録は受け付けていません")
    body = h.read_json()
    if not (h.headers.get("Content-Type") or "").startswith("application/json"):
        raise ApiError(415, "Content-Type: application/json で送ってください")
    if CFG.registration == "invite":
        code = str(body.get("inviteCode", "")).strip().lower()
        if not code or not secrets.compare_digest(code, invite_code().lower()):
            raise ApiError(403, "招待コードが違います")
    username = str(body.get("username", "")).strip()
    if not USERNAME_RE.match(username):
        raise ApiError(400, "ユーザー名は半角英数字と _ - . で3〜32文字にしてください")
    password = body.get("password", "")
    _check_password_rule(password)
    display = str(body.get("displayName", "")).strip()[:32]
    if DBH.q("SELECT 1 FROM users WHERE username=?", (username,), one=True):
        raise ApiError(409, "そのユーザー名はすでに使われています")
    try:
        cur = DBH.x("INSERT INTO users(username, display_name, pw_hash, created_at) VALUES(?,?,?,?)",
                    (username, display, hash_password(password), int(time.time() * 1000)))
    except sqlite3.IntegrityError:
        raise ApiError(409, "そのユーザー名はすでに使われています")
    start_session(h, cur.lastrowid)
    u = DBH.q("SELECT * FROM users WHERE id=?", (cur.lastrowid,), one=True)
    h.send_json({"user": user_info(u), "channels": []})


@route("POST", r"/api/auth/login")
def auth_login(h):
    body = h.read_json()
    if not (h.headers.get("Content-Type") or "").startswith("application/json"):
        raise ApiError(415, "Content-Type: application/json で送ってください")
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", ""))
    u = DBH.q("SELECT * FROM users WHERE username=?", (username,), one=True)
    now = int(time.time() * 1000)
    if u and u["locked_until"] > now:
        raise ApiError(429, "ログインの失敗が続いたため、%d分ほど待ってからやり直してください"
                       % max(1, (u["locked_until"] - now) // 60000 + 1))
    if not u or not verify_password(password, u["pw_hash"]):
        if u:
            failed = u["failed"] + 1
            locked = now + 10 * 60000 if failed >= 10 else 0
            DBH.x("UPDATE users SET failed=?, locked_until=? WHERE id=?", (0 if locked else failed, locked, u["id"]))
        time.sleep(0.3)
        raise ApiError(401, "ユーザー名かパスワードが違います")
    start_session(h, u["id"])
    h.send_json({"user": user_info(u), "channels": my_channels(u["id"])})


@route("POST", r"/api/auth/logout")
def auth_logout(h):
    token = h.session_token()
    if token:
        DBH.x("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))
    _set_session_cookie(h, "", 0)
    h.send_json({"status": "ok"})


@route("GET", r"/api/auth/me")
def auth_me(h):
    u = h.user()
    if u is None:
        raise ApiError(401, "ログインしていません")
    h.send_json({"user": user_info(u), "channels": my_channels(u["id"]), "maxChannels": CFG.max_channels})


@route("POST", r"/api/auth/password")
def auth_password(h):
    u = h.require_user()
    body = h.read_json()
    if not verify_password(str(body.get("current", "")), u["pw_hash"]):
        raise ApiError(403, "今のパスワードが違います")
    new = body.get("new", "")
    _check_password_rule(new)
    token_hash = _token_hash(h.session_token())
    # 他の端末のログインは切る（この端末はそのまま）
    DBH.xmany(lambda c: (c.execute("UPDATE users SET pw_hash=?, must_change=0 WHERE id=?", (hash_password(new), u["id"])),
                         c.execute("DELETE FROM sessions WHERE user_id=? AND token_hash<>?", (u["id"], token_hash))))
    h.send_json({"status": "ok"})


@route("POST", r"/api/me/channels")
def me_create_channel(h):
    u = h.require_user()
    body = h.read_json()
    cnt = DBH.q("SELECT COUNT(*) FROM channels WHERE owner_id=?", (u["id"],), one=True)[0]
    if cnt >= CFG.max_channels:
        raise ApiError(403, "チャネルは1人 %d 個までです" % CFG.max_channels)
    name = str(body.get("name", "")).strip()[:64] or ((u["display_name"] or u["username"]) + "のチャネル")
    ch = create_channel(name, str(body.get("description", ""))[:500], bool(body.get("public", True)), owner_id=u["id"])
    h.send_json(channel_public_info(ch, with_keys=True))


@route("POST", r"/api/me/claim")
def me_claim_channel(h):
    """配布されたキーカードのチャネルを自分のアカウントに追加する: {"channelId", "writeKey"}"""
    u = h.require_user()
    body = h.read_json()
    try:
        cid = int(str(body.get("channelId", "")).strip())
    except ValueError:
        raise ApiError(400, "チャネルIDは数字で入力してください")
    ch = get_channel(cid)
    key = str(body.get("writeKey", "")).strip()
    if ch is None or not key or not secrets.compare_digest(key, ch["write_key"]):
        raise ApiError(403, "チャネルIDかライトキーが違います")
    if ch["owner_id"] == u["id"]:
        raise ApiError(409, "このチャネルはすでにあなたのアカウントに入っています")
    if ch["owner_id"] is not None:
        raise ApiError(409, "このチャネルは別のユーザーのアカウントに入っています。講師に連絡してください")
    cnt = DBH.q("SELECT COUNT(*) FROM channels WHERE owner_id=?", (u["id"],), one=True)[0]
    if cnt >= CFG.max_channels:
        raise ApiError(403, "チャネルは1人 %d 個までです" % CFG.max_channels)
    DBH.x("UPDATE channels SET owner_id=? WHERE id=? AND owner_id IS NULL", (u["id"], ch["id"]))
    h.send_json(channel_public_info(get_channel(ch["id"]), with_keys=True))


@route("DELETE", r"/api/me/channels/(\d+)")
def me_delete_channel(h, cid):
    u = h.require_user()
    ch = _channel_or_404(cid)
    if ch["owner_id"] != u["id"]:
        raise ApiError(403, "自分のチャネルだけ削除できます")
    DBH.xmany(lambda c: (c.execute("DELETE FROM data WHERE channel_id=?", (ch["id"],)),
                         c.execute("DELETE FROM channels WHERE id=?", (ch["id"],))))
    h.send_json({"status": "ok"})


# ---- admin: users
@route("GET", r"/api/admin/users")
def admin_users(h):
    h.require_admin()
    rows = DBH.q("SELECT u.*, (SELECT COUNT(*) FROM channels c WHERE c.owner_id=u.id) AS nch FROM users u ORDER BY u.id")
    h.send_json([{"id": r["id"], "username": r["username"], "displayName": r["display_name"],
                  "channels": r["nch"], "created": iso(r["created_at"]),
                  "lastLogin": iso(r["last_login"]) if r["last_login"] else None,
                  "mustChangePassword": bool(r["must_change"])} for r in rows])


@route("POST", r"/api/admin/users/(\d+)/reset")
def admin_reset_password(h, uid):
    """仮パスワードを発行（ログイン中の端末はすべてログアウト）"""
    h.require_admin()
    u = DBH.q("SELECT * FROM users WHERE id=?", (int(uid),), one=True)
    if u is None:
        raise ApiError(404, "ユーザーが見つかりません")
    temp = new_invite_code() + new_invite_code()[:2]
    DBH.xmany(lambda c: (c.execute("UPDATE users SET pw_hash=?, must_change=1, failed=0, locked_until=0 WHERE id=?",
                                   (hash_password(temp), u["id"])),
                         c.execute("DELETE FROM sessions WHERE user_id=?", (u["id"],))))
    h.send_json({"username": u["username"], "tempPassword": temp})


@route("DELETE", r"/api/admin/users/(\d+)")
def admin_delete_user(h, uid):
    """ユーザーを削除。持っていたチャネルとデータは残し、持ち主なしにする"""
    h.require_admin()
    uid = int(uid)
    DBH.xmany(lambda c: (c.execute("UPDATE channels SET owner_id=NULL WHERE owner_id=?", (uid,)),
                         c.execute("DELETE FROM sessions WHERE user_id=?", (uid,)),
                         c.execute("DELETE FROM users WHERE id=?", (uid,))))
    h.send_json({"status": "ok"})


@route("PUT", r"/api/admin/channels/(\d+)/owner")
def admin_set_owner(h, cid):
    """{"username": "taro"} で持ち主を変更、{"username": ""} で持ち主なし"""
    h.require_admin()
    ch = _channel_or_404(cid)
    body = h.read_json()
    name = str(body.get("username") or "").strip()
    if name:
        u = DBH.q("SELECT id FROM users WHERE username=?", (name,), one=True)
        if u is None:
            raise ApiError(404, "ユーザー %s は存在しません" % name)
        owner = u["id"]
    else:
        owner = None
    DBH.x("UPDATE channels SET owner_id=? WHERE id=?", (owner, ch["id"]))
    h.send_json({"status": "ok"})


@route("GET", r"/api/admin/settings")
def admin_settings(h):
    h.require_admin()
    h.send_json({"registration": CFG.registration, "inviteCode": invite_code(),
                 "inviteFixed": bool(CFG.invite_code), "maxChannels": CFG.max_channels,
                 "minInterval": CFG.min_interval})


@route("POST", r"/api/admin/invite")
def admin_new_invite(h):
    h.require_admin()
    if CFG.invite_code:
        raise ApiError(409, "招待コードは設定ファイルで固定されています")
    code = new_invite_code()
    set_setting("invite_code", code)
    h.send_json({"inviteCode": code})


def _clean_pw(text):
    """パスワードファイルの中身から BOM・改行・前後の空白を取り除き、1行目だけを使う"""
    text = text.replace("\ufeff", "").strip()
    return text.splitlines()[0].strip() if text else ""


# ---------------------------------------------------------------- CGI mode (shared hosting)
class _CGIHeaders:
    """BaseHTTPRequestHandler.headers の代わり。CGI の環境変数から読む"""

    def __init__(self, environ):
        self.env = environ

    def get(self, name, default=None):
        key = name.upper().replace("-", "_")
        if key in ("CONTENT_LENGTH", "CONTENT_TYPE"):
            return self.env.get(key, default)
        return self.env.get("HTTP_" + key, default)


class CGIHandler(Handler):
    """1リクエスト = 1プロセスの CGI として Handler を動かす"""

    def __init__(self, environ, stdin, stdout):  # noqa: super().__init__ は呼ばない
        self.environ = environ
        self.command = environ.get("REQUEST_METHOD", "GET").upper()
        path = environ.get("PATH_INFO", "")
        if not path:
            # PATH_INFO が渡らない環境向け: 元の URL（REQUEST_URI）からフォルダー部分を除いて求める
            uri = environ.get("REQUEST_URI", "").split("?", 1)[0]
            script = environ.get("SCRIPT_NAME", "")
            bp = CFG.base_path.rstrip("/")
            if script and uri.startswith(script):
                uri = uri[len(script):]
            elif bp and (uri == bp or uri.startswith(bp + "/")):
                uri = uri[len(bp):]
            path = uri
        path = path or "/"
        qs = environ.get("QUERY_STRING", "")
        self.path = path + ("?" + qs if qs else "")
        self.headers = _CGIHeaders(environ)
        self.rfile = stdin
        self.wfile = stdout
        self.client_address = (environ.get("REMOTE_ADDR", "-"), 0)
        self.close_connection = True
        self._out = []

    def send_response(self, code, message=None):
        try:
            phrase = message or HTTPStatus(code).phrase
        except ValueError:
            phrase = ""
        self._out = ["Status: %d %s" % (code, phrase)]

    def send_header(self, key, value):
        self._out.append("%s: %s" % (key, value))

    def end_headers(self):
        self.wfile.write(("\r\n".join(self._out) + "\r\n\r\n").encode("latin-1", "replace"))
        self._out = []

    def log_message(self, fmt, *args):
        pass

    def handle_cgi(self):
        method = self.command
        if method == "OPTIONS":
            return self.do_OPTIONS()
        if method == "HEAD":
            return self.dispatch("GET")
        if method not in ("GET", "POST", "PUT", "DELETE"):
            return self.send_json({"error": "未対応のメソッドです"}, 405)
        return self.dispatch(method)


def run_cgi(data_dir=None, admin_password="", registration="invite", invite_code="", max_channels=3,
            tz_offset=9.0, prefer_https=False,
            max_rows=200_000, min_interval=25.0, base_path=None):
    """さくらのレンタルサーバーなど、CGI しか使えない環境向けの入口（index.cgi から呼ぶ）"""
    global DBH
    env = os.environ
    if base_path is None:
        # SCRIPT_NAME = "/minibient/index.cgi" → "/minibient"
        base_path = os.path.dirname(env.get("SCRIPT_NAME", "/index.cgi")).replace("\\", "/")
        if base_path in ("/", "."):
            base_path = ""
    CFG.base_path = base_path.rstrip("/")
    CFG.registration, CFG.invite_code, CFG.max_channels = registration, invite_code.strip(), max_channels
    CFG.prefer_https = bool(prefer_https)
    CFG.tz_offset = tz_offset
    CFG.max_rows, CFG.min_interval = max_rows, min_interval
    CFG.journal_mode = "DELETE"

    if not data_dir:
        data_dir = os.path.join(os.path.expanduser("~"), "minibient_data")
    os.makedirs(data_dir, mode=0o700, exist_ok=True)
    CFG.db = os.path.join(data_dir, "minibient.db")

    pw = admin_password
    pw_file = os.path.join(data_dir, "admin_password.txt")
    if not pw:
        if os.path.exists(pw_file):
            with open(pw_file, encoding="utf-8") as fp:
                pw = _clean_pw(fp.read())
        if not pw:
            pw = secrets.token_urlsafe(9)
            with open(pw_file, "w", encoding="utf-8") as fp:
                fp.write(pw + "\n")
            os.chmod(pw_file, 0o600)
    CFG.admin_password = _clean_pw(pw)

    out = sys.stdout.buffer
    try:
        DBH = DB(CFG.db)
    except Exception as e:  # 保存先に書き込めないなど
        body = json.dumps({"error": "データベースを開けません: %s (%s)" % (e, CFG.db)}, ensure_ascii=False).encode("utf-8")
        out.write(b"Status: 500 Internal Server Error\r\nContent-Type: application/json; charset=utf-8\r\n\r\n" + body)
        out.flush()
        return
    CGIHandler(env, sys.stdin.buffer, out).handle_cgi()
    out.flush()


# ---------------------------------------------------------------- main
def local_ips():
    import socket
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


def env_bool(name, default):
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def main():
    global DBH
    ap = argparse.ArgumentParser(description="MiniBient: Ambient 互換 IoT データ可視化サーバー")
    ap.add_argument("--host", default=os.environ.get("MB_HOST", CFG.host))
    ap.add_argument("--port", type=int, default=int(os.environ.get("MB_PORT", CFG.port)))
    ap.add_argument("--db", default=os.environ.get("MB_DB", CFG.db), help="SQLite ファイルのパス")
    ap.add_argument("--admin-password", default=os.environ.get("MB_ADMIN_PASSWORD", ""),
                    help="管理画面のパスワード（未指定なら admin_password.txt に保存/自動生成）")
    ap.add_argument("--registration", choices=["invite", "open", "closed"],
                    default=os.environ.get("MB_REGISTRATION", CFG.registration),
                    help="ユーザー登録: invite=招待コードが必要（既定） / open=誰でも / closed=受け付けない")
    ap.add_argument("--invite-code", default=os.environ.get("MB_INVITE_CODE", ""),
                    help="招待コードを固定する（未指定なら管理画面で表示・作り直しできる）")
    ap.add_argument("--prefer-https", action="store_true", default=env_bool("MB_PREFER_HTTPS", False),
                    help="https で公開している場合に指定。ブラウザーを https に切り替え、送信方法も https で案内する")
    ap.add_argument("--max-channels", type=int, default=int(os.environ.get("MB_MAX_CHANNELS", CFG.max_channels)),
                    help="1ユーザーが持てるチャネル数")
    ap.add_argument("--tz", type=float, default=float(os.environ.get("MB_TZ_OFFSET", CFG.tz_offset)),
                    help="時差（時間）。日本は 9")
    ap.add_argument("--max-rows", type=int, default=int(os.environ.get("MB_MAX_ROWS", CFG.max_rows)))
    ap.add_argument("--base-path", default=os.environ.get("MB_BASE_PATH", ""),
                    help="リバースプロキシでサブフォルダーに置く場合のURLの先頭（例 /minibient）")
    ap.add_argument("--min-interval", type=float, default=float(os.environ.get("MB_MIN_INTERVAL", CFG.min_interval)),
                    help="同じチャネルへの最短送信間隔（秒）")
    a = ap.parse_args()

    CFG.host, CFG.port, CFG.db = a.host, a.port, a.db
    CFG.registration, CFG.invite_code, CFG.max_channels = a.registration, a.invite_code.strip(), a.max_channels
    CFG.prefer_https = a.prefer_https
    CFG.tz_offset = a.tz
    CFG.max_rows, CFG.min_interval = a.max_rows, a.min_interval
    CFG.base_path = a.base_path.rstrip("/")

    pw = a.admin_password
    pw_file = os.path.join(os.path.dirname(os.path.abspath(CFG.db)), "admin_password.txt")
    if not pw:
        if os.path.exists(pw_file):
            with open(pw_file, encoding="utf-8", errors="replace") as fp:
                pw = _clean_pw(fp.read())
        if not pw:
            pw = secrets.token_urlsafe(9)
            with open(pw_file, "w", encoding="utf-8") as fp:
                fp.write(pw + "\n")
    CFG.admin_password = pw

    DBH = DB(CFG.db)
    httpd = ThreadingHTTPServer((CFG.host, CFG.port), Handler)
    httpd.daemon_threads = True

    print("=" * 60)
    print(" MiniBient %s  (Ambient 互換 IoT データ可視化サーバー)" % VERSION)
    print("=" * 60)
    print(" 画面      : http://localhost:%d/" % CFG.port)
    for ip in local_ips():
        print("            http://%s:%d/   ← M5StickC からはこのアドレス" % (ip, CFG.port))
    print(" 管理画面  : http://localhost:%d/admin" % CFG.port)
    print(" 管理パスワード: %s" % pw)
    if CFG.registration == "invite":
        print(" 招待コード    : %s   （受講者のユーザー登録に必要）" % invite_code())
    print(" DB        : %s" % os.path.abspath(CFG.db))
    print(" 停止は Ctrl+C")
    print("=" * 60)
    sys.stdout.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n停止しました")


if __name__ == "__main__":
    main()
