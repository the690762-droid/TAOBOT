@echo off
rem Cài đặt và chạy Ryan AI Command Center trên Windows. Chạy lại an toàn: bước đã xong sẽ được bỏ qua.
setlocal EnableExtensions
cd /d "%~dp0"
title Ryan AI Command Center - Cai dat

echo [1/5] Kiem tra Python 3.10 tro len...
set "PY="
where py >nul 2>nul && py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo Khong tim thay Python 3.10 tro len.
  echo Tai tai https://www.python.org/downloads/ va tick "Add python.exe to PATH" khi cai.
  goto :fail
)
echo      Dung: %PY%

echo [2/5] Tao moi truong ao .venv...
if not exist ".venv\Scripts\python.exe" (
  %PY% -m venv .venv || goto :fail
) else (
  echo      Da co .venv, bo qua.
)
set "VPY=%~dp0.venv\Scripts\python.exe"

echo [3/5] Cai thu vien trong requirements.txt...
"%VPY%" -m pip install --quiet --upgrade pip || goto :fail
"%VPY%" -m pip install --quiet -r requirements.txt || goto :fail

echo [4/5] Kiem tra file .env...
if not exist ".env" (
  copy /y ".env.example" ".env" >nul || goto :fail
  echo      Da tao .env tu .env.example.
  echo      Mo file .env va dien TELEGRAM_BOT_TOKEN va TELEGRAM_ALLOWED_USER_IDS, roi chay lai file nay.
  pause
  exit /b 0
)

echo [5/5] Khoi dong. Nhan Ctrl+C de dung.
"%VPY%" main.py
goto :end

:fail
echo.
echo Cai dat that bai. Xem thong bao loi phia tren, sua va chay lai.
pause
exit /b 1

:end
pause
