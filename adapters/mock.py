"""Agent giả lập cho MOCK_MODE. Kết quả luôn đánh dấu mock để không bị nhầm với kết quả thật."""
from adapters.base import CLIAdapter

REPLIES = {
    "plan": "[MOCK] 1. Phân tích yêu cầu\n2. Sửa các file liên quan\nTiêu chí: test PASS",
    "review": "VERDICT: PASS\n[MOCK] Không phát hiện lỗi.",
    "hard": "VERDICT: PASS\n[MOCK] Không phát hiện lỗi.",
    "verify": "VERDICT: PASS\n[MOCK] Kiểm định đạt.",
}


class MockAdapter(CLIAdapter):
    def installed(self):
        return True

    def status(self):
        if not self.enabled:
            return "disabled"
        return "mock"

    def run(self, prompt, cwd, timeout=900, role=None):
        out = REPLIES.get(role, "[MOCK] Đã thực hiện (không sửa file).")
        return {"agent": self.name, "role": role, "ok": True, "exit_code": 0, "duration": 0.0,
                "stdout": out, "stderr": "", "error": None}
