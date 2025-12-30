@echo off
SETLOCAL ENABLEDELAYEDEXPANSION
TITLE AI Healthcare Navigator - Deep Repair Launcher
COLOR 0B

echo =======================================================
echo    AI HEALTHCARE NAVIGATOR - DIAGNOSTIC LAUNCHER
echo =======================================================

:: 1. FORZA L'USO DI PYTHON 3.12
echo [INFO] Verifica installazione Python 3.12...
py -3.12 --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
echo [ERRORE] Python 3.12 non trovato.
echo Assicurati di averlo installato e che sia nel PATH.
pause
exit /b 1
)

:: 2. PULIZIA AMBIENTE SE CORROTTO
:: Se vedi ancora l'errore pyarrow, cancella manualmente la cartella .venv prima di avviare
if not exist .venv (
echo [INFO] Creazione ambiente virtuale isolato...
py -3.12 -m venv .venv
)

:: 3. ATTIVAZIONE E RIPARAZIONE FORZATA
echo [INFO] Attivazione ambiente e installazione pulita...
call .venv\Scripts\activate

:: Aggiornamento PIP
python -m pip install --upgrade pip -q

:: DISINSTALLAZIONE COMPLETA DEI MODULI PROBLEMATICI
echo [INFO] Rimozione librerie per pulizia profonda...
python -m pip uninstall pyarrow plotly pandas narwhals -y >nul 2>&1

:: INSTALLAZIONE IN ORDINE DI DIPENDENZA (Cruciale per evitare circular imports)
echo [INFO] Installazione in corso (fase 1: Core)...
python -m pip install numpy==1.26.4 pandas --no-cache-dir -q

echo [INFO] Installazione in corso (fase 2: Streamlit & AI)...
python -m pip install streamlit google-generativeai xlsxwriter --no-cache-dir -q

echo [INFO] Installazione in corso (fase 3: Grafica e Fix PyArrow)...
:: Installiamo una versione di pyarrow compatibile con i binari Windows di Python 3.12
python -m pip install pyarrow==15.0.0 plotly --no-cache-dir -q

:: 4. PREPARAZIONE LOG
if not exist triage_logs.jsonl (
echo. > triage_logs.jsonl
)

:: 5. AVVIO MODULI
set CHAT_PORT=8501
set DASH_PORT=8502

echo.
echo [SUCCESSO] Ambiente ricostruito.
echo [INFO] Avvio Chatbot: http://localhost:%CHAT_PORT%
start "Chatbot" cmd /k "call .venv\Scripts\activate && streamlit run frontend.py --server.port=%CHAT_PORT%"

timeout /t 5 >nul

echo [INFO] Avvio Analytics: http://localhost:%DASH_PORT%
:: Disabilitiamo il monitoraggio dei file per evitare blocchi DLL durante l'uso
start "Analytics" cmd /k "call .venv\Scripts\activate && streamlit run backend.py --server.port=%DASH_PORT% --server.fileWatcherType none"

echo =======================================================
echo    SISTEMA RIPRISTINATO
echo    Se l'errore "pyarrow" persiste nel browser:
echo    CANCELLA la cartella ".venv" e riavvia questo file.
echo =======================================================
pause