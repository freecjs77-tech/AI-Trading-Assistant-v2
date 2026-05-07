@echo off
chcp 65001 >nul
echo Running test...
echo.

where python >nul 2>&1
if %errorlevel% equ 0 (
    python "%~dp0_test_new_conditions.py"
) else (
    "C:\Users\DIT-969\AppData\Local\Python\pythoncore-3.14-64\python.exe" "%~dp0_test_new_conditions.py"
)

echo.
pause
