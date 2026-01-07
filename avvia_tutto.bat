@echo off
SETLOCAL EnableDelayedExpansion
TITLE AI Health Navigator - Suite Integrata v2.0

:: Configurazione percorsi
cd /d "%~dp0"

echo ======================================================
echo    AI HEALTH NAVIGATOR - BOOTSTRAP SYSTEM
echo ======================================================
echo.

:: 1. Verifica Ambiente Virtuale
echo [1/3] Verifica ambiente virtuale...
if not exist ".venv\Scripts\activate" (
echo [ERRORE] Ambiente virtuale non trovato in .venv.
echo Assicurati di aver creato l'ambiente con: python -m venv .venv
pause
exit /b
)
call .venv\Scripts\activate

:: 2. Avvio Backend Analytics
echo [2/3] Avvio ANALYTICS ENGINE (Porta 8502)...
:: Headless true impedisce l'apertura automatica del browser per il backend
start "HealthNavigator - Backend" /min cmd /c "streamlit run backend.py --server.port 8502 --server.headless true --browser.gatherUsageStats false"

:: 3. Avvio Frontend Triage
echo [3/3] Avvio CLINICAL FRONTEND (Porta 8501)...
:: Nota: Utilizzo frontend.py come entry point principale identificato nell'analisi
start "HealthNavigator - Frontend" cmd /c "streamlit run frontend.py --server.port 8501 --browser.gatherUsageStats false"

echo.
echo ------------------------------------------------------
echo    SERVIZI IN FASE DI CARICAMENTO...
echo ------------------------------------------------------
echo    - Interfaccia Paziente: http://localhost:8501
echo    - Dashboard Strategica: http://localhost:8502
echo ------------------------------------------------------
echo.
echo Suggerimento: Se il browser non si apre entro 10 secondi,
echo copia e incolla i link sopra nella barra degli indirizzi.
echo.
echo Premi un tasto per terminare questo monitor (i server resteranno attivi).
pause > nul