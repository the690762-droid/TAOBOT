"""Điểm khởi chạy: orchestrator + API desktop + bot Telegram (nếu đã cấu hình .env)."""
import os
import threading
from pathlib import Path

from adapters.registry import build_adapters, load_config
from backend.server import serve
from bot.telegram import from_env
from orchestrator.core import Orchestrator
from storage.db import DB


def load_env(path=Path(__file__).resolve().parent / ".env"):
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def main():
    load_env()
    cfg = load_config()
    db = DB()
    o = Orchestrator(db, build_adapters(cfg), cfg)
    o.start()
    bot = from_env(o, db)
    if bot:
        threading.Thread(target=bot.poll_forever, daemon=True).start()
        print("Telegram: đang lắng nghe (đã giới hạn user ID).")
    else:
        print("Telegram: CHƯA KẾT NỐI (thiếu TELEGRAM_BOT_TOKEN hoặc TELEGRAM_ALLOWED_USER_IDS trong .env).")
    port = int(os.environ.get("RYAN_API_PORT", "8765"))
    print(f"Giao diện: http://127.0.0.1:{port}")
    serve(o, db, port)


if __name__ == "__main__":
    main()
