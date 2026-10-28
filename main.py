"""Điểm khởi chạy. MOCK_MODE=true (mặc định): agent và Telegram là mock. MOCK_MODE=false: nạp .env thật."""
import os
import secrets
import sys
import threading

import uvicorn

from adapters.registry import build_adapters, load_config
from backend.config import load_env, mock_mode
from backend.server import create_app
from bot.telegram import from_env, mock_bot
from orchestrator.core import Orchestrator
from quality.safety import register_secret
from storage.db import DB


def main():
    load_env()
    mock = mock_mode()
    cfg = load_config()
    db = DB()
    o = Orchestrator(db, build_adapters(cfg, mock=mock), cfg)
    if mock:
        bot = mock_bot(o, db)
        telegram_note = "Telegram: MOCK (không gọi mạng)."
    else:
        bot = from_env(o, db)
        telegram_note = ("Telegram: đang lắng nghe (đã giới hạn user ID)." if bot else
                         "Telegram: CHƯA KẾT NỐI (thiếu TELEGRAM_BOT_TOKEN hoặc TELEGRAM_ALLOWED_USER_IDS).")
    if bot:
        o.notify = bot.notify
        if not mock:
            threading.Thread(target=bot.poll_forever, daemon=True).start()
    o.start()
    port = int(os.environ.get("RYAN_API_PORT", "8765"))
    app = create_app(o, db, bot=bot, mock=mock, token=secrets.token_urlsafe(24))
    register_secret(app.state.token)
    print(f"Chế độ: {'MOCK' if mock else 'LIVE'}. {telegram_note}")
    print(f"Giao diện: http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    sys.exit(main())
