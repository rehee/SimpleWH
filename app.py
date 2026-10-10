import hashlib
import os
import re
import secrets
import psycopg
from psycopg.rows import dict_row
from psycopg import IsolationLevel
import time
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash


def create_app(config=None):
    app = Flask(__name__, static_folder="static")
    app.config.update(DATA_DIR=os.getenv("DATA_DIR", "data"),
                      ADMIN_USERNAME=os.getenv("ADMIN_USERNAME", "owner"),
                      ADMIN_PASSWORD=os.getenv("ADMIN_PASSWORD", ""),
                      COOKIE_SECURE=os.getenv("COOKIE_SECURE", "true").lower() == "true",
                      DATABASE_URL=os.getenv("DATABASE_URL", "postgresql://warehouse:warehouse@localhost:5432/warehouse"),
                      MAX_CONTENT_LENGTH=12 * 1024 * 1024)
    if config:
        app.config.update(config)
    Path(app.config["DATA_DIR"]).mkdir(parents=True, exist_ok=True)
    def connect():
        return psycopg.connect(app.config["DATABASE_URL"], row_factory=dict_row)

    with connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(771234)")
        db.execute(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
        if not db.execute("SELECT 1 FROM users WHERE role='owner'").fetchone():
            password = app.config["ADMIN_PASSWORD"]
            username = app.config["ADMIN_USERNAME"]
            if len(password) < 12 or not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username):
                raise RuntimeError("首次启动需设置主账号和至少 12 位密码")
            db.execute("INSERT INTO users(username,password,role) VALUES(%s,%s,'owner')",
                       (username, generate_password_hash(password)))
        if not db.execute("SELECT 1 FROM settings WHERE key='seeded'").fetchone():
            for name, kind, levels in [(n, 'rack', 6) for n in ['左1','左2','中1','中2','右1','右2']] + [('中3','rack',5),('柜1','cabinet',5),('柜2','cabinet',5)]:
                root = db.execute("INSERT INTO containers(name,kind,description) VALUES(%s,%s,%s) RETURNING id", (name,kind,'默认收纳设施')).fetchone()['id']
                for level in range(1, levels+1):
                    db.execute("INSERT INTO containers(name,kind,parent_id,level,description) VALUES(%s,'shelf',%s,%s,'默认层')", (f'第{level}层',root,level))
            db.execute("INSERT INTO settings VALUES('seeded','1')")
        # Upgrade databases initialized before the seventh rack was specified.
        # The marker preserves intentional deletions on subsequent restarts.
        if not db.execute("SELECT 1 FROM settings WHERE key='default_middle3_v1'").fetchone():
            if not db.execute("SELECT 1 FROM containers WHERE name='中3' AND kind='rack' AND parent_id IS NULL").fetchone():
                root = db.execute("INSERT INTO containers(name,kind,description) VALUES('中3','rack','默认收纳设施') RETURNING id").fetchone()['id']
                for level in range(1, 6):
                    db.execute("INSERT INTO containers(name,kind,parent_id,level,description) VALUES(%s,'shelf',%s,%s,'默认层')", (f'第{level}层',root,level))
            db.execute("INSERT INTO settings VALUES('default_middle3_v1','1')")

    @app.before_request
    def before():
        g.db = connect()
        if request.method in ("GET", "HEAD"):
            # Keep one snapshot while another user moves or deletes a container.
            g.db.isolation_level = IsolationLevel.REPEATABLE_READ
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            g.db.execute("SELECT pg_advisory_xact_lock(771235)")
        g.user = None
        g.session = None
        token = request.cookies.get("wh_session", "")
        if token:
            g.session = g.db.execute(
                "SELECT * FROM sessions WHERE token=%s AND expires>%s",
                (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
            if g.session:
                g.user = g.db.execute("SELECT id,username,role FROM users WHERE id=%s",
                                      (g.session["user_id"],)).fetchone()

    @app.teardown_request
    def teardown(error):
        if hasattr(g, "db"):
            g.db.close()

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.path.startswith(("/api/", "/photos/")):
            response.headers["Cache-Control"] = "no-store"
        return response

    def require(owner=False):
        def decorator(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                if not g.user:
                    return jsonify(error="请先登录"), 401
                if owner and g.user["role"] != "owner":
                    return jsonify(error="只有主用户可以管理成员"), 403
                if request.method not in ("GET", "HEAD") and not secrets.compare_digest(
                        request.headers.get("X-CSRF-Token", ""), g.session["csrf"]):
                    return jsonify(error="请求验证失败，请重新登录"), 403
                return fn(*args, **kwargs)
            return wrapped
        return decorator

    def body():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise ValueError("请输入有效数据")
        return value

    def field(data, name, label, limit=120, default=None):
        value = data.get(name, default)
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
            raise ValueError(f"{label}不能为空且不能超过 {limit} 字")
        return value.strip()

    def integer(value, label, minimum=0):
        if type(value) is not int or not minimum <= value <= 1000000:
            raise ValueError(f"{label}必须为 {minimum}–1000000 的整数")
        return value

    def now():
        return datetime.now(timezone.utc).isoformat()

    def log(name, action, detail):
        g.db.execute("INSERT INTO movements(item_name,action,detail,username,created_at) VALUES(%s,%s,%s,%s,%s)",
                     (name, action, detail, g.user["username"], now()))

    @app.errorhandler(ValueError)
    def invalid(error):
        g.db.rollback()
        return jsonify(error=str(error)), 400

    @app.errorhandler(psycopg.IntegrityError)
    def conflict(error):
        g.db.rollback()
        return jsonify(error="名称或库位重复，或记录仍有关联物品"), 409

    @app.errorhandler(413)
    def too_large(error):
        return jsonify(error="照片不能超过 12 MB"), 413

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/health")
    def health():
        g.db.execute("SELECT 1").fetchone()
        return jsonify(status="ok")

    @app.post("/api/login")
    def login():
        data = body()
        username = field(data, "username", "用户名", 32)
        password = field(data, "password", "密码", 256)
        # Bound both a single account and all attempts at the origin; IP headers are not trusted.
        keys = ["user:" + username, "global"]
        current = time.time()
        for key in keys:
            row = g.db.execute("SELECT * FROM login_attempts WHERE key=%s", (key,)).fetchone()
            if row and row["blocked_until"] > current:
                g.db.rollback()
                return jsonify(error="登录尝试过多，请 15 分钟后重试"), 429
        user = g.db.execute("SELECT * FROM users WHERE username=%s", (username,)).fetchone()
        if not check_password_hash(user["password"] if user else DUMMY_HASH, password):
            for key in keys:
                row = g.db.execute("SELECT * FROM login_attempts WHERE key=%s", (key,)).fetchone()
                failures = (row["failures"] if row and row["blocked_until"] > current - 900 else 0) + 1
                threshold = 10 if key != "global" else 100
                g.db.execute("INSERT INTO login_attempts VALUES(%s,%s,%s) ON CONFLICT(key) DO UPDATE SET failures=EXCLUDED.failures,blocked_until=EXCLUDED.blocked_until",
                             (key, failures, current + 900 if failures >= threshold else current))
            g.db.commit()
            return jsonify(error="用户名或密码错误"), 401
        g.db.execute("DELETE FROM login_attempts WHERE key=%s", (keys[0],))
        g.db.execute("DELETE FROM sessions WHERE expires<=%s", (current,))
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        g.db.execute("INSERT INTO sessions VALUES(%s,%s,%s,%s)",
                     (hashlib.sha256(token.encode()).hexdigest(), user["id"], csrf, current + 86400))
        g.db.commit()
        response = jsonify(user={k: user[k] for k in ("id", "username", "role")}, csrf=csrf)
        response.set_cookie("wh_session", token, httponly=True, secure=app.config["COOKIE_SECURE"],
                            samesite="Lax", max_age=86400)
        return response

    @app.get("/api/me")
    @require()
    def me():
        return jsonify(user=dict(g.user), csrf=g.session["csrf"])

    @app.post("/api/logout")
    @require()
    def logout():
        g.db.execute("DELETE FROM sessions WHERE token=%s", (g.session["token"],))
        g.db.commit()
        response = jsonify(ok=True)
        response.delete_cookie("wh_session", secure=app.config["COOKIE_SECURE"], samesite="Lax")
        return response

    from inventory import register_inventory
    register_inventory(app, require, body, field, integer, now, log)

    @app.get("/api/users")
    @require(owner=True)
    def users():
        return jsonify(users=[dict(r) for r in g.db.execute("SELECT id,username,role FROM users ORDER BY id")])

    @app.post("/api/users")
    @require(owner=True)
    def add_user():
        data = body()
        username = field(data, "username", "用户名", 32)
        password = field(data, "password", "密码", 256)
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username) or len(password) < 12:
            raise ValueError("用户名需为 3–32 位字母/数字/_.-，密码至少 12 位")
        cursor = g.db.execute("INSERT INTO users(username,password,role) VALUES(%s,%s,'member') RETURNING id",
                              (username, generate_password_hash(password)))
        log(username, "创建成员", "普通用户")
        g.db.commit()
        return jsonify(id=cursor.fetchone()["id"]), 201

    @app.delete("/api/users/<int:user_id>")
    @require(owner=True)
    def delete_user(user_id):
        row = g.db.execute("SELECT * FROM users WHERE id=%s", (user_id,)).fetchone()
        if not row:
            return jsonify(error="用户不存在"), 404
        if row["role"] == "owner":
            return jsonify(error="主用户不能被删除"), 403
        g.db.execute("DELETE FROM users WHERE id=%s", (user_id,))
        log(row["username"], "删除成员", "所有登录会话已失效")
        g.db.commit()
        return jsonify(ok=True)

    @app.post("/api/password")
    @require()
    def change_password():
        data = body()
        old = field(data, "old_password", "当前密码", 256)
        password = field(data, "password", "新密码", 256)
        row = g.db.execute("SELECT * FROM users WHERE id=%s", (g.user["id"],)).fetchone()
        if not check_password_hash(row["password"], old):
            return jsonify(error="当前密码错误"), 400
        if len(password) < 12:
            raise ValueError("新密码至少 12 位")
        g.db.execute("UPDATE users SET password=%s WHERE id=%s", (generate_password_hash(password), row["id"]))
        g.db.execute("DELETE FROM sessions WHERE user_id=%s", (row["id"],))
        g.db.commit()
        response = jsonify(ok=True)
        response.delete_cookie("wh_session", secure=app.config["COOKIE_SECURE"], samesite="Lax")
        return response

    return app


DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(32))
if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=8000)
