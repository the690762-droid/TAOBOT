# Ryan AI Command Center (MVP)

Điều phối AI qua Telegram và giao diện web cục bộ. Orchestrator tạo công việc, lập kế hoạch, chờ duyệt, chạy executor, test, review, kiểm định và checkpoint Git để khôi phục.

## Trạng thái thật (đã kiểm chứng trong môi trường build)
- Đã chạy: 14 unit test (`python -m unittest discover -s tests -t .`) đều PASS; giao diện và API khởi động, trả về HTTP 200.
- Đã có CLI thật trên máy build: `claude` (Claude Code 2.1.312). Haiku, Sonnet, Opus, Claude Code đều đi qua `claude -p --model ...`.
- **Chưa kiểm thử thật:** Telegram (cần token của bạn), Antigravity và OpenCode (CLI chưa cài trên máy build, cấu hình lệnh là mẫu chưa xác minh), Electron (chưa đóng gói, giao diện hiện là trang HTML phục vụ bởi Python).

## Cài đặt trên Windows
1. Cài Python 3.11+, Git, Node.js (nếu dùng Claude Code CLI: `npm i -g @anthropic-ai/claude-code`).
2. Đăng nhập CLI: chạy `claude` một lần để xác thực.
3. Sao chép `.env.example` thành `.env`, điền `TELEGRAM_BOT_TOKEN` (từ @BotFather) và `TELEGRAM_ALLOWED_USER_IDS` (ID của bạn).
4. Kiểm tra CLI: `python -c "from adapters.registry import *; print({n:a.status() for n,a in build_adapters(load_config()).items()})"`.

## Chạy
- Khởi chạy: `python main.py` rồi mở http://127.0.0.1:8765
- Dừng: Ctrl+C.
- Khôi phục: nút "Khôi phục checkpoint" trên giao diện hoặc `/rollback` trên Telegram. Checkpoint là tag `ryan-ckpt-<job>` tạo trước khi sửa; dự án phải là git repo và sạch (không có thay đổi chưa commit).

## Cấu hình tuyến
`config/agents.json`: `routes` chọn agent cho từng vai trò, `agents.*.command` là lệnh thực tế, `enabled` bật/tắt. Hiện tuyến: Haiku làm executor chính, Sonnet rà soát lỗi và bảo mật, Opus cho lỗi khó, Claude Code kiểm định cuối.

## Ghi chú an toàn
- Bot chỉ phản hồi user ID trong `TELEGRAM_ALLOWED_USER_IDS`, kể cả với nút inline.
- API chỉ bind 127.0.0.1.
- Không ghi `.env`, token hay credential vào log; `.env` đã nằm trong `.gitignore`.
- Yêu cầu có từ khóa rủi ro (xóa, production, token, quản trị) được gắn cấp quyền 3 để phải duyệt.

## Chạy Telegram trên máy của bạn (chế độ thật)
Sandbox của hệ thống không kết nối được api.telegram.org (proxy chặn), nên bot phải chạy trên máy của bạn:
1. Lấy user ID số của bạn từ @userinfobot trên Telegram.
2. Mở `.env` (tạo từ `.env.example`), điền `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_IDS=<user ID>`, `MOCK_MODE=false`.
3. Chạy `python main.py`. Dòng đầu phải báo "Telegram: đang lắng nghe".
4. Mở chat với bot và gửi yêu cầu bằng tiếng Việt. Bot sẽ lập kế hoạch và hiện nút Duyệt hoặc Hủy.
5. Dự án phải được thêm trước trong giao diện desktop (hoặc chỉ có một dự án thì bot tự chọn).

Nếu token đã gửi trong khung chat, hãy thu hồi và tạo token mới bằng /revoke trong @BotFather, rồi cập nhật `.env`.
