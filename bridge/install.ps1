<#
.SYNOPSIS
    Устанавливает ИИ-мост в пользовательскую папку команд R-Pro.

.DESCRIPTION
    Копирует папку AIAgentBridge в "Документы\R-Pro\<версия>\My Commands".
    Права администратора не нужны: системные файлы R-Pro не затрагиваются.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install.ps1
    powershell -ExecutionPolicy Bypass -File .\install.ps1 -Uninstall
#>

[CmdletBinding()]
param(
    # Папка вида "C:\Users\<имя>\Documents\R-Pro\0.2\My Commands".
    # Если не указана, определяется автоматически.
    [string]$CommandsPath,

    # Удалить ранее установленный мост.
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'AIAgentBridge'

function Resolve-CommandsPath {
    $root = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'R-Pro'
    if (-not (Test-Path $root)) {
        throw "Не найдена папка '$root'. Запустите R-Pro хотя бы один раз, затем повторите установку."
    }

    $versions = Get-ChildItem $root -Directory | Sort-Object Name -Descending
    if (-not $versions) {
        throw "В папке '$root' нет подпапок с версией R-Pro."
    }

    $target = Join-Path $versions[0].FullName 'My Commands'
    if (-not (Test-Path $target)) {
        New-Item -ItemType Directory -Path $target -Force | Out-Null
    }
    return $target
}

if (-not $CommandsPath) { $CommandsPath = Resolve-CommandsPath }
$destination = Join-Path $CommandsPath 'AIAgentBridge'

if ($Uninstall) {
    if (Test-Path $destination) {
        Remove-Item $destination -Recurse -Force
        Write-Host "Мост удалён: $destination" -ForegroundColor Yellow
    } else {
        Write-Host "Мост не найден в $destination — удалять нечего." -ForegroundColor Yellow
    }
    Write-Host "Перезапустите R-Pro, чтобы изменения вступили в силу."
    return
}

if (-not (Test-Path $source)) {
    throw "Не найдены исходники моста: $source"
}

# Сохраняем пользовательский bridge.json, если он уже был настроен.
$existingConfig = Join-Path $destination 'bridge.json'
$savedConfig = $null
if (Test-Path $existingConfig) {
    $savedConfig = Get-Content $existingConfig -Raw
}

if (Test-Path $destination) { Remove-Item $destination -Recurse -Force }
Copy-Item $source $destination -Recurse -Force

# Скомпилированные файлы от прошлой версии только мешают.
Get-ChildItem $destination -Filter *.pyc -Recurse -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

if ($savedConfig) {
    Set-Content -Path (Join-Path $destination 'bridge.json') -Value $savedConfig -Encoding UTF8
    Write-Host "Прежний bridge.json сохранён." -ForegroundColor DarkGray
}

Write-Host "Мост установлен: $destination" -ForegroundColor Green
Write-Host ""
Write-Host "Дальше:" -ForegroundColor Cyan
Write-Host "  1. Запустите (или перезапустите) R-Pro."
Write-Host "  2. В панели вывода должна появиться строка '[ИИ-мост] запущен на http://127.0.0.1:8765'."
Write-Host "  3. Проверьте мост из PowerShell:"
Write-Host "       Invoke-RestMethod http://127.0.0.1:8765/health"
