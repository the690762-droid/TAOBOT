"""Telegram bot (long polling, chỉ stdlib). Logic xử lý tách khỏi mạng để test được."""
import json
import os
import time
import urllib.parse
import urllib.request

HELP = ("/new <yêu cầu> · /plan · /run · /status · /approve · /cancel · /review · /logs · "
        "/cost · /projects · /use <dự án> · /agents · /rollback")


class Bot:
    def __init__(self, orch, db, token, allowed_ids, api=None):
        self.o, self.db, self.token = orch, db, token
        self.allowed = {int(x) for x in allowed_ids if str(x).strip()}
        self.api = api or self._api
        self.cur = {}      # chat_id -> job_id hiện tại
        self.proj = {}     # chat_id -> project
        self.offset = 0

    def _api(self, method, **params):
        data = urllib.parse.urlencode({k: v if isinstance(v, str) else json.dumps(v) for k, v in params.items()}).encode()
        with urllib.request.urlopen(f"https://api.telegram.org/bot{self.token}/{method}", data, timeout=60) as r:
            return json.load(r)

    def send(self, chat, text, buttons=None):
        text = text.replace(self.token, "***") if self.token else text
        p = {"chat_id": chat, "text": text[:4000]}
        if buttons:
            p["reply_markup"] = {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in buttons]]}
        return self.api("sendMessage", **p)

    def authorized(self, uid):
        return int(uid) in self.allowed

    # ---- xử lý một update ----
    def handle(self, upd):
        if "callback_query" in upd:
            cq = upd["callback_query"]
            uid, chat, text = cq["from"]["id"], cq["message"]["chat"]["id"], cq["data"]
            if not self.authorized(uid):          # xác minh quyền cả với nút inline
                self.api("answerCallbackQuery", callback_query_id=cq["id"], text="Không có quyền")
                return "denied"
            self.api("answerCallbackQuery", callback_query_id=cq["id"])
        elif "message" in upd and "text" in upd["message"]:
            m = upd["message"]
            uid, chat, text = m["from"]["id"], m["chat"]["id"], m["text"].strip()
            if not self.authorized(uid):
                return "denied"                   # im lặng, không lộ sự tồn tại của bot
        else:
            return "ignored"
        self.command(chat, text)
        return "ok"

    def _jid(self, chat, arg=""):
        return arg or self.cur.get(chat)

    def command(self, chat, text):
        cmd, _, arg = text.partition(" ")
        cmd, arg = cmd.lower().split("@")[0], arg.strip()
        o, db = self.o, self.db
        if cmd == "/start" or cmd == "/help":
            return self.send(chat, HELP)
        if cmd == "/projects":
            ps = db.projects()
            return self.send(chat, "\n".join(f"{p['name']} — {p['path']}" for p in ps) or "Chưa có dự án nào. Thêm trong giao diện desktop.")
        if cmd == "/use":
            if arg not in {p["name"] for p in db.projects()}:
                return self.send(chat, "Dự án không tồn tại.")
            self.proj[chat] = arg
            return self.send(chat, f"Đã chọn dự án: {arg}")
        if cmd == "/agents":
            return self.send(chat, "\n".join(f"{a.label}: {a.status()}" for a in o.ad.values()))
        if cmd == "/cost":
            return self.send(chat, "Chi phí: chưa xác định (chưa có nguồn usage đáng tin cậy).")
        if cmd == "/new" or not cmd.startswith("/"):
            req = arg if cmd == "/new" else text
            if not req:
                return self.send(chat, "Dùng: /new <yêu cầu>")
            jid = o.new_job(req, self.proj.get(chat), "telegram")
            self.cur[chat] = jid
            return self.send(chat, f"Đã tạo công việc {jid}. Bấm Lập kế hoạch.", [("Lập kế hoạch", f"/plan {jid}")])
        jid = self._jid(chat, arg)
        job = db.get_job(jid) if jid else None
        if not job:
            return self.send(chat, "Chưa có công việc. Dùng /new.")
        if cmd == "/plan":
            ok = o.plan(jid)
            j = db.get_job(jid)
            if ok:
                return self.send(chat, f"Kế hoạch ({jid}):\n{json.loads(j['plan'])['text']}", [("Duyệt", f"/approve {jid}"), ("Hủy", f"/cancel {jid}")])
            return self.send(chat, f"{j['status']}: {j['result']}")
        if cmd == "/approve":
            if not o.approve(jid):
                return self.send(chat, "Không có kế hoạch nào đang chờ duyệt.")
            return self.send(chat, "Đã duyệt.", [("Chạy", f"/run {jid}")])
        if cmd == "/run":
            return self.send(chat, f"Chạy: {o.run(jid)}")
        if cmd == "/cancel":
            o.cancel(jid)
            return self.send(chat, "Đã hủy.")
        if cmd in ("/status", "/review"):
            return self.send(chat, f"{jid}: {job['status']}\n{job['result'] or ''}")
        if cmd == "/logs":
            return self.send(chat, "\n".join(f"{e['agent']}/{e['kind']}: {e['message']}" for e in db.events(jid, 20)) or "Không có log.")
        if cmd == "/rollback":
            return self.send(chat, f"Rollback: {o.rollback(jid)}")
        return self.send(chat, HELP)

    def poll_forever(self):
        while True:
            try:
                for u in self.api("getUpdates", offset=self.offset, timeout=30).get("result", []):
                    self.offset = u["update_id"] + 1
                    self.handle(u)
            except Exception:
                time.sleep(5)


def from_env(orch, db):
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    ids = os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "").split(",")
    return Bot(orch, db, tok, ids) if tok and any(i.strip() for i in ids) else None
