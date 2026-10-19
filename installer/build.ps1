<#
.SYNOPSIS
    Собирает установщик ИИ-агента: один .exe со всем необходимым.

.DESCRIPTION
    По шагам:
      1. собирает плагин (addon\build.ps1) — загрузчик и ядро;
      2. готовит встраиваемый Python (скачивается с python.org один раз и
         лежит в installer\cache) и ставит в него библиотеки агента;
      3. раскладывает агент, мост и плагин в installer\stage;
      4. проверяет, что агент в этом Python импортируется;
      5. собирает installer\output\rpro-agent-setup-<версия>.exe (Inno Setup 6).

    Версия берётся из файла VERSION в корне репозитория. Адрес сервера
    моделей зашивается в agent\defaults.json установки; пользователь может
    перебить его своим %LOCALAPPDATA%\R-Pro\AIAgentBridge\settings.json.

.EXAMPLE
    .\installer\build.ps1
    .\installer\build.ps1 -OllamaUrl http://127.0.0.1:11434   # сборка для локальной модели
#>

[CmdletBinding()]
param(
    # Адрес сервера моделей, который получат пользователи.
    [string]$OllamaUrl = 'https://rpro.itc.kl.avtotor.ru/ollama',

    # Версия встраиваемого Python. Библиотеки ставятся под неё же.
    [string]$PythonVersion = '3.11.9',

    # Что нового — одной фразой. Попадает в latest.json и в плашку
    # «Доступна версия …» в панели агента у пользователей.
    [string]$Notes = '',

    # Компилятор Inno Setup, если он стоит не в обычном месте.
    [string]$Iscc,

    # Облачная сборка: модель отвечает через OpenRouter (NVIDIA Nemotron), Ollama не нужна.
    # Плагин не пересобирается (берутся готовые addon\bin\*.dll — для сборки нужна установленная
    # R-Pro), site\latest.json не трогается. Ключ в установщик по умолчанию
    # НЕ зашивается (его пользователь вводит сам: tools\set-openrouter-key.ps1); зашить можно только
    # явным -OpenRouterKey — тогда он виден любому, у кого есть .exe.
    [switch]$Cloud,
    [string]$OpenRouterKey = '',
    # ollama | openrouter | auto (облако, при сбое — Ollama предприятия)
    [string]$LlmProvider = 'auto'
)

$ErrorActionPreference = 'Stop'

$root = Split-Path $PSScriptRoot -Parent
$cache = Join-Path $PSScriptRoot 'cache'
$stage = Join-Path $PSScriptRoot 'stage'

$version = (Get-Content (Join-Path $root 'VERSION') -Raw).Trim()
Write-Host "ИИ-агент $version, сервер моделей $OllamaUrl" -ForegroundColor Cyan

function Find-Iscc {
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    throw "Не найден Inno Setup 6 (ISCC.exe). Поставьте его (winget install JRSoftware.InnoSetup) или укажите -Iscc."
}

if (-not $Iscc) { $Iscc = Find-Iscc }

# --- 1. плагин ------------------------------------------------------------

if ($Cloud) {
    foreach ($dll in 'AiBridge.Core.dll', 'Plugin.AiBridge.dll') {
        if (-not (Test-Path (Join-Path $root "addon\bin\$dll"))) { throw "Облачная сборка: нет готового addon\bin\$dll" }
    }
    Write-Host "Облачная сборка ($LlmProvider): плагин берётся готовый из addon\bin" -ForegroundColor Yellow
} else {
    & (Join-Path $root 'addon\build.ps1')
}

# --- 2. Python ------------------------------------------------------------

if (-not (Test-Path $cache)) { New-Item -ItemType Directory -Path $cache | Out-Null }

$pythonZip = Join-Path $cache "python-$PythonVersion-embed-amd64.zip"
if (-not (Test-Path $pythonZip)) {
    $url = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
    Write-Host "Скачиваю $url" -ForegroundColor Cyan
    Invoke-WebRequest $url -OutFile "$pythonZip.part" -UseBasicParsing
    Move-Item "$pythonZip.part" $pythonZip
}

if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage | Out-Null

$python = Join-Path $stage 'python'
Expand-Archive $pythonZip -DestinationPath $python

# Встраиваемый Python берёт пути поиска модулей только из файла ._pth и не
# добавляет туда папку запускаемого скрипта. Поэтому папку агента и
# site-packages прописываем явно. Пути — относительно самого Python.
$short = ($PythonVersion -split '\.')[0..1] -join ''
$pth = Join-Path $python "python$short._pth"
@(
    "python$short.zip"
    '.'
    'Lib\site-packages'
    '..\agent'
    'import site'
) | Set-Content -Path $pth -Encoding ASCII

