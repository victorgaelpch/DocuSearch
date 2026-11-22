<#
.SYNOPSIS
  Inicia DocuSearch en http://127.0.0.1 y abre el navegador. DOC-34.
.DESCRIPTION
  Escucha solo en 127.0.0.1 (esta computadora). Para detenerlo pulse Ctrl+C.
.PARAMETER Puerto
  Puerto local (8000 por defecto).
.PARAMETER NoAbrir
  No abrir el navegador.
#>
param([int]$Puerto = 8000, [switch]$NoAbrir)
# "Continue": en Windows PowerShell 5.1 la salida de error de pip/py no debe
# abortar el script; cada comando externo se comprueba con $LASTEXITCODE.
$ErrorActionPreference = "Continue"
$Raiz = Resolve-Path (Join-Path $PSScriptRoot "..\..") -ErrorAction Stop
Set-Location $Raiz -ErrorAction Stop
$venvPython = Join-Path $Raiz ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { throw "Primero ejecute scripts\windows\instalar.ps1" }

& $venvPython -m backend.app.cli doctor --port $Puerto
if ($LASTEXITCODE -ne 0) {
  Write-Host "Corrija lo marcado con [ERR] antes de iniciar (por ejemplo, scripts\windows\configurar-cuenta.ps1)." -ForegroundColor Yellow
  exit 1
}
$url = "http://127.0.0.1:$Puerto/"
if (-not $NoAbrir) {
  Start-Job -ScriptBlock { param($u) Start-Sleep -Seconds 4; Start-Process $u } -ArgumentList $url | Out-Null
}
Write-Host "DocuSearch en $url (Ctrl+C para detener)" -ForegroundColor Green
& $venvPython -m uvicorn backend.app.main:app --host 127.0.0.1 --port $Puerto
