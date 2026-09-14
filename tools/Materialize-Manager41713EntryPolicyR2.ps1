[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RepositoryRoot,
    [Parameter(Mandatory=$true)][string]$ExpectedBase,
    [string]$EvidenceRoot=''
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$Utf8=New-Object Text.UTF8Encoding($false)
$source=Join-Path $PSScriptRoot 'Materialize-Manager41713EntryPolicyR1.ps1'
if(-not(Test-Path -LiteralPath $source -PathType Leaf)){throw 'Entry-policy R1 materializer is missing.'}
$text=[IO.File]::ReadAllText($source,[Text.Encoding]::UTF8)
$old='$policyRun="$entryPolicyValidator=Join-Path `$RepositoryRoot ''tools\Test-ManagerEntryPolicyCompleteness.ps1''`r`nInvoke-Child `$entryPolicyValidator @(''-RepositoryRoot'',`$RepositoryRoot)`r`n"+$entryRun'
$new=@'
$policyRun=@'
$entryPolicyValidator=Join-Path $RepositoryRoot 'tools\Test-ManagerEntryPolicyCompleteness.ps1'
Invoke-Child $entryPolicyValidator @('-RepositoryRoot',$RepositoryRoot)
'@+$entryRun
'@
$count=[regex]::Matches($text,[regex]::Escape($old)).Count
if($count-ne1){throw('R1 entry-policy interpolation token count='+$count)}
$text=$text.Replace($old,$new.TrimEnd())
$temp=Join-Path ([IO.Path]::GetTempPath()) ('Materialize-Manager41713EntryPolicy-r2-'+[guid]::NewGuid().ToString('N')+'.ps1')
try{
    [IO.File]::WriteAllText($temp,$text,$Utf8)
    $tokens=$null;$errors=$null
    [void][Management.Automation.Language.Parser]::ParseFile($temp,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){throw('Entry-policy R2 generated parser failed: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
    $exe=Join-Path $PSHOME 'powershell.exe'
    & $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $temp -RepositoryRoot $RepositoryRoot -ExpectedBase $ExpectedBase -EvidenceRoot $EvidenceRoot
    exit [int]$LASTEXITCODE
}finally{Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue}
