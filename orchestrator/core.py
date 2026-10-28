"""Orchestrator: nhận việc -> kế hoạch -> duyệt -> thực thi -> test -> review -> sửa -> kiểm định.
Một worker duy nhất xử lý hàng đợi nên không bao giờ có hai executor cùng sửa một workspace."""
import queue
import subprocess
import threading

from quality import gitops, safety

SMALL_HINTS = ("log", "giải thích", "tóm tắt", "explain", "summarize", "typo")


def parse_verdict(text):
    for line in (text or "").splitlines():
        u = line.strip().upper()
        if u.startswith("VERDICT:"):
            return "PASS" if "PASS" in u else "FAIL"
    return "UNKNOWN"


class Orchestrator:
    def __init__(self, db, adapters, cfg, notify=None):
        self.db, self.ad, self.cfg = db, adapters, cfg
        self.notify = notify or (lambda jid, msg: None)
        self.q = queue.Queue()
        self.queued = set()
        self.current = None
        self.lock = threading.Lock()
        self.worker = None

    # ---------- API ----------
    def start(self):
        self.worker = threading.Thread(target=self._loop, daemon=True)
        self.worker.start()

    def new_job(self, request, project=None, source="desktop"):
        return self.db.create_job(request, project, source)

    def _say(self, jid, agent, kind, msg):
        self.db.event(jid, agent, kind, msg)
        self.notify(jid, f"[{agent}] {msg}")

    def _agent(self, role, request=""):
        name = self.cfg["routes"][role]
        if role == "code" and any(h in request.lower() for h in SMALL_HINTS):
            name = self.cfg["routes"]["small"]
        return self.ad[name]

    def _project_dir(self, job):
        for p in self.db.projects():
            if p["name"] == job["project"]:
                return p["path"]
        return None

    def plan(self, jid):
        job = self.db.get_job(jid)
        pdir = self._project_dir(job)
        if not pdir:
            self.db.set_status(jid, "BLOCKED", result="Chưa chọn dự án hợp lệ (dùng /projects).")
            return False
        self.db.set_status(jid, "PLANNING")
        ag = self._agent("plan")
        prompt = ("Chỉ lập kế hoạch, KHÔNG sửa code. Trả về các bước nhỏ, danh sách file cần sửa và tiêu chí kiểm thử.\n"
                  f"Yêu cầu: {job['request']}")
        res = ag.run(prompt, pdir, self.cfg["limits"]["timeout_sec"], "plan")
        self.db.add_run(jid, res)
        if not res["ok"]:
            self.db.set_status(jid, "BLOCKED", result=f"Lập kế hoạch lỗi ({ag.name}): {res['error']}")
            self._say(jid, ag.name, "error", res["error"])
            return False
        level = safety.required_level(job["request"] + res["stdout"])
        self.db.set_status(jid, "AWAITING_APPROVAL", plan={"text": res["stdout"], "level": level})
        self._say(jid, ag.name, "plan", f"Kế hoạch sẵn sàng (cấp quyền {level}). Cần /approve.")
        return True

    def approve(self, jid):
        job = self.db.get_job(jid)
        if not job or job["status"] != "AWAITING_APPROVAL":
            return False
        self.db.set_status(jid, "APPROVED")
        return True

    def run(self, jid):
        """Đưa việc đã duyệt vào hàng đợi; chống chạy trùng."""
        job = self.db.get_job(jid)
        if not job or job["status"] != "APPROVED":
            return "not_approved"
        with self.lock:
            if jid in self.queued or self.current == jid:
                return "duplicate"
            self.queued.add(jid)
        self.q.put(jid)
        return "queued"

    def cancel(self, jid):
        if self.current == jid:
            for a in self.ad.values():
                a.cancel()
        self.db.set_status(jid, "CANCELLED")

    def rollback(self, jid):
        job = self.db.get_job(jid)
        ck = self.db.kv_get(f"ckpt:{jid}")
        pdir = self._project_dir(job) if job else None
        if not ck or not pdir:
            return {"ok": False, "error": "no_checkpoint"}
        return gitops.rollback(pdir, ck)

    # ---------- worker ----------
    def _loop(self):
        while True:
            jid = self.q.get()
            with self.lock:
                self.queued.discard(jid)
                self.current = jid
            try:
                self._execute(jid)
            except Exception as e:  # không để worker chết
                self.db.set_status(jid, "FAILED", result=f"Lỗi nội bộ: {e!r}")
            finally:
                with self.lock:
                    self.current = None

    def _cancelled(self, jid):
        return self.db.get_job(jid)["status"] == "CANCELLED"

    def _run_tests(self, jid, pdir):
        cmd = self.db.kv_get(f"test_cmd:{self.db.get_job(jid)['project']}")
        if not cmd:
            return None, "Chưa cấu hình lệnh test cho dự án."
        r = subprocess.run(cmd, shell=True, cwd=pdir, capture_output=True, text=True,
                           timeout=self.cfg["limits"]["timeout_sec"])
        self.db.event(jid, "tests", "tests", f"exit={r.returncode}")
        return r.returncode == 0, (r.stdout + r.stderr)[-4000:]

    def _execute(self, jid):
        job = self.db.get_job(jid)
        pdir = self._project_dir(job)
        lim = self.cfg["limits"]
        plan = (job["plan"] or "")
        ck = gitops.checkpoint(pdir, jid)
        if not ck["ok"]:
            self.db.set_status(jid, "BLOCKED", result=f"Không tạo được checkpoint: {ck['error']}")
            return
        self.db.kv_set(f"ckpt:{jid}", ck["tag"])
        self.db.set_status(jid, "RUNNING")
        ex = self._agent("code", job["request"])
        task = f"Thực hiện kế hoạch sau trong thư mục hiện tại, không sửa .env/credential.\n{plan}\nYêu cầu gốc: {job['request']}"
        for rnd in range(lim["max_fix_rounds"] + 1):
            res = ex.run(task, pdir, lim["timeout_sec"], "code")
            self.db.add_run(jid, res)
            if self._cancelled(jid):
                return
            if not res["ok"]:
                self.db.set_status(jid, "FAILED", result=f"Executor {ex.name} lỗi: {res['error']}")
                return
            tests_ok, tests_out = self._run_tests(jid, pdir)
            self.db.set_status(jid, "REVIEWING")
            diff = gitops.diff(pdir, ck["tag"])
            role = "hard" if rnd >= 2 else "review"
            rv = self._agent(role)
            rres = rv.run("Rà soát diff: lỗi logic, lỗi bảo mật (injection, lộ secret, quyền truy cập), hiệu năng, và có làm sai yêu cầu không. "
                          "Dòng đầu BẮT BUỘC: 'VERDICT: PASS' hoặc 'VERDICT: FAIL', sau đó liệt kê lỗi (file, nguyên nhân, mức độ, cách sửa)."
                          f"\n\nYêu cầu: {job['request']}\n"
                          f"Test: {tests_out}\nDiff:\n{diff[-12000:]}", pdir, lim["timeout_sec"], role)
            self.db.add_run(jid, rres)
            verdict = parse_verdict(rres["stdout"]) if rres["ok"] else "UNKNOWN"
            if tests_ok and verdict == "PASS":
                break
            if rnd == lim["max_fix_rounds"]:
                self.db.set_status(jid, "FAILED", result=f"Còn lỗi sau {rnd} vòng sửa. tests_ok={tests_ok} verdict={verdict}")
                return
            task = f"Sửa các lỗi sau trong dự án:\nTest: {tests_out}\nReview:\n{rres['stdout']}"
            self.db.set_status(jid, "RUNNING")
        vf = self._agent("verify")
        vres = vf.run("Kiểm định độc lập thay đổi so với yêu cầu. Dòng đầu: 'VERDICT: PASS' hoặc 'VERDICT: FAIL'.\n"
                      f"Yêu cầu: {job['request']}\nDiff:\n{gitops.diff(pdir, ck['tag'])[-12000:]}", pdir, lim["timeout_sec"], "verify")
        self.db.add_run(jid, vres)
        if vres["ok"] and parse_verdict(vres["stdout"]) == "PASS" and tests_ok:
            self.db.set_status(jid, "DONE", result=f"Test OK, review PASS, kiểm định PASS. File: {gitops.changed_files(pdir, ck['tag'])}")
        else:
            self.db.set_status(jid, "FAILED", result=f"Kiểm định không đạt: {vres['error'] or parse_verdict(vres['stdout'])}")
