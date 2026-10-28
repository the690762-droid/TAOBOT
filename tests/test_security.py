import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient

from adapters.registry import load_config
from backend.server import create_app
from orchestrator.core import Orchestrator
from quality import gitops, safety
from storage.db import DB
from tests.test_orchestrator import Fake, make_repo, wait


def mk(mock=True):
    cfg, db = load_config(), DB(":memory:")
    repo = make_repo()
    db.add_project("p", repo)
    db.kv_set("test_cmd:p", f"{sys.executable.replace(chr(92), '/')} -c pass")
    o = Orchestrator(db, {n: Fake(n, ["VERDICT: PASS"]) for n in cfg["agents"]}, cfg)
    o.start()
    from bot.telegram import mock_bot
    app = create_app(o, db, bot=mock_bot(o, db), mock=True, token="T0KEN")
    return TestClient(app, base_url="http://127.0.0.1:8765"), db, o, repo


class Api(unittest.TestCase):
    def setUp(self):
        self.c, self.db, self.o, self.repo = mk()
        self.h = {"x-ryan-token": "T0KEN", "content-type": "application/json"}

    def test_no_token_rejected(self):
        self.assertEqual(self.c.get("/api/state").status_code, 401)

    def test_wrong_host_rejected(self):
        r = self.c.get("/api/state", headers={**self.h, "host": "evil.test:8765"})
        self.assertEqual(r.status_code, 403)

    def test_cross_origin_rejected(self):
        r = self.c.post("/api/new", json={"request": "x"}, headers={**self.h, "origin": "https://evil.test"})
        self.assertEqual(r.status_code, 403)

    def test_text_plain_post_rejected(self):
        r = self.c.post("/api/new", content=b'{"request":"x"}', headers={**self.h, "content-type": "text/plain"})
        self.assertEqual(r.status_code, 415)

    def test_oversized_body_rejected(self):
        r = self.c.post("/api/new", content=b"x" * (70 * 1024), headers=self.h)
        self.assertEqual(r.status_code, 413)

    def test_project_path_validated(self):
        r = self.c.post("/api/project", json={"name": "bad", "path": "/"}, headers=self.h)
        self.assertEqual(r.status_code, 400)
        self.assertNotIn("bad", [p["name"] for p in self.db.projects()])

    def test_index_embeds_token_only_for_host(self):
        self.assertIn("T0KEN", self.c.get("/", headers={"host": "127.0.0.1:8765"}).text)

    def test_mock_telegram_endpoint(self):
        r = self.c.post("/api/mock/telegram", json={"user_id": 1, "text": "/help"}, headers=self.h)
        self.assertEqual(r.json()["result"], "ok")  # user 1 nằm trong allowlist mock
        self.assertTrue(r.json()["sent"])

    def test_mock_mode_label_in_state(self):
        self.assertEqual(self.c.get("/api/state", headers=self.h).json()["mode"], "MOCK")


class Safety(unittest.TestCase):
    def test_validate_project(self):
        self.assertIsNone(safety.validate_project(make_repo()))
        self.assertIsNotNone(safety.validate_project(tempfile.mkdtemp()))  # không phải git repo
        self.assertIsNotNone(safety.validate_project("relative/path"))
        self.assertIsNotNone(safety.validate_project(str(Path.home())))

    def test_redact(self):
        safety.register_secret("SUPERSECRET123")
        self.assertEqual(safety.redact("a SUPERSECRET123 b"), "a *** b")


class States(unittest.TestCase):
    def test_cancel_wins_over_status_writes(self):
        c, db, o, repo = mk()
        jid = o.new_job("x", "p")
        db.set_status(jid, "CANCELLED")
        self.assertFalse(db.set_status(jid, "RUNNING"))
        self.assertEqual(db.get_job(jid)["status"], "CANCELLED")

    def test_cancel_refused_on_done_job(self):
        c, db, o, repo = mk()
        jid = o.new_job("x", "p")
        db.set_status(jid, "DONE")
        self.assertFalse(o.cancel(jid))
        self.assertEqual(db.get_job(jid)["status"], "DONE")

    def test_cancelled_while_queued_does_not_run(self):
        c, db, o, repo = mk()
        jid = o.new_job("sửa", "p"); o.plan(jid); o.approve(jid)
        o.cancel(jid)
        o._execute(jid)  # worker sẽ gọi đúng hàm này
        self.assertEqual(db.get_job(jid)["status"], "CANCELLED")

    def test_level3_needs_explicit_confirm(self):
        c, db, o, repo = mk()
        jid = o.new_job("deploy production", "p")
        db.set_status(jid, "AWAITING_APPROVAL", plan={"text": "x", "level": 3})
        self.assertEqual(o.approve(jid), "needs_confirm")
        self.assertEqual(o.approve(jid, confirm=True), "approved")

    def test_rollback_refused_while_active(self):
        c, db, o, repo = mk()
        jid = o.new_job("x", "p")
        db.set_status(jid, "RUNNING")
        self.assertEqual(o.rollback(jid)["error"], "job_still_active")

    def test_rollback_refused_when_head_moved(self):
        c, db, o, repo = mk()
        jid = o.new_job("x", "p")
        ck = gitops.checkpoint(repo, jid)
        db.kv_set(f"ckpt:{jid}", ck["tag"]); db.kv_set(f"post:{jid}", ck["commit"])
        (Path(repo) / "n.txt").write_text("user work")
        subprocess_commit(repo)
        db.set_status(jid, "DONE")
        self.assertEqual(o.rollback(jid)["error"], "head_changed_since_run")
        self.assertTrue((Path(repo) / "n.txt").exists())


def subprocess_commit(repo):
    import subprocess
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "user"], cwd=repo, check=True)


if __name__ == "__main__":
    unittest.main()
