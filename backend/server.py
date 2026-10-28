"""FastAPI: API JSON, WebSocket cập nhật trạng thái, giao diện tĩnh.
Bảo vệ chống trang web bên ngoài và DNS rebinding: token ngẫu nhiên theo phiên, kiểm tra Host/Origin,
bắt buộc Content-Type JSON, giới hạn kích thước body. Chỉ bind 127.0.0.1 khi chạy."""
import asyncio
import json
import secrets
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

from quality import safety

UI = Path(__file__).resolve().parent.parent / "desktop" / "index.html"
MAX_BODY = 64 * 1024
LOCAL_HOSTS = ("127.0.0.1", "localhost")


def create_app(o, db, bot=None, mock=False, token=None):
    token = token or secrets.token_urlsafe(24)
    app = FastAPI(title="Ryan AI Command Center", docs_url=None, redoc_url=None, openapi_url=None)

    def snapshot():
        return {
            "mode": "MOCK" if mock else "LIVE",
            "telegram": ("mock" if mock else "connected") if bot else "not_connected",
            "agents": [{"name": a.name, "label": a.label, "status": a.status()} for a in o.ad.values()],
            "projects": db.projects(),
            "jobs": db.list_jobs(20),
        }

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = request.headers.get("host", "")
        if host.rsplit(":", 1)[0] not in LOCAL_HOSTS:       # chống DNS rebinding
            return JSONResponse({"error": "bad_host"}, 403)
        origin = request.headers.get("origin")
        if origin and origin != f"http://{host}":            # chỉ cho phép cùng nguồn
            return JSONResponse({"error": "bad_origin"}, 403)
        if request.url.path.startswith("/api/"):
            if request.headers.get("x-ryan-token") != token:
                return JSONResponse({"error": "unauthorized"}, 401)
            if request.method == "POST":
                if not request.headers.get("content-type", "").startswith("application/json"):
                    return JSONResponse({"error": "content_type_must_be_json"}, 415)
                if int(request.headers.get("content-length", "0") or 0) > MAX_BODY:
                    return JSONResponse({"error": "body_too_large"}, 413)
        return await call_next(request)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return UI.read_text(encoding="utf-8").replace("__RYAN_TOKEN__", token)

    @app.get("/api/state")
    def state():
        return snapshot()

    @app.get("/api/job/{jid}")
    def job(jid: str):
        return {"job": db.get_job(jid), "events": db.events(jid)}

    @app.post("/api/new")
    def new(body: dict):
        if body.get("project") and body["project"] not in {p["name"] for p in db.projects()}:
            return JSONResponse({"error": "unknown_project"}, 400)
        return {"job_id": o.new_job(body["request"], body.get("project"), "desktop")}

    @app.post("/api/project")
    def project(body: dict):
        err = safety.validate_project(body["path"])
        if err:
            return JSONResponse({"error": err}, 400)
        db.add_project(body["name"], body["path"])
        if body.get("test_cmd") is not None:
            db.kv_set(f"test_cmd:{body['name']}", body["test_cmd"])
        return {"ok": True}

    @app.post("/api/plan")
    async def plan(body: dict):
        return {"ok": await asyncio.to_thread(o.plan, body["job_id"])}

    @app.post("/api/approve")
    def approve(body: dict):
        return {"result": o.approve(body["job_id"], bool(body.get("confirm")))}

    @app.post("/api/run")
    def run(body: dict):
        return {"result": o.run(body["job_id"])}

    @app.post("/api/cancel")
    def cancel(body: dict):
        return {"ok": o.cancel(body["job_id"])}

    @app.post("/api/rollback")
    async def rollback(body: dict):
        return await asyncio.to_thread(o.rollback, body["job_id"])

    @app.post("/api/mock/telegram")
    def mock_telegram(body: dict):
        """Chỉ có khi MOCK_MODE: giả lập tin nhắn/nút bấm Telegram, trả về các tin bot đã gửi."""
        if not (mock and bot):
            return JSONResponse({"error": "mock_mode_only"}, 404)
        bot.api.sent.clear()
        uid = body.get("user_id", 0)
        if "callback" in body:
            upd = {"callback_query": {"id": "mock", "from": {"id": uid}, "data": body["callback"],
                                      "message": {"chat": {"id": uid, "type": "private"}}}}
        else:
            upd = {"message": {"from": {"id": uid}, "chat": {"id": uid, "type": "private"}, "text": body["text"]}}
        return {"result": bot.handle(upd), "sent": bot.api.sent}

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        if sock.query_params.get("t") != token or sock.headers.get("host", "").rsplit(":", 1)[0] not in LOCAL_HOSTS:
            await sock.close(code=4401)
            return
        await sock.accept()
        last = None
        try:
            while True:
                snap = await asyncio.to_thread(snapshot)
                if snap != last:
                    await sock.send_text(json.dumps(snap, ensure_ascii=False, default=str))
                    last = snap
                await asyncio.sleep(1)
        except WebSocketDisconnect:
            pass

    app.state.token = token
    return app
