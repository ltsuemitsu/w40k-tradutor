@echo off
setlocal enabledelayedexpansion

:: =====================================================
:: W40K: Rogue Trader - Tradutor GUI Launcher
:: Double-click this file to open the interactive GUI
:: =====================================================

cd /d "%~dp0"

echo.
echo ================================================
echo   W40K ROGUE TRADER - TRADUTOR (GUI)
echo   Warhammer 40k Grimdark Translation Tool
echo ================================================
echo.

:: Check for Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERRO] Python nao foi encontrado no PATH do sistema.
    echo.
    echo Solucoes:
    echo   1. Instale o Python 3.10 ou superior de https://www.python.org/downloads/
    echo      (IMPORTANTE: marque a opcao "Add Python to PATH" durante a instalacao)
    echo.
    echo   2. Reinicie o computador apos instalar e tente novamente.
    echo.
    pause
    exit /b 1
)

:: Try to find a virtual environment
set "PYTHON_CMD=python"

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_CMD=.venv\Scripts\python.exe"
    echo [INFO] Usando ambiente virtual: .venv
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON_CMD=venv\Scripts\python.exe"
    echo [INFO] Usando ambiente virtual: venv
) else if exist "env\Scripts\python.exe" (
    set "PYTHON_CMD=env\Scripts\python.exe"
    echo [INFO] Usando ambiente virtual: env
)

:: Check if PySide6 is available (quick import test)
echo Verificando dependencias...
%PYTHON_CMD% -c "import PySide6; print('PySide6 OK')" >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [AVISO] PySide6 nao esta instalado.
    echo Tentando instalar dependencias automaticamente...
    echo.
    
    %PYTHON_CMD% -m pip install -r requirements-gui.txt --quiet
    if %errorlevel% neq 0 (
        echo.
        echo [ERRO] Falha ao instalar as dependencias.
        echo.
        echo Por favor rode manualmente no terminal:
        echo     pip install -r requirements-gui.txt
        echo.
        echo Depois execute novamente este arquivo .bat
        echo.
        pause
        exit /b 1
    )
    echo [OK] Dependencias instaladas com sucesso.
)

:: Launch the GUI using pythonw (no console window flash for GUI app)
echo.
echo Iniciando a interface grafica...
echo (A janela do tradutor vai abrir em instantes)

%PYTHON_CMD%w tradutor_desktop.py

:: If pythonw failed (some environments), fallback to python
if %errorlevel% neq 0 (
    echo.
    echo [AVISO] Nao foi possivel usar pythonw. Tentando python normal...
    %PYTHON_CMD% tradutor_desktop.py
)

:: Only pause if there was an error so the window doesn't disappear immediately
if %errorlevel% neq 0 (
    echo.
    echo ================================================
    echo O programa encerrou com erro.
    echo Verifique as mensagens acima.
    echo ================================================
    pause
)

endlocal
exit /b 0
