import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adapters.registry import load_config
from bot.telegram import Bot
from orchestrator.core import Orchestrator
from storage.db import DB
from tests.test_orchestrator import Fake, make_repo


def mk():
    cfg, db = load_config(), DB(":memory:")
    db.add_project("p", make_repo())
    o = Orchestrator(db, {n: Fake(n, ["kế hoạch"]) for n in cfg["agents"]}, cfg)
    sent = []
    def api(method, **p):
        sent.append((method, p)); return {"result": []}
    return Bot(o, db, "SECRETTOKEN123", ["42"], api=api), db, sent


def msg(uid, text): return {"update_id": 1, "message": {"from": {"id": uid}, "chat": {"id": uid, "type": "private"}, "text": text}}
def cb(uid, data): return {"update_id": 2, "callback_query": {"id": "c", "from": {"id": uid}, "message": {"chat": {"id": uid, "type": "private"}}, "data": data}}


class T(unittest.TestCase):
    def test_unauthorized_message_ignored(self):
        b, db, sent = mk()
        self.assertEqual(b.handle(msg(7, "/new hack")), "denied")
        self.assertEqual(sent, []); self.assertEqual(db.list_jobs(), [])

    def test_unauthorized_inline_button_denied(self):
        b, db, sent = mk()
        self.assertEqual(b.handle(cb(7, "/approve x")), "denied")
        self.assertEqual(sent[0][0], "answerCallbackQuery")

    def test_flow_new_plan_approve(self):
        b, db, sent = mk()
        b.handle(msg(42, "/use p"))
        b.handle(msg(42, "sửa giao diện"))
        jid = db.list_jobs()[0]["id"]
        b.handle(cb(42, f"/plan {jid}"))
        self.assertEqual(db.get_job(jid)["status"], "AWAITING_APPROVAL")
        b.handle(cb(42, f"/approve {jid}"))
        self.assertEqual(db.get_job(jid)["status"], "APPROVED")

    def test_token_never_sent(self):
        b, db, sent = mk()
        b.send(42, "token là SECRETTOKEN123")
        self.assertNotIn("SECRETTOKEN123", sent[-1][1]["text"])

    def test_natural_message_plans_with_buttons(self):
        b, db, sent = mk()
        b.handle(msg(42, "/use p"))
        b.handle(msg(42, "thêm một file mới"))
        jid = db.list_jobs()[0]["id"]
        self.assertEqual(db.get_job(jid)["status"], "AWAITING_APPROVAL")
        card = sent[-1][1]
        self.assertIn("Kế hoạch", card["text"])
        labels = [b_["text"] for row in card["reply_markup"]["inline_keyboard"] for b_ in row]
        self.assertEqual(labels, ["Duyệt ✅", "Hủy ✖"])
        self.assertNotIn("parse_mode", card)

    def test_level3_plan_asks_confirmation(self):
        b, db, sent = mk()
        b.handle(msg(42, "/use p"))
        b.handle(msg(42, "deploy production"))
        jid = db.list_jobs()[0]["id"]
        self.assertEqual(db.get_job(jid)["plan"] and json.loads(db.get_job(jid)["plan"])["level"], 3)
        labels = [x["text"] for row in sent[-1][1]["reply_markup"]["inline_keyboard"] for x in row]
        self.assertIn("Xác nhận duyệt ⚠️", labels)
        b.handle(cb(42, f"/approve {jid}"))
        self.assertEqual(db.get_job(jid)["status"], "AWAITING_APPROVAL")

    def test_cost_is_unknown(self):
        b, db, sent = mk()
        b.handle(msg(42, "/cost"))
        self.assertIn("chưa xác định", sent[-1][1]["text"])


if __name__ == "__main__":
    unittest.main()
