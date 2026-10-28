"""Phân cấp quyền (1 tự động, 2 trong phạm vi dự án, 3 phải duyệt) và kiểm tra đường dẫn."""
import re
from pathlib import Path

LEVEL3_PATTERNS = [
    r"\brm\s+-rf\b", r"\bdel\s+/[sfq]", r"\brmdir\s+/s", r"\bformat\b\s+[a-z]:", r"\bdrop\s+(table|database)\b",
    r"\bRunAs\b", r"\bStart-Process\b.*-Verb\s+RunAs", r"\bnet\s+user\b", r"\breg\s+(add|delete)\b",
    r"\bicacls\b", r"\bchmod\s+-R\b", r"\bdeploy\b", r"\bproduction\b", r"\bprod\b",
    r"xóa\s+(dữ liệu|database|db)", r"quản trị", r"triển khai\s+production", r"sửa\s+database\s+thật",
    r"\.env\b", r"\btoken\b", r"\bcredential",
]
_L3 = re.compile("|".join(LEVEL3_PATTERNS), re.IGNORECASE)


def required_level(text):
    """3 nếu yêu cầu đụng tới thao tác rủi ro; ngược lại 2 (sửa trong dự án)."""
    return 3 if _L3.search(text or "") else 2


def inside(project_dir, target):
    root = Path(project_dir).resolve()
    t = Path(target).resolve()
    return t == root or root in t.parents


def redact(text, secrets):
    for s in secrets:
        if s and len(s) >= 6:
            text = text.replace(s, "***")
    return text
