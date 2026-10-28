"""Cấu hình chung. MOCK_MODE mặc định bật để chạy an toàn trên cloud; đặt MOCK_MODE=false khi chạy thật."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def mock_mode():
    return os.environ.get("MOCK_MODE", "true").strip().lower() in ("1", "true", "yes", "on")


def load_env(path=ROOT / ".env"):
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
