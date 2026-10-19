<#
.SYNOPSIS
    Собирает плагин ИИ-агента (загрузчик и ядро) и ставит его для разработки.

.DESCRIPTION
    Плагин состоит из двух сборок:

      bin\Plugin.AiBridge.dll  — загрузчик. Лежит в папке R-Pro (только оттуда
                                 программа берёт плагины), меняется редко.
      bin\AiBridge.Core.dll    — ядро: тикер, окно чата, автозапуск агента.
                                 Лежит где угодно, путь к нему загрузчик берёт
                                 из реестра HKCU\Software\AAIT\RProAgent\CorePath.

    Пользователям всё это ставит установщик (installer\build.ps1). Этот скрипт —
    для разработки: -Install кладёт загрузчик в папку R-Pro (нужны права
    администратора) и направляет его на ядро прямо в addon\bin. После
    пересборки ядра достаточно перезапустить R-Pro.

    Сборка идёт компилятором из состава .NET Framework, Visual Studio не нужна.
    Версия берётся из файла VERSION в корне репозитория.

.EXAMPLE
    .\build.ps1                 # собрать
    .\build.ps1 -Install        # собрать и поставить для разработки (от администратора)
    .\build.ps1 -Uninstall      # удалить загрузчик из папки программы
#>

[CmdletBinding()]
param(
    # Папка установленной R-Pro. Если не указана, находится автоматически.
    [string]$RProPath,

    # Поставить загрузчик в папку программы и направить его на ядро из bin.
    [switch]$Install,

    # Удалить загрузчик из папки программы.
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'

# Имя загрузчика обязано начинаться с "Plugin." или "UXAddOn." — только такие
# файлы R-Pro ищет в своей папке. Ядро, наоборот, так называть нельзя: попади
# оно в папку программы, R-Pro подхватила бы его в обход загрузчика.
$loaderName = 'Plugin.AiBridge.dll'
$coreName = 'AiBridge.Core.dll'
$outputDir = Join-Path $PSScriptRoot 'bin'
$loaderPath = Join-Path $outputDir $loaderName
$corePath = Join-Path $outputDir $coreName

# Имя из первой версии, когда плагин умел только тикать. Если остался от
# прошлой установки — уберём, иначе в R-Pro окажется два одинаковых тикера.
$legacyName = 'Plugin.AiBridgeTicker.dll'

$registryKey = 'HKCU:\Software\AAIT\RProAgent'

function Find-RPro {
    $candidates = @()
    foreach ($base in @(${env:ProgramFiles(x86)}, $env:ProgramFiles)) {
        if ($base -and (Test-Path $base)) {
            $candidates += Get-ChildItem $base -Directory -Filter 'RProv*' -ErrorAction SilentlyContinue
        }
    }
    if (-not $candidates) {
        throw "Не найдена установленная R-Pro. Укажите папку параметром -RProPath."
    }
    return ($candidates | Sort-Object Name -Descending)[0].FullName
}

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal $identity).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not $RProPath) { $RProPath = Find-RPro }
Write-Host "R-Pro: $RProPath" -ForegroundColor DarkGray

$installedPath = Join-Path $RProPath $loaderName

if ($Uninstall) {
    if (-not (Test-Admin)) {
        throw "Для удаления плагина нужны права администратора: запустите PowerShell от имени администратора."
    }
    if (Test-Path $installedPath) {
        Remove-Item $installedPath -Force
        Write-Host "Плагин удалён: $installedPath" -ForegroundColor Yellow
    } else {
        Write-Host "Плагин не установлен — удалять нечего." -ForegroundColor Yellow
    }
    Write-Host "Перезапустите R-Pro."
    return
}

# --- сборка ---------------------------------------------------------------

$version = (Get-Content (Join-Path $PSScriptRoot '..\VERSION') -Raw).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+$') {
    throw "В файле VERSION должна быть версия вида 1.2.3, а там '$version'."
}

$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path $csc)) {
    $csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
}
if (-not (Test-Path $csc)) {
    throw "Не найден компилятор C# (csc.exe) из состава .NET Framework."
}

# Папки со сборками .NET Framework. Каталог Reference Assemblies есть не на
# каждой машине, поэтому опираемся на сами библиотеки времени выполнения.
$frameworkDir = Split-Path $csc -Parent

$references = @(
    (Join-Path $RProPath 'UX.Shared.dll'),
    (Join-Path $RProPath 'Create3D.Shared.dll'),
    (Join-Path $RProPath 'Caliburn.Micro.dll'),
    (Join-Path $RProPath 'Newtonsoft.Json.dll'),
    (Join-Path $frameworkDir 'System.dll'),
    (Join-Path $frameworkDir 'System.Core.dll'),
    (Join-Path $frameworkDir 'System.Net.Http.dll'),
    (Join-Path $frameworkDir 'System.Xaml.dll'),
    (Join-Path $frameworkDir 'System.ComponentModel.Composition.dll'),
    (Join-Path $frameworkDir 'WPF\WindowsBase.dll'),
    (Join-Path $frameworkDir 'WPF\PresentationCore.dll'),
    (Join-Path $frameworkDir 'WPF\PresentationFramework.dll')
)

