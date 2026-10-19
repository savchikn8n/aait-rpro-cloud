<#
.SYNOPSIS
    Снимает карту ленты R-Pro с живого окна в agent\kb\ui_ribbon.md.

.DESCRIPTION
    Через UI Automation по очереди открывает каждую вкладку ленты и записывает
    её группы и элементы: подпись, внутренний id, тип, подсказку, активность.
    Нужна запущенная R-Pro. После снятия пересоберите базу: python kb_build.py.

    Выпадающие меню («Поведение», «Элементы», «Свойства» на вкладке
    МОДЕЛИРОВАНИЕ) неактивны без выделенного компонента, их содержимое
    берётся из справки.
#>
param([string]$Out = (Join-Path $PSScriptRoot 'kb\ui_ribbon.md'))

Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$A = [System.Windows.Automation.AutomationElement]
$Scope = [System.Windows.Automation.TreeScope]
$p = Get-Process rpro_starter -ErrorAction Stop | Select-Object -First 1
$root = $A::FromHandle($p.MainWindowHandle)
$walker = [System.Windows.Automation.TreeWalker]::RawViewWalker

function ById($el, $id) {
    $cond = New-Object System.Windows.Automation.PropertyCondition ($A::AutomationIdProperty), $id
    $el.FindFirst($Scope::Descendants, $cond)
}

$tabs = ById (ById $root 'MainRibbon') 'XamRibbonTabs'
$sb = New-Object System.Text.StringBuilder
[void]$sb.AppendLine('# Лента R-Pro')
[void]$sb.AppendLine("Снято $(Get-Date -Format 'yyyy-MM-dd') с окна «$($root.Current.Name)» скриптом kb_ui_dump.ps1.")

function Line($el, $depth) {
    $c = $el.Current
    $ct = $c.ControlType.ProgrammaticName -replace 'ControlType\.', ''
    $s = ('  ' * $depth) + "- $ct"
    if ($c.Name) { $s += " «$($c.Name)»" }
    if ($c.AutomationId) { $s += " ``$($c.AutomationId)``" }
    if ($c.ClassName) { $s += " [$($c.ClassName)]" }
    if ($c.HelpText) { $s += " — $($c.HelpText -replace '\s+', ' ')" }
    if (-not $c.IsEnabled) { $s += ' (неактивна)' }
    $s
}

# Внутри вкладки оставляем только значимое: группы и элементы с подписью.
function WalkTab($el, $depth) {
    $child = $walker.GetFirstChild($el)
    while ($null -ne $child) {
        try {
            $c = $child.Current
            if (($c.ClassName -match 'RibbonGroup|Tool|Gallery|MenuItem') -and ($c.Name -or $c.HelpText)) {
                [void]$sb.AppendLine((Line $child $depth))
                WalkTab $child ($depth + 1)
            } else {
                WalkTab $child $depth
            }
        } catch {}
        $child = $walker.GetNextSibling($child)
    }
}

# Через ::new, а не New-Object: тот заворачивает ControlType в PSObject, и
# конструктор отказывается его принимать.
$tabCond = [System.Windows.Automation.PropertyCondition]::new($A::ControlTypeProperty, [System.Windows.Automation.ControlType]::TabItem)
$tabItems = $tabs.FindAll($Scope::Children, $tabCond)
$select = [System.Windows.Automation.SelectionItemPattern]::Pattern
foreach ($t in $tabItems) {
    try { $t.GetCurrentPattern($select).Select() } catch {}
    Start-Sleep -Milliseconds 900
    [void]$sb.AppendLine('')
    [void]$sb.AppendLine("## Вкладка «$($t.Current.Name)» ``$($t.Current.AutomationId)``")
    WalkTab $t 0
}
# Вернуть пользователю «Главную».
try { $tabItems[0].GetCurrentPattern($select).Select() } catch {}

[IO.File]::WriteAllText($Out, $sb.ToString(), (New-Object Text.UTF8Encoding $false))
"вкладок: $($tabItems.Count) → $Out"
