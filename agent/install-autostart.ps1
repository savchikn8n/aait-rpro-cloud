<#
.SYNOPSIS
    Настраивает автозапуск сервера агента вместе с R-Pro.

.DESCRIPTION
    Плагин в R-Pro при старте программы сам поднимает agent\serve.py скрытым
    процессом и гасит его при выходе. Где лежит агент, плагин не знает —
    этот скрипт записывает путь к Python и к serve.py в файл
    %LOCALAPPDATA%\R-Pro\AIAgentBridge\agent.json.

    Права администратора не нужны. Плагин (addon\build.ps1 -Install) должен
    быть уже установлен. После настройки перезапустите R-Pro.

.EXAMPLE
    .\agent\install-autostart.ps1                  # Python из .venv репозитория
    .\agent\install-autostart.ps1 -Python C:\Python311\python.exe
    .\agent\install-autostart.ps1 -Uninstall       # выключить автозапуск
#>

[CmdletBinding()]
param(
    # Python, которым запускать агента. По умолчанию — из .venv репозитория,
    # иначе первый найденный в PATH.
    [string]$Python,

    # Убрать настройку автозапуска.
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'

$settingsDir = Join-Path $env:LOCALAPPDATA 'R-Pro\AIAgentBridge'
$configPath = Join-Path $settingsDir 'agent.json'
$script = Join-Path $PSScriptRoot 'serve.py'

if ($Uninstall) {
    if (Test-Path $configPath) {
        Remove-Item $configPath -Force
        Write-Host "Автозапуск агента выключен." -ForegroundColor Yellow
    } else {
        Write-Host "Автозапуск и так не настроен." -ForegroundColor Yellow
    }
    return
}

if (-not $Python) {
    $venvPython = Join-Path (Split-Path $PSScriptRoot -Parent) '.venv\Scripts\python.exe'
    if (Test-Path $venvPython) {
        $Python = $venvPython
    } else {
        $found = Get-Command python.exe -ErrorAction SilentlyContinue
        if (-not $found) {
            throw "Python не найден. Создайте окружение (шаг 2 в README) или укажите путь параметром -Python."
        }
        $Python = $found.Source
    }
}
$Python = (Resolve-Path $Python).Path
Write-Host "Python: $Python" -ForegroundColor DarkGray

# Проверяем заранее, что агент в этом окружении вообще поднимается: иначе
# ошибка всплывёт только в журнале, когда R-Pro уже запущена.
Push-Location $PSScriptRoot
try {
    & $Python -c "import requests, config, chat, tools, llm_ollama" 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Агент не импортируется этим Python. Поставьте зависимости: $Python -m pip install -r agent\requirements.txt"
    }
} finally {
    Pop-Location
}

if (-not (Test-Path $settingsDir)) { New-Item -ItemType Directory -Path $settingsDir -Force | Out-Null }

$config = [ordered]@{ python = $Python; script = $script }
# Без BOM: Newtonsoft его переварит, но незачем.
[IO.File]::WriteAllText($configPath, ($config | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))

Write-Host "Автозапуск настроен: $configPath" -ForegroundColor Green
Write-Host ""
Write-Host "Перезапустите R-Pro. В панели вывода появится строка"
Write-Host "  [ИИ-мост] агент запущен, журнал: …\agent.log"
Write-Host "а панель «ИИ-агент» поздоровается, как только модель загрузится."
Write-Host ""
Write-Host "Временно выключить без удаления настройки:" -ForegroundColor DarkGray
Write-Host "  New-Item -ItemType File `"$settingsDir\agent.disabled`" -Force"
