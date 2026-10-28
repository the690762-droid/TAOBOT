"""Adapter CLI chung: kiểm tra cài đặt, chạy subprocess có timeout, hủy, chuẩn hóa kết quả.
Chạy được cả Windows và Linux: không dùng shell, dùng đường dẫn đầy đủ từ shutil.which."""
import os
import shutil
import signal
import subprocess
import threading
import time

IS_WIN = os.name == "nt"


def spawn_kwargs():
    # Tạo nhóm tiến trình riêng để kill được cả cây tiến trình con.
    if IS_WIN:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def child_env():
    # Không truyền token Telegram hay biến TELEGRAM_* cho tiến trình con (agent có thể bị prompt-inject).
    return {k: v for k, v in os.environ.items() if not k.startswith("TELEGRAM_")}


def kill_tree(proc):
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


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
        argv = [a.replace("{prompt}", prompt) for a in self.command]
        # Trên Windows, CLI thường là claude.cmd: dùng đường dẫn đã resolve để Popen chạy được.
        resolved = shutil.which(self.binary)
        if resolved:
            argv[0] = resolved
        return argv

    def cancel(self):
        self._cancelled.set()
        p = self._proc
        if p and p.poll() is None:
            kill_tree(p)

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
            self._proc = subprocess.Popen(self.build(prompt), cwd=str(cwd), stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                          errors="replace", env=child_env(), **spawn_kwargs())
            if self._cancelled.is_set():
                kill_tree(self._proc)
            out, err = self._proc.communicate(timeout=timeout)
            res.update(stdout=out, stderr=err, exit_code=self._proc.returncode)
            res["ok"] = self._proc.returncode == 0 and not self._cancelled.is_set()
            if self._cancelled.is_set():
                res["error"] = "cancelled"
            elif not res["ok"]:
                res["error"] = f"exit_code_{self._proc.returncode}"
        except subprocess.TimeoutExpired:
            kill_tree(self._proc)
            out, err = self._proc.communicate()
            res.update(stdout=out or "", stderr=err or "", error="timeout")
        except OSError as e:
            res["error"] = f"spawn_failed: {e}"
        finally:
            self._proc = None
            res["duration"] = round(time.time() - t0, 3)
        return res
