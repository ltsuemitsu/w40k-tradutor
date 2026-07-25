@echo off
setlocal

:: =====================================================
:: W40K Translator - Nova GUI (Fase 1)
:: Thin wrapper: delega para o launcher PowerShell
:: (launch_translator.ps1), que ja trata venv, py -3,
:: dependencias e pythonw corretamente.
:: =====================================================

cd /d "%~dp0"

echo.
echo ================================================
echo   W40K TRANSLATOR
echo   Warhammer 40k Grimdark Translation Tool
echo ================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_translator.ps1"

if %errorlevel% neq 0 (
    echo.
    echo ================================================
    echo O launcher encerrou com erro.
    echo Verifique as mensagens acima.
    echo ================================================
    pause
)

endlocal
exit /b 0
