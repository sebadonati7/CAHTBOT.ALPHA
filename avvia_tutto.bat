@echo off
TITLE AI Health Navigator - Avvio Integrato
cd /d "%~dp0"

echo [1/3] Attivazione ambiente virtuale...
call .venv\Scripts\activate

echo [2/3] Avvio BACKEND (Porta 8502)...
start "Backend - Analytics" /min cmd /c "streamlit run backend.py --server.port 8502 --server.headless true --browser.gatherUsageStats false"

echo [3/3] Avvio FRONTEND (Porta 8501)...
start "Frontend - Triage" cmd /c "streamlit run test_frontend.py --server.port 8501 --browser.gatherUsageStats false"

echo.
echo ======================================================
echo   SISTEMA AVVIATO CON SUCCESSO
echo ======================================================
echo   Frontend: http://localhost:8501
echo   Backend:  http://localhost:8502
echo ======================================================
echo.
echo Premi un tasto per chiudere questa finestra (i server rimarranno attivi).
pause > nul