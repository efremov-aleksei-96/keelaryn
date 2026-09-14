[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RepositoryRoot,
    [Parameter(Mandatory=$true)][string]$ExpectedBase,
    [string]$EvidenceRoot=''
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$Utf8=New-Object Text.UTF8Encoding($false)
$source=Join-Path $PSScriptRoot 'Materialize-Manager41713PrefreezeReviewFixesR1.ps1'
if(-not(Test-Path -LiteralPath $source -PathType Leaf)){throw 'R1 materializer missing.'}
$text=[IO.File]::ReadAllText($source,[Text.Encoding]::UTF8)
foreach($pair in @(
    @('($oldSnapshot.Trim())','($oldSnapshot.TrimEnd())'),
    @('($newSnapshot.Trim())','($newSnapshot.TrimEnd())'),
    @('($oldLoop.Trim())','($oldLoop.TrimEnd())'),
    @('($newLoop.Trim())','($newLoop.TrimEnd())')
)){
    $count=[regex]::Matches($text,[regex]::Escape([string]$pair[0])).Count
    if($count-ne1){throw('R2 patch token count='+$count+' token='+[string]$pair[0])}
    $text=$text.Replace([string]$pair[0],[string]$pair[1])
}
$temp=Join-Path ([IO.Path]::GetTempPath()) ('Materialize-Manager41713PrefreezeReviewFixesR2-'+[guid]::NewGuid().ToString('N')+'.ps1')
try{
    [IO.File]::WriteAllText($temp,$text,$Utf8)
    $tokens=$null;$errors=$null;[void][Management.Automation.Language.Parser]::ParseFile($temp,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){throw('R2 parser failed: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
    & (Join-Path $PSHOME 'powershell.exe') -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $temp -RepositoryRoot $RepositoryRoot -ExpectedBase $ExpectedBase -EvidenceRoot $EvidenceRoot
    exit [int]$LASTEXITCODE
}finally{Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue}
