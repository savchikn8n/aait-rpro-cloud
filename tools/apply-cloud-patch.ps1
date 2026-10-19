<#
.SYNOPSIS
    Ставит в уже установленный ИИ-агент облачную модель (OpenRouter): обновляет код агента и пишет настройки.
    Права администратора не нужны. Запускать из папки распакованного патча (рядом лежат agent\ и cloud-settings.json).
#>
[CmdletBinding()]
param([string]$InstallDir)

$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot

if (-not $InstallDir) {
    $InstallDir = (Get-ItemProperty 'HKCU:\Software\AAIT\RProAgent' -ErrorAction SilentlyContinue).InstallDir
}
if (-not $InstallDir) { $InstallDir = Join-Path $env:LOCALAPPDATA 'Programs\AAIT\RProAgent' }
$agent = Join-Path $InstallDir 'agent'
if (-not (Test-Path (Join-Path $agent 'serve.py'))) {
    throw "Не найден установленный агент в $InstallDir. Сначала поставьте rpro-agent-setup-*.exe, потом запустите патч."
}

# Сервер агента (serve.py) держит старый код в памяти — останавливаем его; панель поднимет заново.
try {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.ExecutablePath -like "$InstallDir*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
} catch { }

$backup = Join-Path $InstallDir ("agent.bak-" + (Get-Date -Format 'yyyyMMdd-HHmmss'))
Copy-Item $agent $backup -Recurse
Copy-Item (Join-Path $here 'agent\*') $agent -Recurse -Force
Write-Host "Код агента обновлён (копия прежнего: $backup)" -ForegroundColor Green

# Настройки пользователя: добавляем облачные ключи, остальное не трогаем.
$folder = Join-Path $env:LOCALAPPDATA 'R-Pro\AIAgentBridge'
New-Item -ItemType Directory -Force -Path $folder | Out-Null
$file = Join-Path $folder 'settings.json'
$settings = @{}
if (Test-Path $file) {
    $old = Get-Content $file -Raw -Encoding UTF8 | ConvertFrom-Json
    $old.PSObject.Properties | ForEach-Object { $settings[$_.Name] = $_.Value }
}
$new = Get-Content (Join-Path $here 'cloud-settings.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$new.PSObject.Properties | ForEach-Object { $settings[$_.Name] = $_.Value }
[IO.File]::WriteAllText($file, ($settings | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
Write-Host "Настройки записаны: $file" -ForegroundColor Green
Write-Host "Готово. Перезапустите R-Pro: панель «ИИ-агент» заработает на облачной модели." -ForegroundColor Cyan
