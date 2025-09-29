#!/usr/bin/env python3

import os, time, hmac, secrets, threading, json, io, uuid, pathlib
from functools import wraps

from flask import Flask, request, jsonify, redirect, make_response, current_app
from werkzeug.exceptions import HTTPException

from googleservice import GoogleService
import config

UNIVERSAL_KEY = config.UNIVERSAL_KEY
SESSION_TTL_SECONDS = config.SESSION_TTL_SECONDS
HTTPS_COOKIES = config.HTTPS_COOKIES == 1
REDIS_URL = config.REDIS_URL
API_RATE_LIMIT = config.API_RATE_LIMIT

SESS_PREFIX = "sess:"
RL_PREFIX   = "rl:"   # rate limit

root_dir_name = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def create_app():
    # ============== APP INIT ====================
    app = Flask(__name__, static_folder=f"{root_dir_name}/client", static_url_path="")

    # Single per-process instance
    gsvc = GoogleService()

    # ============== REDIS =======================
    try:
        import redis
        rds = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        # quick ping on boot (non-fatal if it fails; you'll see 500s at runtime otherwise)
        try:
            rds.ping()
        except Exception:
            pass
    except Exception as e:
        raise RuntimeError("Redis is required for this gate. Install and set REDIS_URL.") from e

    def session_set(session_id: str, ttl: int = SESSION_TTL_SECONDS):
        rds.setex(SESS_PREFIX + session_id, ttl, "1")

    def session_valid(session_id: str) -> bool:
        if not session_id:
            return False
        return rds.exists(SESS_PREFIX + session_id) == 1

    def session_ttl(sid: str) -> int:
        if not sid: return -2
        return rds.ttl(SESS_PREFIX + sid)

    def session_delete(session_id: str):
        if not session_id:
            return
        rds.delete(SESS_PREFIX + session_id)

    def rate_limit_login(ip: str) -> bool:
        key = f"{RL_PREFIX}login:{ip or 'unknown'}"
        pipe = rds.pipeline()
        pipe.incr(key)
        pipe.expire(key, 60)
        count, _ = pipe.execute()
        return int(count) <= API_RATE_LIMIT

    # ============== COOKIE HELPERS ==============
    def _consttime_eq(a, b): return hmac.compare_digest(str(a or ""), str(b or ""))

    def set_session_cookie(resp, sid: str):
        resp.set_cookie(
            "auth_session", sid,
            max_age=SESSION_TTL_SECONDS,
            httponly=True,
            samesite="Lax",
            secure=HTTPS_COOKIES,
            path="/",
        )

    def clear_session_cookie(resp):
        resp.delete_cookie("auth_session", path="/")

    def require_session(fn):
        @wraps(fn)
        def w(*args, **kwargs):
            sid = request.cookies.get("auth_session")
            if not session_valid(sid):
                if request.path.startswith("/api/"):
                    return jsonify({"error": "unauthorized"}), 401
                # return inline login page (no asset dependencies)
                return redirect("/login")
            return fn(*args, **kwargs)
        return w

    # ============== AUTH PAGES ==================
    def login_page():
        return app.send_static_file('login.html'), 200, {"Content-Type":"text/html; charset=utf-8"}

    def loading_page():
        return app.send_static_file('loading.html'), 200, {"Content-Type":"text/html; charset=utf-8"}

    @app.get("/")
    def root_decider():
        sid = request.cookies.get("auth_session")
        if not sid:
            return login_page()
        return loading_page()

    @app.get("/login")
    def login_get():
        return login_page()

    @app.get("/auth/check")
    def auth_check():
        sid = request.cookies.get("auth_session")
        if session_valid(sid):
            ttl = session_ttl(sid)
            return jsonify({"ok": True, "ttl": ttl}), 200
        return jsonify({"ok": False}), 401

    @app.post("/auth/login")
    def login():
        # Basic per-IP rate limit
        if not rate_limit_login(request.remote_addr or "unknown"):
            return "Terlalu banyak percobaan gagal. Coba lagi setelah sesaat.", 429

        key = request.form.get("key", "")
        if not _consttime_eq(key, UNIVERSAL_KEY):
            time.sleep(0.4)
            return "Kode akses salah.", 401

        sid = secrets.token_urlsafe(32)
        session_set(sid, SESSION_TTL_SECONDS)
        resp = make_response(redirect("/"))
        set_session_cookie(resp, sid)
        return resp

    @app.post("/auth/logout")
    def logout():
        sid = request.cookies.get("auth_session")
        if sid: session_delete(sid)
        resp = make_response(redirect("/"))
        clear_session_cookie(resp)
        return resp

    # ============== GATED UI & ASSETS ===========
    @app.get("/index.html")
    def handle_index():
        return redirect("/")

    @app.get("/loading.html")
    def handle_loading():
        return redirect("/")

    @app.get("/form")
    @require_session
    def form_index():
        return app.send_static_file("index.html")

    @app.get("/script.js")
    @require_session
    def js():
        return app.send_static_file("script.js")

    @app.get("/style.css")
    @require_session
    def css():
        return app.send_static_file("style.css")


    # ============== API =========================
    @app.post("/api/append-to-sheet")
    @require_session
    def drive_then_sheet():
        log_request_summary()

        foto_evidence = request.files.get("foto_evidence")
        if not foto_evidence: return jsonify({"error":"image required"}), 400
        if foto_evidence.content_length and foto_evidence.content_length > 16777216:
            return jsonify({"error":"file too large"}), 413

        form_dict = request.form.to_dict(flat=True)
        for key, value in form_dict.items():
            if value == '':
                form_dict[key] = '-'

        image_file = foto_evidence.stream
        image_file.seek(0)

        gsvc.authenticate()
        gsvc.build_services()

        try:
            drive_link = gsvc.upload_to_drive(image_file, f"{form_dict.get('kode_sa')}_{form_dict.get('tanggal')}_{form_dict.get('kegiatan')}.jpg")
            form_dict['foto_evidence'] = drive_link

            row = [
                form_dict.get('kode_sa', '-'),      # 1
                form_dict.get('nama', '-'),         # 2
                form_dict.get('no_telp', '-'),      # 3
                form_dict.get('witel', '-'),        # 4
                form_dict.get('telda', '-'),        # 5
                form_dict.get('tanggal', '-'),      # 6
                form_dict.get('kategori', '-'),     # 7
                form_dict.get('tenant', '-'),       # 8
                form_dict.get('kegiatan', '-'),     # 9
                form_dict.get('layanan', '-'),      # 10
                form_dict.get('tarif', '-'),        # 11
                form_dict.get('nama_pic', '-'),     # 12
                form_dict.get('jabatan_pic', '-'),  # 13
                form_dict.get('telepon_pic', '-'),  # 14
                form_dict.get('paket_deal', '-'),   # 15
                form_dict.get('deal_bundling', '-'), # 16
                form_dict.get('foto_evidence', '-'), # 17
            ]

            success, res = gsvc.append_to_sheet([row])

            return jsonify({"row": row, "status": success})

        except Exception as e:
            current_app.logger.info(f'Error ocurred on google service process: {e}')

        return app

    # ============== ERROR HANDLER (clean JSON) ==
    @app.errorhandler(Exception)
    def on_error(e):
        if isinstance(e, HTTPException):
            return jsonify(error=e.description), e.code
        app.logger.exception("Unhandled error")
        return jsonify(error="internal server error"), 500

    return app

