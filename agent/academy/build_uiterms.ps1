# Builds uiterms.json: English UI string -> Russian UI string in R-Pro.
# Source: Resource.English.dll and Resource.<Russian>.dll from the R-Pro install
# (WPF BAML resource dictionaries with identical keys). Run in Windows PowerShell 5.1:
#   powershell -File build_uiterms.ps1
# The script is ASCII-only on purpose (no BOM needed).
param([string]$Install = 'C:\Program Files (x86)\RProv222',
      [string]$Out = (Join-Path $PSScriptRoot 'uiterms.json'))

Add-Type -AssemblyName PresentationFramework, WindowsBase, System.Xaml

function Read-Dicts($dll) {
    $asm = [Reflection.Assembly]::LoadFrom($dll)
    $stream = $asm.GetManifestResourceStream($asm.GetManifestResourceNames()[0])
    $rr = New-Object System.Resources.ResourceReader($stream)
    $res = @{}
    foreach ($e in $rr) {
        try {
            $reader = New-Object System.Windows.Baml2006.Baml2006Reader($e.Value)
            $writer = New-Object System.Xaml.XamlObjectWriter($reader.SchemaContext)
            while ($reader.Read()) { $writer.WriteNode($reader) }
            $d = $writer.Result
            foreach ($k in $d.Keys) {
                if ($d[$k] -is [string]) { $res["$($e.Key)|$k"] = $d[$k] }
            }
        } catch { Write-Warning "skip $($e.Key): $($_.Exception.Message)" }
    }
    $res
}

$ruDll = Get-ChildItem $Install -Filter 'Resource.*.dll' |
    Where-Object { $_.Name -notlike '*English*' -and $_.Name -notlike '*Additional*' } |
    Select-Object -First 1
$en = Read-Dicts (Join-Path $Install 'Resource.English.dll')
$ru = Read-Dicts $ruDll.FullName
Write-Host "EN strings: $($en.Count), RU strings: $($ru.Count)"

$pairs = New-Object System.Collections.Generic.List[object]
foreach ($k in $en.Keys) {
    if ($ru.ContainsKey($k)) {
        $pairs.Add([pscustomobject]@{ key = $k; en = $en[$k]; ru = $ru[$k] })
    }
}
Write-Host "pairs: $($pairs.Count)"
[IO.File]::WriteAllText($Out, ($pairs | ConvertTo-Json -Depth 3), (New-Object Text.UTF8Encoding($false)))
Write-Host "written $Out"
