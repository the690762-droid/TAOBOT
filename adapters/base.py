"""Adapter CLI chung: kiểm tra cài đặt, chạy subprocess có timeout, hủy, chuẩn hóa kết quả."""
import os
import shutil
import signal
import subprocess
import threading
import time


class CLIAdapter:
    def __init__(self, name, cfg):
        self.name = name
        self.label = cfg.get("label", name)
        self.enabled = cfg.get("enabled", True)
        self.binary = cfg["binary"]
        self.command = cfg["command"]
        self._proc = None
        self._cancelled = threading.Event()

    def installed(self):
        return shutil.which(self.binary) is not None

    def status(self):
        if not self.enabled:
            return "disabled"
        return "ready" if self.installed() else "not_installed"

    def build(self, prompt):
        return [a.replace("{prompt}", prompt) for a in self.command]

    def cancel(self):
        self._cancelled.set()
        p = self._proc
        if p and p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass

    def run(self, prompt, cwd, timeout=900, role=None):
        """Trả về dict chuẩn hóa: agent, role, ok, exit_code, duration, stdout, stderr, error."""
        t0 = time.time()
        res = {"agent": self.name, "role": role, "ok": False, "exit_code": None,
               "duration": 0.0, "stdout": "", "stderr": "", "error": None}
        if not self.enabled:
            res["error"] = "agent_disabled"
            return res
        if not self.installed():
            res["error"] = f"cli_not_installed: {self.binary}"
            return res
        self._cancelled.clear()
        try:
            # start_new_session để có thể kill cả nhóm tiến trình khi timeout/hủy; không dùng shell.
            self._proc = subprocess.Popen(self.build(prompt), cwd=cwd, stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE, text=True, start_new_session=True)
            out, err = self._proc.communicate(timeout=timeout)
            res.update(stdout=out, stderr=err, exit_code=self._proc.returncode)
            res["ok"] = self._proc.returncode == 0 and not self._cancelled.is_set()
            if self._cancelled.is_set():
                res["error"] = "cancelled"
            elif not res["ok"]:
                res["error"] = f"exit_code_{self._proc.returncode}"
        except subprocess.TimeoutExpired:
            try:
                os.killpg(self._proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            out, err = self._proc.communicate()
            res.update(stdout=out or "", stderr=err or "", error="timeout")
        except OSError as e:
            res["error"] = f"spawn_failed: {e}"
        finally:
            self._proc = None
            res["duration"] = round(time.time() - t0, 3)
        return res
