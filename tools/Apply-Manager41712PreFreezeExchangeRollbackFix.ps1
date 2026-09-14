[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$Utf8NoBom=New-Object Text.UTF8Encoding($false)

function Fail([string]$Message){throw $Message}
function Read-Text([string]$Relative){return [IO.File]::ReadAllText((Join-Path $RepositoryRoot $Relative),[Text.Encoding]::UTF8)}
function Write-Text([string]$Relative,[string]$Text){[IO.File]::WriteAllText((Join-Path $RepositoryRoot $Relative),$Text,$Utf8NoBom)}
function Replace-ExactlyOnce([string]$Text,[string]$Old,[string]$New,[string]$Label){
    $first=$Text.IndexOf($Old,[StringComparison]::Ordinal)
    if($first-lt0){Fail($Label+' old text not found.')}
    if($Text.IndexOf($Old,$first+$Old.Length,[StringComparison]::Ordinal)-ge0){Fail($Label+' old text is not unique.')}
    return $Text.Substring(0,$first)+$New+$Text.Substring($first+$Old.Length)
}
function Lines([string[]]$Rows,[string]$Eol){return [string]::Join($Eol,$Rows)}

$menuRel='manager\product\tools\KeelarynMenu.ps1'
$menu=Read-Text $menuRel
$menuEol=if($menu.Contains("`r`n")){"`r`n"}else{"`n"}
$oldPublication=Lines @(
'        if(Test-Path -LiteralPath $target -PathType Leaf){',
'            [IO.File]::Replace($tmp,$target,$backup,$true)',
'            if(Test-Path -LiteralPath $backup){Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue}',
'        }else{',
'            [IO.File]::Move($tmp,$target)',
'        }',
'        $publishedHash=Get-FileSha256Hex $target',
"        if(`$publishedHash-cne`$sourceHash){Fail 'Prepared CURRENT durable publication succeeded, but post-publication SHA-256 verification failed.'}",
"        Write-UiHost ('Prepared CURRENT: '+`$target) -ForegroundColor Green",
'        return 0'
) $menuEol
$newPublication=Lines @(
'        $replacedPrevious=(Test-Path -LiteralPath $target -PathType Leaf)',
'        if($replacedPrevious){',
'            [IO.File]::Replace($tmp,$target,$backup,$true)',
'        }else{',
'            [IO.File]::Move($tmp,$target)',
'        }',
'        try{$publishedHash=Get-FileSha256Hex $target}catch{',
"            `$rollbackNote=if(`$replacedPrevious-and(Test-Path -LiteralPath `$backup -PathType Leaf)){('Previous exchange artifact is preserved at '+`$backup+'.')}else{'No previous exchange artifact existed.'}",
"            Fail('Prepared CURRENT durable publication succeeded, but post-publication SHA-256 verification could not complete. '+`$rollbackNote+' '+`$_.Exception.Message)",
'        }',
'        if($publishedHash-cne$sourceHash){',
"            `$rollbackNote=if(`$replacedPrevious-and(Test-Path -LiteralPath `$backup -PathType Leaf)){('Previous exchange artifact is preserved at '+`$backup+'.')}else{'No previous exchange artifact existed.'}",
"            Fail('Prepared CURRENT durable publication succeeded, but post-publication SHA-256 verification failed. '+`$rollbackNote)",
'        }',
'        if(Test-Path -LiteralPath $backup){Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue}',
"        Write-UiHost ('Prepared CURRENT: '+`$target) -ForegroundColor Green",
'        return 0'
) $menuEol
$menu=Replace-ExactlyOnce $menu $oldPublication $newPublication 'ChatGPT CURRENT publication transaction'
$oldFinally=Lines @(
'        if($archive){$archive.Dispose()}',
'        if($targetStream){$targetStream.Dispose()}',
'        if($sourceStream){$sourceStream.Dispose()}',
'        if(Test-Path -LiteralPath $tmp){Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue}',
'        if(Test-Path -LiteralPath $backup){Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue}'
) $menuEol
$newFinally=Lines @(
'        if($archive){$archive.Dispose()}',
'        if($targetStream){$targetStream.Dispose()}',
'        if($sourceStream){$sourceStream.Dispose()}',
'        if(Test-Path -LiteralPath $tmp){Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue}'
) $menuEol
$menu=Replace-ExactlyOnce $menu $oldFinally $newFinally 'ChatGPT CURRENT rollback preservation finally block'
Write-Text $menuRel $menu

$reg3Rel='tools\Invoke-Manager4173ReviewRegression.ps1'
$reg3=Read-Text $reg3Rel
$reg3Eol=if($reg3.Contains("`r`n")){"`r`n"}else{"`n"}
$oldHash='    function Get-FileSha256Hex([string]$FilePath){return Get-Sha256 $FilePath}'
$newHash=Lines @(
'    $script:ForcedPublishedHashMismatchPath=$null',
'    function Get-FileSha256Hex([string]$FilePath){',
'        $hash=Get-Sha256 $FilePath',
'        if($script:ForcedPublishedHashMismatchPath){',
'            $actual=[IO.Path]::GetFullPath($FilePath)',
'            $forced=[IO.Path]::GetFullPath([string]$script:ForcedPublishedHashMismatchPath)',
"            if(`$actual-ieq`$forced){return ('0'*64)}",
'        }',
'        return $hash',
'    }'
) $reg3Eol
$reg3=Replace-ExactlyOnce $reg3 $oldHash $newHash '4.17.3 regression hash stub'
$anchor="    Write-Host '  PASS wrong-instance, mixed-identity and non-approved CURRENT exports fail closed without changing exchange bytes'"
$rollbackTest=Lines @(
'',
'    # Regression A3: rollback bytes survive until post-publication verification succeeds.',
'    New-IdentityBoundCurrentZip $aCurrent $aId',
"    [IO.File]::WriteAllText(`$prepared,'previous-exchange-artifact',(New-Object Text.UTF8Encoding(`$false)))",
'    $previousExchangeHash=Get-Sha256 $prepared',
'    $script:ForcedPublishedHashMismatchPath=$prepared',
'    $blocked=$false;$failureMessage=$null',
"    try{`$null=Copy-CurrentForChatGPT `$ctxA 'workspace-input'}catch{`$blocked=`$true;`$failureMessage=`$_.Exception.Message}finally{`$script:ForcedPublishedHashMismatchPath=`$null}",
"    Assert `$blocked 'Forced post-publication verification failure did not fail closed.'",
"    Assert ([string]`$failureMessage).Contains('durable publication succeeded') 'Post-publication failure did not identify the durable commit.'",
"    Assert ([string]`$failureMessage).Contains('Previous exchange artifact is preserved at') 'Post-publication failure did not report preserved rollback data.'",
"    Assert ((Get-Sha256 `$prepared)-ceq(Get-Sha256 `$aCurrent)) 'Durably published target bytes were not the verified source bytes.'",
"    `$backupPattern=(Split-Path `$prepared -Leaf)+'.replace-backup-*'",
"    `$rollbackRows=@(Get-ChildItem -LiteralPath (Split-Path -Parent `$prepared) -File -Filter `$backupPattern)",
"    Assert (`$rollbackRows.Count-eq1) ('Expected exactly one preserved rollback artifact; actual='+`$rollbackRows.Count)",
"    Assert ((Get-Sha256 `$rollbackRows[0].FullName)-ceq`$previousExchangeHash) 'Preserved rollback artifact does not match the previous exchange bytes.'",
'    Remove-Item -LiteralPath $rollbackRows[0].FullName -Force',
"    Write-Host '  PASS previous exchange bytes survive a durable-commit/post-publication verification failure'"
) $reg3Eol
$reg3=Replace-ExactlyOnce $reg3 $anchor ($anchor+$rollbackTest) '4.17.3 rollback regression insertion'
Write-Text $reg3Rel $reg3

$reg12Rel='tools\Invoke-Manager41712ReviewRegression.ps1'
$reg12=Read-Text $reg12Rel
$reg12Eol=if($reg12.Contains("`r`n")){"`r`n"}else{"`n"}
$reg12Anchor='Assert ($menu.Contains("CURRENT belongs to a different instance_id")) ''Frontend CURRENT wrong-instance failure contract is missing.'''
$reg12Extra=Lines @(
"Assert (`$copyCurrentText.Contains('Previous exchange artifact is preserved at')) 'ChatGPT CURRENT post-publication failure does not preserve/report rollback data.'",
"`$postVerifyIndex=`$copyCurrentText.IndexOf('`$publishedHash=Get-FileSha256Hex `$target',[StringComparison]::Ordinal)",
"`$backupCleanupIndex=`$copyCurrentText.IndexOf('if(Test-Path -LiteralPath `$backup){Remove-Item -LiteralPath `$backup -Force -ErrorAction SilentlyContinue}',[StringComparison]::Ordinal)",
"Assert (`$postVerifyIndex-ge0-and`$backupCleanupIndex-gt`$postVerifyIndex) 'ChatGPT CURRENT rollback backup is deleted before post-publication verification.'"
) $reg12Eol
$reg12=Replace-ExactlyOnce $reg12 $reg12Anchor ($reg12Anchor+$reg12Eol+$reg12Extra) '4.17.12 rollback source-contract regression'
Write-Text $reg12Rel $reg12

foreach($relative in @($menuRel,$reg3Rel,$reg12Rel)){
    $tokens=$null;$errors=$null
    [void][Management.Automation.Language.Parser]::ParseFile((Join-Path $RepositoryRoot $relative),[ref]$tokens,[ref]$errors)
    if(@($errors).Count){Fail('Parser failed after materialization: '+$relative+'; '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
}

Write-Host 'Manager 4.17.12 pre-freeze exchange rollback materialization: PASS' -ForegroundColor Green
