<#
.SYNOPSIS
    Записывает ключ OpenRouter в настройки агента (%LOCALAPPDATA%\R-Pro\AIAgentBridge\settings.json).
    Запуск без параметров спросит ключ (ввод скрыт). Права администратора не нужны.
#>
[CmdletBinding()]
param([string]$Key, [string]$Provider = 'auto')
$ErrorActionPreference = 'Stop'
if (-not $Key) {
    $secure = Read-Host 'Ключ OpenRouter (sk-or-...)' -AsSecureString
    $Key = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
}
if ($Key -notmatch '^sk-or-') { throw 'Ключ OpenRouter начинается с sk-or-. Проверьте, что скопировали его целиком.' }
$folder = Join-Path $env:LOCALAPPDATA 'R-Pro\AIAgentBridge'
New-Item -ItemType Directory -Force -Path $folder | Out-Null
$file = Join-Path $folder 'settings.json'
$settings = @{}
if (Test-Path $file) {
    (Get-Content $file -Raw -Encoding UTF8 | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $settings[$_.Name] = $_.Value }
}
$settings['RPRO_LLM'] = $Provider
$settings['OPENROUTER_API_KEY'] = $Key
[IO.File]::WriteAllText($file, ($settings | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
Write-Host "Ключ записан в $file. Перезапустите R-Pro." -ForegroundColor Green