foreach ($ref in $references) {
    if (-not (Test-Path $ref)) {
        throw "Не найдена сборка, на которую ссылается плагин: $ref"
    }
}

if (-not (Test-Path $outputDir)) { New-Item -ItemType Directory -Path $outputDir -Force | Out-Null }

# У ядра — версия выпуска: по ней оно сверяется с сервером обновлений.
# У загрузчика — своя, из addon\loader\VERSION, и меняется она только вместе с
# его кодом. По ней установщик решает, класть ли загрузчик в папку R-Pro, а
# значит, просить ли права администратора. Сравнивать файлы целиком нельзя:
# компилятор .NET Framework при каждой сборке выдаёт другие байты.
$loaderVersion = (Get-Content (Join-Path $PSScriptRoot 'loader\VERSION') -Raw).Trim()

function Write-VersionFile([string]$path, [string]$value) {
    @"
[assembly: System.Reflection.AssemblyVersion("$value.0")]
[assembly: System.Reflection.AssemblyFileVersion("$value.0")]
[assembly: System.Reflection.AssemblyInformationalVersion("$value")]
"@ | Set-Content -Path $path -Encoding UTF8
}

$versionFile = Join-Path $outputDir 'AssemblyVersion.g.cs'
$loaderVersionFile = Join-Path $outputDir 'LoaderVersion.g.cs'
Write-VersionFile $versionFile $version
Write-VersionFile $loaderVersionFile $loaderVersion

function Build-Assembly([string]$name, [string]$sourceDir, [string]$output, [string]$versionFile) {
    $sources = @(Get-ChildItem $sourceDir -Filter '*.cs' | Select-Object -ExpandProperty FullName)
    if (-not $sources) { throw "В папке $sourceDir нет исходников (*.cs)." }

    $arguments = @(
        '/target:library'
        '/platform:AnyCPU'
        '/optimize+'
        '/nologo'
        "/out:$output"
    ) + ($references | ForEach-Object { "/reference:$_" }) + $sources + $versionFile

    Write-Host "Сборка $name…" -ForegroundColor Cyan
    & $csc $arguments
    if ($LASTEXITCODE -ne 0) { throw "Компиляция $name не удалась." }

    $size = [math]::Round((Get-Item $output).Length / 1KB, 1)
    Write-Host "Собрано: $output ($size КБ)" -ForegroundColor Green
}

Build-Assembly 'загрузчика' (Join-Path $PSScriptRoot 'loader') $loaderPath $loaderVersionFile
Build-Assembly 'ядра' (Join-Path $PSScriptRoot 'core') $corePath $versionFile
Write-Host "Версия: $version, загрузчик $loaderVersion" -ForegroundColor DarkGray

# --- установка для разработки ---------------------------------------------

if (-not $Install) {
    Write-Host ""
    Write-Host "Для установки запустите PowerShell от имени администратора и повторите с -Install"
    return
}

if (-not (Test-Admin)) {
    throw "Для установки нужны права администратора: загрузчик кладётся в папку программы. Запустите PowerShell от имени администратора."
}

$rproRunning = Get-Process rpro_starter -ErrorAction SilentlyContinue
if ($rproRunning) {
    throw "R-Pro запущена — закройте её, иначе файл плагина занят."
}

$legacyPath = Join-Path $RProPath $legacyName
if (Test-Path $legacyPath) {
    Remove-Item $legacyPath -Force
    Write-Host "Удалён плагин прошлой версии: $legacyName" -ForegroundColor DarkGray
}

Copy-Item $loaderPath $installedPath -Force
Write-Host "Загрузчик установлен: $installedPath" -ForegroundColor Green

# Ключ пишется в ветку того, кто запустил скрипт. Поэтому запускайте его от
# администратора под своей учётной записью: если права даёт другая, ядро
# пропишется ей, а не вам.
New-Item -Path $registryKey -Force | Out-Null
Set-ItemProperty -Path $registryKey -Name CorePath -Value $corePath
Write-Host "Ядро: $corePath (HKCU\Software\AAIT\RProAgent\CorePath)" -ForegroundColor Green

Write-Host ""
Write-Host "Дальше:" -ForegroundColor Cyan
Write-Host "  1. Если агент ещё не прописан — .\agent\install-autostart.ps1 (без прав администратора)."
Write-Host "  2. Запустите R-Pro."
Write-Host "  3. В панели вывода появится '[ИИ-мост] ИИ-агент $version' и '[ИИ-мост] тикер запущен'."
Write-Host ""
Write-Host "Пересобрали ядро — просто перезапустите R-Pro, права администратора больше не нужны:" -ForegroundColor DarkGray
Write-Host "  .\addon\build.ps1" -ForegroundColor DarkGray
