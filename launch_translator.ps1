# W40K Translator - Nova GUI Launcher (PowerShell)
# Right-click -> Run with PowerShell or create a shortcut to this file
# Launches the project-centric GUI (w40k_translator.py)

# Do NOT use Stop globally for external commands, as Python tracebacks on stderr
# will be treated as fatal errors by PowerShell.
$ErrorActionPreference = "Continue"

# Go to the folder where this script is located
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

Write-Host ""
Write-Host "================================================" -ForegroundColor DarkYellow
Write-Host "   W40K TRANSLATOR" -ForegroundColor Yellow
Write-Host "   Warhammer 40k Grimdark Translation Tool" -ForegroundColor Yellow
Write-Host "================================================" -ForegroundColor DarkYellow
Write-Host ""

# Function to find best python executable + args
function Get-PythonInfo {
    # Check virtual environments first (common names)
    # Prefer pythonw.exe for GUI (no console flash)
    $venvCandidates = @(
        ".venv\Scripts\pythonw.exe",
        "venv\Scripts\pythonw.exe",
        "env\Scripts\pythonw.exe",
        ".venv\Scripts\python.exe",
        "venv\Scripts\python.exe",
        "env\Scripts\python.exe"
    )

    foreach ($v in $venvCandidates) {
        if (Test-Path $v) {
            Write-Host "[INFO] Usando ambiente virtual: $v" -ForegroundColor Cyan
            return @{ Exe = $v; Args = @() }
        }
    }

    # Try Windows Python launcher (py.exe) - handles multiple Python versions cleanly
    if (Get-Command py -ErrorAction SilentlyContinue) {
        Write-Host "[INFO] Usando Python Launcher (py -3)" -ForegroundColor Cyan
        return @{ Exe = "py"; Args = @("-3") }
    }

    # Fallback to python in PATH
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @{ Exe = "python"; Args = @() }
    }

    throw "Python nao encontrado. Instale Python 3.10+ (https://www.python.org/downloads/) e marque 'Add Python to PATH'."
}

$pyInfo = Get-PythonInfo
$pythonExe = $pyInfo.Exe
$pythonArgs = $pyInfo.Args

# Safe helper to invoke python and capture output + exit code without PowerShell treating tracebacks as fatal
function Invoke-PySafe {
    param([string[]]$extraArgs)

    $allArgs = $pythonArgs + $extraArgs

    # Capture both stdout and stderr
    $rawOutput = & $pythonExe $allArgs 2>&1

    $exitCode = $LASTEXITCODE

    # Return object with output and exit code
    [PSCustomObject]@{
        Output   = $rawOutput
        ExitCode = $exitCode
    }
}

# Check if PySide6 is available
Write-Host "Verificando dependencias do GUI..." -ForegroundColor Gray

$result = Invoke-PySafe @("-c", "import PySide6; print('OK')")

if ($result.ExitCode -ne 0) {
    Write-Host "[AVISO] PySide6 nao instalado (ou erro na checagem). Tentando instalar..." -ForegroundColor Yellow

    # Show the actual Python error for diagnostics (usually "ModuleNotFoundError")
    if ($result.Output) {
        Write-Host "Saida do Python:" -ForegroundColor DarkGray
        $result.Output | ForEach-Object { Write-Host "  $_" }
    }

    # Install
    Write-Host "Executando: pip install -r requirements-gui.txt" -ForegroundColor Cyan
    $installResult = Invoke-PySafe @("-m", "pip", "install", "-r", "requirements-gui.txt")

    if ($installResult.ExitCode -ne 0) {
        Write-Host ""
        Write-Host "[ERRO] Falha ao instalar as dependencias automaticamente." -ForegroundColor Red
        Write-Host ""
        Write-Host "Saida da instalacao:" -ForegroundColor DarkGray
        if ($installResult.Output) {
            $installResult.Output | ForEach-Object { Write-Host "  $_" }
        }
        Write-Host ""
        Write-Host "Por favor rode manualmente este comando no terminal (PowerShell ou CMD):" -ForegroundColor Yellow
        Write-Host "    py -3 -m pip install -r requirements-gui.txt" -ForegroundColor White
        Write-Host ""
        Write-Host "Depois de instalar, rode novamente o launcher." -ForegroundColor Yellow
        Read-Host "Pressione ENTER para sair"
        exit 1
    }

    Write-Host "[OK] Dependencias instaladas com sucesso." -ForegroundColor Green
} else {
    Write-Host "[OK] PySide6 ja esta instalado." -ForegroundColor Green
}

# Launch the GUI
Write-Host ""
Write-Host "Iniciando a interface grafica..." -ForegroundColor Green
Write-Host "(A janela do W40K Translator vai abrir em alguns segundos...)" -ForegroundColor Gray

# Build pythonw version to avoid console window
$pythonwExe = $pythonExe
$pythonwArgs = $pythonArgs

if ($pythonExe -eq "py") {
    $pythonwExe = "pyw"
    $pythonwArgs = @("-3")
} else {
    $pythonwExe = $pythonExe -replace "python", "pythonw"
}

try {
    # Launch GUI - we don't capture output here because the app opens its own window
    & $pythonwExe @pythonwArgs "w40k_translator.py"
} catch {
    Write-Host ""
    Write-Host "[AVISO] Falha ao iniciar com versao sem console (pythonw). Tentando versao normal..." -ForegroundColor Yellow
    & $pythonExe @pythonArgs "w40k_translator.py"
}

# Only reach here if the GUI process returned an error code
if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne $null) {
    Write-Host ""
    Write-Host "================================================" -ForegroundColor Red
    Write-Host "O programa terminou com codigo de erro: $LASTEXITCODE" -ForegroundColor Red
    Write-Host "Verifique as mensagens acima ou rode manualmente para mais detalhes:" -ForegroundColor Red
    Write-Host "    py -3 w40k_translator.py" -ForegroundColor White
    Write-Host "================================================" -ForegroundColor Red
    Read-Host "Pressione ENTER para fechar esta janela"
}
