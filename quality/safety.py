"""Phân cấp quyền, kiểm tra dự án, redact secret. Mọi đường dẫn dùng pathlib."""
import re
from pathlib import Path

LEVEL3_PATTERNS = [
    r"\brm\s+-rf\b", r"\bdel\s+/[sfq]", r"\brmdir\s+/s", r"\bformat\b\s+[a-z]:", r"\bdrop\s+(table|database)\b",
    r"\bRunAs\b", r"\bnet\s+user\b", r"\breg\s+(add|delete)\b", r"\bicacls\b", r"\bchmod\s+-R\b",
    r"\bdeploy\b", r"\bproduction\b", r"\bprod\b", r"xóa\s+(dữ liệu|database|db)", r"quản trị",
    r"sửa\s+database\s+thật", r"\.env\b", r"\btoken\b", r"\bcredential",
]
_L3 = re.compile("|".join(LEVEL3_PATTERNS), re.IGNORECASE)
SECRETS = set()


def required_level(text):
    """3 nếu yêu cầu đụng tới thao tác rủi ro (cần xác nhận riêng); ngược lại 2."""
    return 3 if _L3.search(text or "") else 2


def validate_project(path):
    """Dự án phải là thư mục tuyệt đối, là gốc git repo, và không phải / hoặc thư mục home."""
    p = Path(path)
    if not p.is_absolute() or not p.is_dir():
        return "đường dẫn không phải thư mục tuyệt đối tồn tại"
    if p.resolve() in (Path(p.anchor), Path.home().resolve()):
        return "không được chọn ổ đĩa gốc hoặc thư mục home"
    if not (p / ".git").exists():
        return "thư mục phải là gốc của git repo"
    return None


def register_secret(value):
    if value and len(value) >= 6:
        SECRETS.add(value)


def redact(text):
    for s in SECRETS:
        text = (text or "").replace(s, "***")
    return text