def _files_summary(files):
    out = {}
    for k, f in files.items():
        out[k] = {
            "filename": f.filename,
            "mimetype": f.mimetype,
            # works for SpooledTemporaryFile/FileStorage that support seek/tell
        }
        try:
            pos = f.stream.tell()
            f.stream.seek(0, os.SEEK_END)
            out[k]["size"] = f.stream.tell()
            f.stream.seek(pos, os.SEEK_SET)
        except Exception:
            out[k]["size"] = None
    return out

def log_request_summary():
    info = {
        "method": request.method,
        "path": request.path,
        "url": request.url,
        "remote_addr": request.remote_addr,
        "content_type": request.content_type,
        "content_length": request.content_length,
        "args": request.args.to_dict(flat=True),
        "form": request.form.to_dict(flat=True),
        "json": request.get_json(silent=True),
        "files": _files_summary(request.files),
        "headers": {k: v for k, v in request.headers.items()
                    if k.lower() in ("content-type","content-length","user-agent","x-telegram-initdata","x-forwarded-for")},
    }
    current_app.logger.info("REQUEST:\n%s", json.dumps(info, indent=2))

# ============== DEV ENTRY ===================
if __name__ == "__main__":
    app = create_app()

    # Dev server (HTTP). For production, run with gunicorn and put Nginx in front.
    app.run(host="127.0.0.1", port=8000, debug=True)
