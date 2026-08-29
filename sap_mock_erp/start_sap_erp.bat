@echo off
title SAP Mock ERP Server
color 0B
echo =====================================================
echo    SAP Mock ERP - VST Plant 1000
echo =====================================================
echo.
echo    Starting SAP ECC Mock on port 8001...
echo    Web UI: http://localhost:8001
echo    API Docs: http://localhost:8001/docs
echo.

set ROOT=%~dp0
set PYTHON=%ROOT%..\backend\venv\Scripts\python.exe

if not exist "%PYTHON%" (
    echo    Using system Python...
    python "%ROOT%run_sap_erp.py"
) else (
    "%PYTHON%" "%ROOT%run_sap_erp.py"
)

pause
