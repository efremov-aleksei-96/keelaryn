[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$PatcherPath,
    [Parameter(Mandatory=$true)][string]$RepositoryRoot,
    [Parameter(Mandatory=$true)][string]$ExpectedHead
)
$ErrorActionPreference='Stop'
$utf8=New-Object System.Text.UTF8Encoding($false)
$text=[IO.File]::ReadAllText($PatcherPath,[Text.Encoding]::UTF8)
$old=@'
function Replace-One([string]$Path,[string]$Old,[string]$New,[string]$Label){
    $text=Read-Text $Path
    $count=[regex]::Matches($text,[regex]::Escape($Old)).Count
    if($count-ne1){throw "$Label anchor count mismatch: $count"}
    Write-Text $Path ($text.Replace($Old,$New))
}
'@
$new=@'
function Replace-One([string]$Path,[string]$Old,[string]$New,[string]$Label){
    $text=(Read-Text $Path).Replace("`r`n","`n")
    $oldNorm=$Old.Replace("`r`n","`n")
    $newNorm=$New.Replace("`r`n","`n")
    $count=[regex]::Matches($text,[regex]::Escape($oldNorm)).Count
    if($count-ne1){throw "$Label anchor count mismatch: $count"}
    Write-Text $Path ($text.Replace($oldNorm,$newNorm))
}
'@
$textNorm=$text.Replace("`r`n","`n")
$oldNorm=$old.Replace("`r`n","`n")
$newNorm=$new.Replace("`r`n","`n")
$count=[regex]::Matches($textNorm,[regex]::Escape($oldNorm)).Count
if($count-ne1){throw "Patcher helper anchor count mismatch: $count"}
$temp=Join-Path $env:RUNNER_TEMP 'GATE_APPLY_41713_MGR_DEF_0033_NORMALIZED.ps1'
[IO.File]::WriteAllText($temp,$textNorm.Replace($oldNorm,$newNorm),$utf8)
$tokens=$null;$errors=$null
[void][Management.Automation.Language.Parser]::ParseFile($temp,[ref]$tokens,[ref]$errors)
if(@($errors).Count-ne0){throw('Normalized patcher parser failure: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $temp -RepositoryRoot $RepositoryRoot -ExpectedHead $ExpectedHead
exit $LASTEXITCODE
