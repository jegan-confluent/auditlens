@echo off
REM AuditLens setup stub for Windows users who don't yet have WSL2.
REM The real wizard is the bash `setup` script in the repo root; it
REM cannot run from CMD or PowerShell directly. This stub steers users
REM to WSL2 (the supported path) and exits.
echo.
echo AuditLens requires WSL2 or Git Bash on Windows.
echo Please install WSL2 and run setup from an Ubuntu terminal.
echo.
echo Quick setup:
echo   1. Install WSL2: wsl --install (run in PowerShell as Admin)
echo   2. Open Ubuntu from Start Menu
echo   3. Clone and run:
echo        git clone https://github.com/jegan-confluent/auditlens
echo        cd auditlens ^&^& ./setup
echo.
echo See: https://github.com/jegan-confluent/auditlens/blob/main/README.md
echo.
exit /b 1
