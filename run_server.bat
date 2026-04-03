@echo off
chcp 65001 >nul
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo   AI Trading Assistant v3.0
echo   Starting server on http://localhost:5000
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo.

REM Claude Vision OCR용 API 키 (https://console.anthropic.com 에서 발급)
REM 아래 줄의 REM을 제거하고 실제 키를 입력하세요
REM set ANTHROPIC_API_KEY=sk-ant-여기에키입력

REM Python 경로 자동 탐색
where python >nul 2>&1
if %errorlevel% equ 0 (
    python "%~dp0app.py"
) else (
    "C:\Users\DIT-969\AppData\Local\Python\pythoncore-3.14-64\python.exe" "%~dp0app.py"
)

pause
