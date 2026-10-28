"""Cấu hình chung. MOCK_MODE mặc định bật để chạy an toàn trên cloud; đặt MOCK_MODE=false khi chạy thật."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def mock_mode():
    return os.environ.get("MOCK_MODE", "true").strip().lower() in ("1", "true", "yes", "on")


def load_env(path=ROOT / ".env"):
    from quality.safety import register_secret
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            os.environ.setdefault(k.strip(), v)
            register_secret(v)  # mọi giá trị trong .env đều bị che khi ghi log/gửi
