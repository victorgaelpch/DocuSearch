<#
.SYNOPSIS
  Comprueba la instalación y, si el servidor está en marcha, que responde. DOC-34.
#>
param([int]$Puerto = 8000)
# "Continue": en Windows PowerShell 5.1 la salida de error de pip/py no debe
# abortar el script; cada comando externo se comprueba con $LASTEXITCODE.
$ErrorActionPreference = "Continue"
$Raiz = Resolve-Path (Join-Path $PSScriptRoot "..\..") -ErrorAction Stop
Set-Location $Raiz -ErrorAction Stop
$venvPython = Join-Path $Raiz ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { throw "No hay .venv: ejecute scripts\windows\instalar.ps1" }
& $venvPython -m backend.app.cli doctor --port $Puerto
$codigo = $LASTEXITCODE
try {
  $salud = Invoke-RestMethod -Uri "http://127.0.0.1:$Puerto/health" -TimeoutSec 3
  Write-Host "Servidor en marcha: estado $($salud.status)" -ForegroundColor Green
} catch {
  Write-Host "El servidor no está en marcha en el puerto $Puerto (inícielo con scripts\windows\iniciar.ps1)."
}
exit $codigo
