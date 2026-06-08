# Локальный запуск / перезапуск на Windows (из корня репозитория)
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

if (-not (Test-Path "venv")) {
    python -m venv venv
    .\venv\Scripts\pip install -r requirements.txt
}

if (-not (Test-Path ".env")) {
    Copy-Item .env.example .env
    Write-Host "Создан .env — заполните и запустите снова."
    exit 1
}

Write-Host "Запуск бота..."
.\venv\Scripts\python.exe main.py
