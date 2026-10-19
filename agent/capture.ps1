<#
.SYNOPSIS
    Снимок окна R-Pro средствами Windows.

.DESCRIPTION
    Штатный снимок 3D-вида через Python-API не работает: beginFrameGrab
    отрабатывает без ошибок, но файла не создаёт ни при каком написании пути
    (похоже, механизм привязан к записи видео). Поэтому снимок делается снаружи.

    Заодно так получается больше пользы: в кадр попадает всё окно программы —
    3D-вид, дерево компонентов, лента, панель вывода, — а не только сцена.

    Сначала пробуем PrintWindow с отрисовкой слоя DirectX: он снимает окно даже
    когда его частично перекрывают. Если снимок вышел пустым (у DirectX такое
    бывает), переснимаем область экрана.

.PARAMETER Path
    Куда сохранить PNG.

.PARAMETER ProcessName
    Имя процесса. По умолчанию rpro_starter.

.PARAMETER MaxWidth
    Снимок ужимается до этой ширины. Модели со зрением режут картинку на
    фрагменты, и кадр в 2576 точек шириной обходится в разы дороже, чем
    ужатый, — а панели и подписи на нём читаются одинаково. Ноль — не ужимать.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Path,
    [string]$ProcessName = 'rpro_starter',
    [int]$MaxWidth = 1280
)

$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Drawing

Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class WinCapture {
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

$process = Get-Process -Name $ProcessName -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $process) { throw "Процесс '$ProcessName' не найден — программа не запущена." }

$handle = $process.MainWindowHandle
if ($handle -eq [IntPtr]::Zero) { throw "У процесса '$ProcessName' нет главного окна." }
if ([WinCapture]::IsIconic($handle)) { throw "Окно свёрнуто — снимать нечего." }

$rect = New-Object WinCapture+RECT
[void][WinCapture]::GetWindowRect($handle, [ref]$rect)
$width = $rect.Right - $rect.Left
$height = $rect.Bottom - $rect.Top
if ($width -le 0 -or $height -le 0) { throw "Не удалось определить размеры окна." }

function Test-Blank {
    param([System.Drawing.Bitmap]$Image)
    # Смотрим редкую сетку точек: если все одного цвета, снимок пустой.
    $first = $null
    for ($x = 10; $x -lt $Image.Width; $x += [int]($Image.Width / 12) + 1) {
        for ($y = 10; $y -lt $Image.Height; $y += [int]($Image.Height / 12) + 1) {
            $pixel = $Image.GetPixel($x, $y).ToArgb()
            if ($null -eq $first) { $first = $pixel }
            elseif ($pixel -ne $first) { return $false }
        }
    }
    return $true
}

$bitmap = New-Object System.Drawing.Bitmap $width, $height
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$hdc = $graphics.GetHdc()
$printed = [WinCapture]::PrintWindow($handle, $hdc, 2)   # 2 — отрисовать слой DirectX
$graphics.ReleaseHdc($hdc)
$graphics.Dispose()

$method = 'PrintWindow'
if (-not $printed -or (Test-Blank -Image $bitmap)) {
    # Запасной путь: снимаем прямоугольник экрана, занятый окном.
    $bitmap.Dispose()
    $bitmap = New-Object System.Drawing.Bitmap $width, $height
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bitmap.Size)
    $graphics.Dispose()
    $method = 'область экрана'
}

if ($MaxWidth -gt 0 -and $width -gt $MaxWidth) {
    $scale = $MaxWidth / $width
    $newWidth = [int]$MaxWidth
    $newHeight = [int][math]::Round($height * $scale)

    $scaled = New-Object System.Drawing.Bitmap $newWidth, $newHeight
    $graphics = [System.Drawing.Graphics]::FromImage($scaled)
    $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $graphics.DrawImage($bitmap, 0, 0, $newWidth, $newHeight)
    $graphics.Dispose()
    $bitmap.Dispose()

    $bitmap = $scaled
    $width = $newWidth
    $height = $newHeight
}

$folder = Split-Path $Path -Parent
if ($folder -and -not (Test-Path $folder)) { New-Item -ItemType Directory -Path $folder -Force | Out-Null }

$bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
$bitmap.Dispose()

Write-Output "$method|$width|$height|$Path"
