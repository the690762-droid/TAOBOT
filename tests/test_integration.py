"""Luồng 13 bước đầy đủ qua API + Telegram mock. Agent code là Fake ghi file thật để kiểm checkpoint/diff."""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient

from adapters.registry import load_config
from backend.server import create_app
from bot.telegram import mock_bot
from orchestrator.core import ARTIFACTS, Orchestrator
from storage.db import DB
from tests.test_orchestrator import Fake, make_repo

H = {"x-ryan-token": "ITEST", "content-type": "application/json"}
PY = sys.executable.replace("\\", "/")


class Flow13(unittest.TestCase):
    def test_full_flow(self):
        cfg, db = load_config(), DB(":memory:")
        repo = make_repo()
        o = Orchestrator(db, {n: Fake(n, ["1. bước\nVERDICT: PASS"]) for n in cfg["agents"]}, cfg)
        o.ad["haiku"] = Fake("haiku", ["đã sửa"], write="feature.txt")
        bot = mock_bot(o, db)
        o.notify = bot.notify
        o.start()
        c = TestClient(create_app(o, db, bot=bot, mock=True, token="ITEST"), base_url="http://127.0.0.1:8765")

        # 1-2: nhận yêu cầu Telegram, tạo mã công việc; 3: chọn dự án
        c.post("/api/project", json={"name": "p", "path": repo, "test_cmd": f"{PY} -c pass"}, headers=H)
        c.post("/api/mock/telegram", json={"user_id": 1, "text": "/use p"}, headers=H)
        r = c.post("/api/mock/telegram", json={"user_id": 1, "text": "thêm tính năng"}, headers=H).json()
        jid = db.list_jobs()[0]["id"]
        self.assertEqual(r["result"], "ok")
        # 4-5: Antigravity lập kế hoạch và lưu kế hoạch (mock plan)
        r = c.post("/api/mock/telegram", json={"user_id": 1, "callback": f"/plan {jid}"}, headers=H).json()
        self.assertEqual(db.get_job(jid)["status"], "AWAITING_APPROVAL")
        self.assertTrue(any("Kế hoạch" in m.get("text", "") for m in r["sent"]))
        # 6: duyệt
        c.post("/api/mock/telegram", json={"user_id": 1, "callback": f"/approve {jid}"}, headers=H)
        self.assertEqual(db.get_job(jid)["status"], "APPROVED")
        # 7-12: chạy executor (Haiku), test, review (Sonnet), kiểm định, lưu diff/log
        c.post("/api/mock/telegram", json={"user_id": 1, "callback": f"/run {jid}"}, headers=H)
        end = time.time() + 20
        while db.get_job(jid)["status"] not in ("DONE", "FAILED", "BLOCKED") and time.time() < end:
            time.sleep(0.05)
        job = db.get_job(jid)
        self.assertEqual(job["status"], "DONE", job["result"])
        self.assertTrue((Path(repo) / "feature.txt").exists())
        self.assertIn("feature.txt", (ARTIFACTS / jid / "diff.patch").read_text(encoding="utf-8"))
        # 13: báo cáo về Telegram và trạng thái qua API
        self.assertTrue(any("Kết thúc: DONE" in m.get("text", "") for m in bot.api.sent) or
                        any("Kết thúc: DONE" in str(x) for x in bot.api.sent))
        st = c.get(f"/api/job/{jid}", headers=H).json()
        self.assertEqual(st["job"]["status"], "DONE")
        self.assertEqual(c.post("/api/rollback", json={"job_id": jid}, headers=H).json()["error"], None)


if __name__ == "__main__":
    unittest.main()
