<#
.SYNOPSIS
  Crea o cambia la contraseña de la cuenta de Administrador (o de consulta). DOC-34.
.DESCRIPTION
  Pide la contraseña sin mostrarla (mínimo 12 caracteres) y guarda solo su
  hash scrypt en .env (archivo local que no se versiona). La contraseña no se
  escribe en ningún archivo ni en el historial.
.PARAMETER Rol
  admin (por defecto) o user (solo consulta).
#>
param([ValidateSet("admin", "user")][string]$Rol = "admin")
# "Continue": en Windows PowerShell 5.1 la salida de error de pip/py no debe
# abortar el script; cada comando externo se comprueba con $LASTEXITCODE.
$ErrorActionPreference = "Continue"
# Acentos correctos en la salida de Python (consola y redirecciones)
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$Raiz = Resolve-Path (Join-Path $PSScriptRoot "..\..") -ErrorAction Stop
Set-Location $Raiz -ErrorAction Stop
$venvPython = Join-Path $Raiz ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { throw "Primero ejecute scripts\windows\instalar.ps1" }
& $venvPython -m backend.app.cli hash-password --env-file .env --role $Rol
if ($LASTEXITCODE -ne 0) { throw "No se guardó la contraseña." }
$nombre = if ($Rol -eq "admin") { "admin (cambie DOCUSEARCH_ADMIN_USERNAME en .env si desea otro)" } else { "usuario (DOCUSEARCH_USER_USERNAME)" }
Write-Host "Cuenta lista. Usuario: $nombre" -ForegroundColor Green
Write-Host "Reinicie el servidor si ya estaba en marcha."