$sitePackages = Join-Path $python 'Lib\site-packages'
$pyTag = ($PythonVersion -split '\.')[0..1] -join '.'
Write-Host "Библиотеки агента для Python $pyTag…" -ForegroundColor Cyan
& python -m pip install --quiet --disable-pip-version-check `
    --target $sitePackages `
    --platform win_amd64 --python-version $pyTag --implementation cp --only-binary=:all: `
    -r (Join-Path $root 'agent\requirements.txt')
if ($LASTEXITCODE -ne 0) { throw "Не удалось поставить библиотеки агента." }

# --- 3. раскладка ---------------------------------------------------------

# Инструменты разработки (замеры тика, пробы, демо, сборка базы знаний)
# пользователям не нужны.
$devOnly = @('tickhunt.py', 'probe.py', 'demo.py', 'kb_build.py', 'kb_ui_dump.ps1', 'quickref_build.py')

$agent = Join-Path $stage 'agent'
New-Item -ItemType Directory -Path $agent | Out-Null
Get-ChildItem (Join-Path $root 'agent') -File |
    Where-Object { ($_.Extension -in '.py', '.ps1') -and ($_.Name -notin $devOnly) -and ($_.Name -ne 'install-autostart.ps1') } |
    Copy-Item -Destination $agent

# База знаний о R-Pro для справочного инструмента агента (собирает agent\kb_build.py).
# Без неё агент работает, но отвечает о программе по памяти модели.
$kbSource = Join-Path $root 'agent\kb\chunks.jsonl'
if (-not (Test-Path $kbSource)) { throw "Нет $kbSource — соберите базу: python agent\kb_build.py" }
New-Item -ItemType Directory -Path (Join-Path $agent 'kb') | Out-Null
Copy-Item $kbSource (Join-Path $agent 'kb')
# Уроки Academy (собирает agent\academy\academy_to_kb.py): приёмы и подводные камни
# из обучающих видео. Нет файла — агент работает как раньше, только со справкой.
$academySource = Join-Path $root 'agent\kb\academy_chunks.jsonl'
if (Test-Path $academySource) { Copy-Item $academySource (Join-Path $agent 'kb') }
# Данные быстрых команд /api, /термин, /совет, /проблема (agent\quickref.py):
# faq.json пишется руками, остальное собирают kb_build.py и quickref_build.py.
# Курс ИИТБ (agent\iitb\iitb_to_kb.py) — тоже источник справки.
foreach ($name in 'contest_chunks.jsonl', 'iitb_chunks.jsonl', 'api_index.json', 'ui_terms.json', 'tips.jsonl', 'faq.json', 'howto.json') {
    $source = Join-Path $root "agent\kb\$name"
    if (Test-Path $source) { Copy-Item $source (Join-Path $agent 'kb') }
    else { Write-Warning "Нет agent\kb\$name — команда агента останется без данных (python agent\quickref_build.py)" }
}

# Конкурсное задание TechSkills 2026 (модули A, B, C): разбор по модулям для contest.py
$contestSource = Join-Path $root 'agent\contest'
if (Test-Path $contestSource) { Copy-Item $contestSource (Join-Path $agent 'contest') -Recurse }

$defaults = [ordered]@{ OLLAMA_URL = $OllamaUrl }
if ($Cloud) {
    $defaults['RPRO_LLM'] = $LlmProvider
    if ($OpenRouterKey) { $defaults['OPENROUTER_API_KEY'] = $OpenRouterKey }
}
$defaults | ConvertTo-Json | Set-Content -Path (Join-Path $agent 'defaults.json') -Encoding UTF8

$bridge = Join-Path $stage 'bridge'
New-Item -ItemType Directory -Path $bridge | Out-Null
Copy-Item (Join-Path $root 'bridge\AIAgentBridge') $bridge -Recurse
Get-ChildItem $bridge -Recurse -Include '*.pyc', '__pycache__', 'bridge.local.json' |
    Remove-Item -Recurse -Force

foreach ($part in 'core', 'loader') {
    New-Item -ItemType Directory -Path (Join-Path $stage $part) | Out-Null
}
Copy-Item (Join-Path $root 'addon\bin\AiBridge.Core.dll') (Join-Path $stage 'core')
Copy-Item (Join-Path $root 'addon\bin\Plugin.AiBridge.dll') (Join-Path $stage 'loader')

# --- 4. проверка ----------------------------------------------------------

# Запускаем агент ровно так, как его запустит плагин: этим Python и из
# папки установки. Настройки пользователя не должны влиять на проверку.
Write-Host "Проверка: агент импортируется во встраиваемом Python…" -ForegroundColor Cyan
$check = & (Join-Path $python 'python.exe') -c @"
import os, sys
os.environ['LOCALAPPDATA'] = os.devnull
import config, serve, requests, truststore
print(sys.version.split()[0], config.OLLAMA_URL)
"@ 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Агент не запускается во встраиваемом Python:`n$check"
}
Write-Host "  $check" -ForegroundColor Green
Get-ChildItem $stage -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force

# --- 5. установщик --------------------------------------------------------

Write-Host "Сборка установщика…" -ForegroundColor Cyan
& $Iscc /Qp "/DVersion=$version" "/DStage=$stage" (Join-Path $PSScriptRoot 'rpro-agent.iss')
if ($LASTEXITCODE -ne 0) { throw "Inno Setup не собрал установщик." }

$setup = Join-Path $PSScriptRoot "output\rpro-agent-setup-$version.exe"
$size = [math]::Round((Get-Item $setup).Length / 1MB, 1)

# --- 6. latest.json -------------------------------------------------------

if ($Cloud) {
    Write-Host "Готово (облачная сборка): $setup ($size МБ)" -ForegroundColor Green
    return
}

# По этому файлу панель агента узнаёт о новой версии, а лендинг — какую
# ссылку дать на «Скачать». Уезжает на сервер вместе с установщиком
# (site\deploy-itc.ps1 site), поэтому пишем его прямо в site.
$latest = [ordered]@{
    version = $version
    url     = "https://rpro.itc.kl.avtotor.ru/download/rpro-agent-setup-$version.exe"
    sha256  = (Get-FileHash $setup -Algorithm SHA256).Hash.ToLowerInvariant()
    size    = (Get-Item $setup).Length
    notes   = $Notes
}
[IO.File]::WriteAllText((Join-Path $root 'site\latest.json'),
    ($latest | ConvertTo-Json), [Text.UTF8Encoding]::new($false))

Write-Host ""
Write-Host "Готово: $setup ($size МБ)" -ForegroundColor Green
Write-Host "site\latest.json обновлён — выложите: .\site\deploy-itc.ps1 site" -ForegroundColor DarkGray
