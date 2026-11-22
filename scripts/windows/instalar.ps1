<#
.SYNOPSIS
  Instala DocuSearch en un entorno virtual local (Windows, sin GPU). DOC-34.
.DESCRIPTION
  Crea .venv, instala el proyecto con el modelo de spaCy en español y, si se
  pide, la búsqueda semántica en versión CPU. No cambia la política de
  ejecución del sistema: ejecútelo con
    powershell -ExecutionPolicy Bypass -File scripts\windows\instalar.ps1
  (Bypass afecta solo a ese proceso).
.PARAMETER Semantico
  Instala también PyTorch CPU, sentence-transformers y FAISS (~1 GB; el
  modelo de embeddings, ~460 MB, se descarga en la primera búsqueda semántica).
.PARAMETER Desarrollo
  Instala las herramientas de pruebas (pytest y Playwright).
#>
param(
  [switch]$Semantico,
  [switch]$Desarrollo
)
# "Continue": en Windows PowerShell 5.1 la salida de error de pip/py no debe
# abortar el script; cada comando externo se comprueba con $LASTEXITCODE.
$ErrorActionPreference = "Continue"
$Raiz = Resolve-Path (Join-Path $PSScriptRoot "..\..") -ErrorAction Stop
Set-Location $Raiz -ErrorAction Stop

function Invocar([string]$Archivo, [string[]]$Argumentos) {
  & $Archivo @Argumentos
  if ($LASTEXITCODE -ne 0) { throw "Falló: $Archivo $($Argumentos -join ' ') (código $LASTEXITCODE)" }
}

function Buscar-Python {
  foreach ($version in @("3.12", "3.11", "3.10")) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
      $ruta = & py "-$version" -c "import sys; print(sys.executable)" 2>$null
      if ($LASTEXITCODE -eq 0 -and $ruta) { return $ruta.Trim() }
    }
  }
  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python) {
    $ok = & $python.Source -c "import sys; print(sys.version_info >= (3, 10))" 2>$null
    if ($ok -eq "True") { return $python.Source }
  }
  throw "No se encontró Python 3.10 o superior. Instálelo desde https://www.python.org/downloads/ (marque 'Add python.exe to PATH') y vuelva a ejecutar este script."
}

Write-Host "== DocuSearch: instalación local ==" -ForegroundColor Cyan
$venvPython = Join-Path $Raiz ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
  $base = Buscar-Python
  Write-Host "Creando entorno virtual con $base"
  Invocar $base @("-m", "venv", ".venv")
} else {
  Write-Host "Usando el entorno virtual existente (.venv)"
}

Invocar $venvPython @("-m", "pip", "install", "--upgrade", "pip")
$extras = "model"
if ($Desarrollo) { $extras = "dev,model,e2e" }
Write-Host "Instalando DocuSearch con extras [$extras]"
Invocar $venvPython @("-m", "pip", "install", "-e", ".[$extras]")

if ($Semantico) {
  Write-Host "Instalando la búsqueda semántica en versión CPU (puede tardar)"
  Invocar $venvPython @("-m", "pip", "install", "torch", "--index-url", "https://download.pytorch.org/whl/cpu")
  Invocar $venvPython @("-m", "pip", "install", "-e", ".[semantic]")
}
if ($Desarrollo) {
  Invocar $venvPython @("-m", "playwright", "install", "chromium")
}

if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env" -ErrorAction Stop
  Write-Host "Se creó .env a partir de .env.example (no se versiona)."
}

Write-Host ""
Write-Host "Diagnóstico:" -ForegroundColor Cyan
& $venvPython -m backend.app.cli doctor
Write-Host ""
Write-Host "Siguiente paso: powershell -ExecutionPolicy Bypass -File scripts\windows\configurar-cuenta.ps1" -ForegroundColor Green
