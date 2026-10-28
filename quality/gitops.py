"""Checkpoint / diff / rollback bằng git. Không ghi đè thay đổi chưa commit của người dùng."""
import hashlib
import subprocess


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")


def is_dirty(cwd):
    return bool(_git(cwd, "status", "--porcelain").stdout.strip())


def head(cwd):
    r = _git(cwd, "rev-parse", "HEAD")
    return r.stdout.strip() if r.returncode == 0 else None


def checkpoint(cwd, job_id):
    """Tạo tag checkpoint tại HEAD. Từ chối nếu working tree đang có thay đổi chưa commit."""
    if _git(cwd, "rev-parse", "--is-inside-work-tree").stdout.strip() != "true":
        return {"ok": False, "error": "not_a_git_repo"}
    if is_dirty(cwd):
        return {"ok": False, "error": "dirty_working_tree"}
    commit = head(cwd)
    if not commit:
        return {"ok": False, "error": "no_commits"}
    tag = f"ryan-ckpt-{job_id}"
    r = _git(cwd, "tag", "-f", tag, commit)
    return {"ok": r.returncode == 0, "tag": tag, "commit": commit, "error": r.stderr.strip() or None}


def diff(cwd, tag):
    _git(cwd, "add", "-N", ".")  # đưa file mới vào diff (intent-to-add)
    return _git(cwd, "diff", tag).stdout


def changed_files(cwd, tag):
    _git(cwd, "add", "-N", ".")
    return [l for l in _git(cwd, "diff", "--name-only", tag).stdout.splitlines() if l]


def fingerprint(cwd):
    """Băm nội dung thay đổi hiện tại (đã gồm file mới). Dùng để biết người dùng có sửa sau lần chạy không."""
    _git(cwd, "add", "-N", ".")
    return hashlib.sha256(_git(cwd, "diff").stdout.encode("utf-8")).hexdigest()


def rollback(cwd, tag, expect_head, expect_fp):
    """Chỉ khôi phục khi HEAD vẫn là commit sau lần chạy; dọn file mới trong thư mục dự án."""
    if _git(cwd, "rev-parse", "--verify", tag).returncode != 0:
        return {"ok": False, "error": "checkpoint_not_found"}
    if head(cwd) != expect_head:
        return {"ok": False, "error": "head_changed_since_run"}
    if fingerprint(cwd) != expect_fp:
        return {"ok": False, "error": "working_tree_changed_since_run"}
    r = _git(cwd, "reset", "--hard", tag)
    c = _git(cwd, "clean", "-fd", "--", ".")
    return {"ok": r.returncode == 0 and c.returncode == 0, "error": r.stderr.strip() or c.stderr.strip() or None}
