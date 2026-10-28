"""Orchestrator: nhận việc -> kế hoạch -> duyệt -> thực thi -> test -> review -> sửa (tối đa 3 vòng) -> kiểm định.
Một worker duy nhất xử lý hàng đợi nên không có hai executor cùng sửa một workspace."""
import queue
import shlex
import subprocess
import threading
from pathlib import Path

from adapters.base import child_env, kill_tree, spawn_kwargs
from quality import gitops, safety

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "artifacts"
SMALL_HINTS = ("log", "giải thích", "tóm tắt", "explain", "summarize", "typo")
ACTIVE = ("NEW", "PLANNING", "AWAITING_APPROVAL", "APPROVED", "RUNNING", "REVIEWING")
TERMINAL = ("DONE", "FAILED", "CANCELLED")


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

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    # ---------- API ----------
    def new_job(self, request, project=None, source="desktop"):
        return self.db.create_job(request, project, source)

    def _notify(self, jid, msg):
        try:
            self.notify(jid, msg)
        except Exception:  # Telegram lỗi mạng không được làm chết worker
            pass

    def _seal(self, jid, pdir):
        """Ghi mốc HEAD và fingerprint để rollback biết tree có bị người dùng sửa sau lần chạy không."""
        self.db.kv_set(f"post:{jid}", gitops.head(pdir) or "")
        self.db.kv_set(f"fp:{jid}", gitops.fingerprint(pdir))

    def _say(self, jid, agent, kind, msg):
        self.db.event(jid, agent, kind, msg)
        self._notify(jid, f"[{agent}] {msg}")

    def _agent(self, role, request=""):
        name = self.cfg["routes"][role]
        if role == "code" and any(h in request.lower() for h in SMALL_HINTS):
            name = self.cfg["routes"]["small"]
        return self.ad[name]

    def _project_dir(self, job):
        for p in self.db.projects():
            if p["name"] == job["project"]:
                return Path(p["path"])
        return None

    def plan(self, jid):
        job = self.db.get_job(jid)
        if not job or job["status"] not in ("NEW", "BLOCKED"):
            return False
        pdir = self._project_dir(job)
        if not pdir or safety.validate_project(pdir):
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
        self.db.set_status(jid, "AWAITING_APPROVAL", plan={"text": safety.redact(res["stdout"]), "level": level})
        self._say(jid, ag.name, "plan", f"Kế hoạch sẵn sàng (cấp quyền {level}).")
        return True

    def approve(self, jid, confirm=False):
        """Cấp 3 (rủi ro) bắt buộc confirm=True riêng, không duyệt ngầm cùng lượt."""
        job = self.db.get_job(jid)
        if not job or job["status"] != "AWAITING_APPROVAL":
            return "not_awaiting"
        level = json_level(job["plan"])
        if level >= 3 and not confirm:
            return "needs_confirm"
        return "approved" if self.db.set_status(jid, "APPROVED") else "not_awaiting"

    def run(self, jid):
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
        job = self.db.get_job(jid)
        if not job or job["status"] not in ACTIVE:
            return False
        if self.db.set_status(jid, "CANCELLED"):
            for a in self.ad.values():
                a.cancel()
        return True

    def rollback(self, jid):
        job = self.db.get_job(jid)
        if not job or job["status"] not in TERMINAL:
            return {"ok": False, "error": "job_still_active"}
        ck, post, fp = (self.db.kv_get(f"{k}:{jid}") for k in ("ckpt", "post", "fp"))
        pdir = self._project_dir(job)
        if not ck or not post or not fp or not pdir:
            return {"ok": False, "error": "no_checkpoint"}
        if any(j["id"] != jid and j["status"] in ACTIVE for j in self.db.list_jobs(500) if j["project"] == job["project"]):
            return {"ok": False, "error": "another_job_active_in_project"}
        return gitops.rollback(pdir, ck, post, fp)

    # ---------- worker ----------
    def _loop(self):
        while True:
            jid = self.q.get()
            with self.lock:
                self.queued.discard(jid)
                self.current = jid
            try:
                self._execute(jid)
            except Exception as e:  # worker không được chết
                self.db.set_status(jid, "FAILED", result=f"Lỗi nội bộ: {e!r}")
            finally:
                job = self.db.get_job(jid)
                self._notify(jid, f"Kết thúc: {job['status']}. {job['result'] or ''}")
                with self.lock:
                    self.current = None

    def _stopped(self, jid):
        return self.db.get_job(jid)["status"] == "CANCELLED"

    def _run_tests(self, jid, pdir):
        cmd = self.db.kv_get(f"test_cmd:{self.db.get_job(jid)['project']}")
        argv = shlex.split(cmd, posix=True)  # không dùng shell
        timeout = self.cfg["limits"]["timeout_sec"]
        p = subprocess.Popen(argv, cwd=str(pdir), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace", env=child_env(), **spawn_kwargs())
        try:
            out, _ = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_tree(p)
            out, _ = p.communicate()
            return False, f"timeout\n{out or ''}"[-4000:]
        self.db.event(jid, "tests", "tests", f"exit={p.returncode}")
        return p.returncode == 0, out[-4000:]

    def _save_artifacts(self, jid, diff_text):
        d = ARTIFACTS / jid
        d.mkdir(parents=True, exist_ok=True)
        (d / "diff.patch").write_text(safety.redact(diff_text), encoding="utf-8")
        log = "\n".join(f"{e['agent']}/{e['kind']}: {e['message']}" for e in self.db.events(jid, 500))
        (d / "log.txt").write_text(safety.redact(log), encoding="utf-8")

    def _execute(self, jid):
        job = self.db.get_job(jid)
        if job["status"] != "APPROVED":  # đã bị hủy khi còn trong hàng đợi
            return
        pdir = self._project_dir(job)
        if not pdir or safety.validate_project(pdir):
            self.db.set_status(jid, "BLOCKED", result="Dự án không hợp lệ hoặc đã bị đổi đường dẫn.")
            return
        if not self.db.kv_get(f"test_cmd:{job['project']}"):
            self.db.set_status(jid, "BLOCKED", result="Chưa cấu hình lệnh test cho dự án (test_cmd).")
            return
        ck = gitops.checkpoint(pdir, jid)
        if not ck["ok"]:
            self.db.set_status(jid, "BLOCKED", result=f"Không tạo được checkpoint: {ck['error']}")
            return
        self.db.kv_set(f"ckpt:{jid}", ck["tag"])
        if not self.db.set_status(jid, "RUNNING"):
            return
        lim = self.cfg["limits"]
        ex = self._agent("code", job["request"])
        task = (f"Thực hiện kế hoạch sau trong thư mục hiện tại, không sửa .env hay credential.\n"
                f"{job['plan'] or ''}\nYêu cầu gốc: {job['request']}")
        tests_ok, tests_out = False, ""
        for rnd in range(lim["max_fix_rounds"] + 1):
            res = ex.run(task, pdir, lim["timeout_sec"], "code")
            self.db.add_run(jid, res)
            self._seal(jid, pdir)
            if self._stopped(jid):
                return
            if not res["ok"]:
                self.db.set_status(jid, "FAILED", result=f"Executor {ex.name} lỗi: {res['error']}")
                return
            tests_ok, tests_out = self._run_tests(jid, pdir)
            if self._stopped(jid) or not self.db.set_status(jid, "REVIEWING"):
                return
            diff_text = gitops.diff(pdir, ck["tag"])
            role = "hard" if rnd >= 2 else "review"
            rv = self._agent(role)
            rres = rv.run("Rà soát diff: lỗi logic, lỗi bảo mật (injection, lộ secret, quyền truy cập), hiệu năng, "
                          "và có làm sai yêu cầu không. Dòng đầu BẮT BUỘC: 'VERDICT: PASS' hoặc 'VERDICT: FAIL', "
                          "sau đó liệt kê lỗi (file, nguyên nhân, mức độ, cách sửa).\n\n"
                          f"Yêu cầu: {job['request']}\nTest: {tests_out}\nDiff:\n{diff_text[-12000:]}",
                          pdir, lim["timeout_sec"], role)
            self.db.add_run(jid, rres)
            verdict = parse_verdict(rres["stdout"]) if rres["ok"] else "UNKNOWN"
            if tests_ok and verdict == "PASS":
                break
            if rnd == lim["max_fix_rounds"]:
                self.db.set_status(jid, "FAILED", result=f"Còn lỗi sau {rnd} vòng sửa. tests_ok={tests_ok} verdict={verdict}")
                return
            task = f"Sửa các lỗi sau trong dự án:\nTest: {tests_out}\nReview:\n{rres['stdout']}"
            if not self.db.set_status(jid, "RUNNING"):
                return
        vf = self._agent("verify")
        vres = vf.run("Kiểm định độc lập thay đổi so với yêu cầu. Dòng đầu: 'VERDICT: PASS' hoặc 'VERDICT: FAIL'.\n"
                      f"Yêu cầu: {job['request']}\nDiff:\n{gitops.diff(pdir, ck['tag'])[-12000:]}",
                      pdir, lim["timeout_sec"], "verify")
        self.db.add_run(jid, vres)
        self._seal(jid, pdir)
        files = gitops.changed_files(pdir, ck["tag"])
        self._save_artifacts(jid, gitops.diff(pdir, ck["tag"]))
        if self._stopped(jid):
            return
        if vres["ok"] and parse_verdict(vres["stdout"]) == "PASS" and tests_ok:
            self.db.set_status(jid, "DONE", result=f"Test OK, review PASS, kiểm định PASS. File: {files}")
        else:
            self.db.set_status(jid, "FAILED", result=f"Kiểm định không đạt: {vres['error'] or parse_verdict(vres['stdout'])}")


def json_level(plan):
    import json
    try:
        return int(json.loads(plan)["level"])
    except (TypeError, ValueError, KeyError):
        return 3  # không đọc được cấp quyền thì coi là rủi ro
