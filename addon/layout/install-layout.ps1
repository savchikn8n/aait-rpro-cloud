<#
.SYNOPSIS
    Ставит раскладку окон R-Pro с панелью «ИИ-агент» как раскладку по умолчанию.

.DESCRIPTION
    R-Pro хранит расстановку панелей в профиле пользователя и записывает её при
    закрытии программы. Здесь лежит снятая с рабочей машины раскладка: каталог
    слева, 3D-вид по центру, панель «ИИ-агент» справа на всю высоту, свойства и
    вывод внизу.

    Скрипт кладёт её в DefaultLayout_Configure.xml — то есть она станет и
    стартовой, и той, к которой возвращает кнопка «Восстановить окна».
    Прежний файл сохраняется рядом с пометкой .backup.

    Прав администратора не нужно: файлы лежат в профиле пользователя.

.EXAMPLE
    .\install-layout.ps1
    .\install-layout.ps1 -Restore     # вернуть прежнюю раскладку
#>

[CmdletBinding()]
param(
    # Заменить также текущую пользовательскую раскладку, а не только стандартную.
    [switch]$AlsoUser,

    # Вернуть раскладку, которая была до установки.
    [switch]$Restore
)

$ErrorActionPreference = 'Stop'

if (Get-Process rpro_starter -ErrorAction SilentlyContinue) {
    throw "R-Pro запущена — закройте её, иначе она перезапишет раскладку при выходе."
}

$root = Join-Path $env:LOCALAPPDATA 'R-Pro'
if (-not (Test-Path $root)) { throw "Не найдена папка настроек R-Pro: $root" }

# Папка вида "R-Про версия 2.2.2\AppConfig\0.2.2" — версий может быть несколько.
$configDir = Get-ChildItem $root -Directory |
    ForEach-Object { Get-ChildItem (Join-Path $_.FullName 'AppConfig') -Directory -ErrorAction SilentlyContinue } |
    Sort-Object Name -Descending | Select-Object -First 1

if (-not $configDir) { throw "Не найдена папка AppConfig внутри $root" }

$target = Join-Path $configDir.FullName 'DefaultLayout_Configure.xml'
$backup = "$target.backup"
$userLayout = Join-Path $configDir.FullName 'UserLayout_Configure.xml'

if ($Restore) {
    if (-not (Test-Path $backup)) { throw "Резервной копии нет: $backup" }
    Copy-Item $backup $target -Force
    Write-Host "Прежняя раскладка возвращена: $target" -ForegroundColor Yellow
    Write-Host "Пользовательскую раскладку R-Pro перезапишет сама при следующем закрытии."
    return
}

$source = Join-Path $PSScriptRoot 'DefaultLayout_Configure.xml'
if (-not (Test-Path $source)) { throw "Не найден файл раскладки: $source" }

if ((Test-Path $target) -and -not (Test-Path $backup)) {
    Copy-Item $target $backup
    Write-Host "Прежняя раскладка сохранена: $backup" -ForegroundColor DarkGray
}

Copy-Item $source $target -Force
Write-Host "Раскладка по умолчанию заменена: $target" -ForegroundColor Green

if ($AlsoUser) {
    Copy-Item $source $userLayout -Force
    Write-Host "Текущая раскладка пользователя тоже заменена." -ForegroundColor Green
} elseif (Test-Path $userLayout) {
    Write-Host ""
    Write-Host "Учтите: у вас уже есть своя сохранённая раскладка, и R-Pro откроется с ней." -ForegroundColor Yellow
    Write-Host "Чтобы применить новую сразу, повторите с ключом -AlsoUser либо нажмите"
    Write-Host "в программе «Восстановить окна»."
}
