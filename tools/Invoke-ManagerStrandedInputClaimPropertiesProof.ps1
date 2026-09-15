[CmdletBinding()]
param(
    [string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'),
    [string]$OutputPath=''
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$source=Join-Path $RepositoryRoot 'tools\Invoke-ManagerStrandedInputClaimProperties.ps1'
if(-not(Test-Path -LiteralPath $source -PathType Leaf)){throw('Claim property runner missing: '+$source)}

$text=[IO.File]::ReadAllText($source,[Text.Encoding]::UTF8)
$bad='return[pscustomobject]@{Source=$source;Sha=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()}'
$good='return [pscustomobject]@{Source=$source;Sha=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()}'
$count=[regex]::Matches($text,[regex]::Escape($bad)).Count
if($count-ne1){throw('Claim property harness correction anchor count mismatch: '+$count)}
$text=$text.Replace($bad,$good)

$temp=Join-Path ([IO.Path]::GetTempPath()) ('Invoke-ManagerStrandedInputClaimProperties.fixed.'+[guid]::NewGuid().ToString('N')+'.ps1')
$utf8=New-Object Text.UTF8Encoding($false)
try{
    [IO.File]::WriteAllText($temp,$text,$utf8)
    $tokens=$null;$errors=$null
    [void][Management.Automation.Language.Parser]::ParseFile($temp,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){throw('Corrected claim property runner parser failure: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
    $exe=Join-Path $PSHOME 'powershell.exe'
    $args=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$temp,'-RepositoryRoot',$RepositoryRoot)
    if(-not[string]::IsNullOrWhiteSpace($OutputPath)){$args+=@('-OutputPath',$OutputPath)}
    & $exe @args
    $code=[int]$LASTEXITCODE
    exit $code
}finally{
    Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
}
