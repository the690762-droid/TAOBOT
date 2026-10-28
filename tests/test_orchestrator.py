import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adapters.registry import load_config
from orchestrator.core import Orchestrator, parse_verdict
from quality import gitops, safety
from storage.db import DB


class Fake:
    """Agent giả cho test: trả lời theo kịch bản, có thể ghi file vào workspace."""
    def __init__(self, name, replies, write=None, ok=True):
        self.name, self.replies, self.write, self.ok, self.calls = name, list(replies), write, ok, 0
        self.enabled, self.label = True, name

    def status(self): return "ready"
    def cancel(self): pass

    def run(self, prompt, cwd, timeout=900, role=None):
        self.calls += 1
        if self.write:
            (Path(cwd) / self.write).write_text(f"v{self.calls}")
        out = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return {"agent": self.name, "role": role, "ok": self.ok, "exit_code": 0 if self.ok else 1,
                "duration": 0.01, "stdout": out, "stderr": "", "error": None if self.ok else "exit_code_1"}


def make_repo():
    d = tempfile.mkdtemp()
    for c in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *c], cwd=d, check=True)
    (Path(d) / "a.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=d, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=d, check=True)
    return d


PY = sys.executable.replace("\\", "/")


def setup(ad_overrides, test_cmd=f"{PY} -c pass"):
    cfg = load_config()
    db = DB(":memory:")
    repo = make_repo()
    db.add_project("p", repo)
    db.kv_set("test_cmd:p", test_cmd)
    base = {n: Fake(n, ["ok"]) for n in cfg["agents"]}
    base.update(ad_overrides)
    o = Orchestrator(db, base, cfg)
    o.start()
    return o, db, repo, base


def wait(db, jid, final, t=10):
    end = time.time() + t
    while time.time() < end:
        if db.get_job(jid)["status"] in final:
            return db.get_job(jid)["status"]
        time.sleep(0.05)
    return db.get_job(jid)["status"]


class T(unittest.TestCase):
    def test_happy_path_done(self):
        ov = {"antigravity": Fake("antigravity", ["plan"]), "haiku": Fake("haiku", ["x"], write="b.txt"),
              "sonnet": Fake("sonnet", ["VERDICT: PASS"]), "claude_code": Fake("claude_code", ["VERDICT: PASS"])}
        o, db, repo, _ = setup(ov)
        jid = o.new_job("thêm file b", "p")
        self.assertTrue(o.plan(jid))
        self.assertEqual(db.get_job(jid)["status"], "AWAITING_APPROVAL")
        self.assertEqual(o.run(jid), "not_approved")
        self.assertEqual(o.approve(jid), "approved")
        self.assertEqual(o.run(jid), "queued")
        self.assertEqual(wait(db, jid, {"DONE", "FAILED", "BLOCKED"}), "DONE")
        self.assertTrue((Path(repo) / "b.txt").exists())

    def test_duplicate_run_rejected(self):
        o, db, _, _ = setup({})
        jid = o.new_job("x", "p"); o.plan(jid); o.approve(jid)
        o.current = jid
        self.assertEqual(o.run(jid), "duplicate")

    def test_review_fail_exhausts_rounds(self):
        ov = {"haiku": Fake("haiku", ["x"], write="b.txt"), "sonnet": Fake("sonnet", ["VERDICT: FAIL\nbug"]),
              "opus": Fake("opus", ["VERDICT: FAIL\nbug"])}
        o, db, _, ag = setup(ov)
        jid = o.new_job("sửa", "p"); o.plan(jid); o.approve(jid); o.run(jid)
        self.assertEqual(wait(db, jid, {"DONE", "FAILED", "BLOCKED"}), "FAILED")
        self.assertEqual(ag["haiku"].calls, 4)  # 1 lần đầu + 3 vòng sửa
        self.assertGreaterEqual(ag["opus"].calls, 1)  # leo thang Opus

    def test_dirty_tree_blocks_and_protects_user_changes(self):
        o, db, repo, _ = setup({})
        (Path(repo) / "a.txt").write_text("user edit")
        jid = o.new_job("sửa", "p"); o.plan(jid); o.approve(jid); o.run(jid)
        self.assertEqual(wait(db, jid, {"DONE", "FAILED", "BLOCKED"}), "BLOCKED")
        self.assertEqual((Path(repo) / "a.txt").read_text(), "user edit")

    def test_missing_cli_blocks_planning(self):
        ov = {"antigravity": Fake("antigravity", [""], ok=False)}
        o, db, _, _ = setup(ov)
        jid = o.new_job("x", "p")
        self.assertFalse(o.plan(jid))
        self.assertEqual(db.get_job(jid)["status"], "BLOCKED")

    def test_no_test_command_cannot_be_done(self):
        ov = {"sonnet": Fake("sonnet", ["VERDICT: PASS"]), "claude_code": Fake("claude_code", ["VERDICT: PASS"])}
        o, db, _, _ = setup(ov, test_cmd="")
        db.kv_set("test_cmd:p", "")
        jid = o.new_job("x", "p"); o.plan(jid); o.approve(jid); o.run(jid)
        self.assertEqual(wait(db, jid, {"DONE", "FAILED", "BLOCKED"}), "BLOCKED")

    def test_rollback_restores_checkpoint(self):
        ov = {"haiku": Fake("haiku", ["x"], write="b.txt"), "sonnet": Fake("sonnet", ["VERDICT: PASS"]),
              "claude_code": Fake("claude_code", ["VERDICT: PASS"])}
        o, db, repo, _ = setup(ov)
        jid = o.new_job("x", "p"); o.plan(jid); o.approve(jid); o.run(jid)
        wait(db, jid, {"DONE", "FAILED", "BLOCKED"})
        self.assertTrue(o.rollback(jid)["ok"])
        self.assertFalse((Path(repo) / "b.txt").exists())

    def test_cancel(self):
        o, db, _, _ = setup({})
        jid = o.new_job("x", "p"); self.assertTrue(o.cancel(jid))
        self.assertEqual(db.get_job(jid)["status"], "CANCELLED")

    def test_helpers(self):
        self.assertEqual(parse_verdict("VERDICT: PASS\nok"), "PASS")
        self.assertEqual(parse_verdict("blah"), "UNKNOWN")
        self.assertEqual(safety.required_level("deploy production"), 3)
        safety.register_secret("tok123456")
        self.assertEqual(safety.redact("tok123456 x"), "*** x")


if __name__ == "__main__":
    unittest.main()
