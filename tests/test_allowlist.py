import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adapters.registry import load_config
from bot.telegram import Bot, from_env
from orchestrator.core import Orchestrator
from storage.db import DB
from tests.test_bot import cb, msg
from tests.test_orchestrator import Fake, make_repo


class Allowlist(unittest.TestCase):
    def setUp(self):
        self.cfg, self.db = load_config(), DB(":memory:")
        self.db.add_project("p", make_repo())
        self.o = Orchestrator(self.db, {n: Fake(n, ["x"]) for n in self.cfg["agents"]}, self.cfg)
        self.sent = []
        self.bot = Bot(self.o, self.db, "123456:MOCKTOKEN", ["148534973"],
                       api=lambda m, **p: self.sent.append(p) or {"result": []})

    def test_env_loaded_user_accepted(self):
        self.assertEqual(self.bot.handle(msg(148534973, "/help")), "ok")
        self.assertTrue(self.sent)

    def test_other_user_rejected_silently(self):
        self.assertEqual(self.bot.handle(msg(999, "/new hack")), "denied")
        self.assertEqual(self.sent, [])
        self.assertEqual(self.db.list_jobs(), [])

    def test_other_user_inline_button_rejected(self):
        self.assertEqual(self.bot.handle(cb(999, "/approve x")), "denied")

    def test_from_env_reads_allowlist(self):
        os.environ.update(TELEGRAM_BOT_TOKEN="123456:MOCKTOKEN", TELEGRAM_ALLOWED_USER_IDS="148534973")
        try:
            b = from_env(self.o, self.db)
            self.assertTrue(b.authorized(148534973))
            self.assertFalse(b.authorized(999))
        finally:
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            os.environ.pop("TELEGRAM_ALLOWED_USER_IDS", None)


if __name__ == "__main__":
    unittest.main()
