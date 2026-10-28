"""Checkpoint / diff / rollback bằng git. Không ghi đè thay đổi chưa commit của người dùng."""
import subprocess


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def is_repo(cwd):
    return _git(cwd, "rev-parse", "--is-inside-work-tree").stdout.strip() == "true"


def is_dirty(cwd):
    return bool(_git(cwd, "status", "--porcelain").stdout.strip())


def checkpoint(cwd, job_id):
    """Tạo tag checkpoint tại HEAD. Từ chối nếu working tree đang có thay đổi chưa commit."""
    if not is_repo(cwd):
        return {"ok": False, "error": "not_a_git_repo"}
    if is_dirty(cwd):
        return {"ok": False, "error": "dirty_working_tree"}
    head = _git(cwd, "rev-parse", "HEAD")
    if head.returncode != 0:
        return {"ok": False, "error": "no_commits"}
    tag = f"ryan-ckpt-{job_id}"
    r = _git(cwd, "tag", "-f", tag)
    return {"ok": r.returncode == 0, "tag": tag, "commit": head.stdout.strip(), "error": r.stderr.strip() or None}


def diff(cwd, tag):
    return _git(cwd, "diff", tag).stdout


def changed_files(cwd, tag):
    return [l for l in _git(cwd, "diff", "--name-only", tag).stdout.splitlines() if l]


def rollback(cwd, tag):
    """Khôi phục file đã theo dõi về checkpoint và dọn file mới do agent tạo."""
    if _git(cwd, "rev-parse", "--verify", tag).returncode != 0:
        return {"ok": False, "error": "checkpoint_not_found"}
    r = _git(cwd, "reset", "--hard", tag)
    c = _git(cwd, "clean", "-fd")
    return {"ok": r.returncode == 0, "error": r.stderr.strip() or c.stderr.strip() or None}
