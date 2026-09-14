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

$old='$policyRun="$entryPolicyValidator='
$new='$policyRun="`$entryPolicyValidator='
$count=[regex]::Matches($text,[regex]::Escape($old)).Count
if($count-ne1){throw('R1 entry-policy interpolation prefix count='+$count)}
$text=$text.Replace($old,$new)

# Authoritative repository source is LF-preserved (-text); R1's oldSelf matcher used CRLF.
# Patch only the literal matcher token, not generated product/source content.
$oldSelfBreak='`r`nInvoke-Child `$menu @(''-SelfTest'',''-NoRootLauncher'')'
$newSelfBreak='`nInvoke-Child `$menu @(''-SelfTest'',''-NoRootLauncher'')'
$selfBreakCount=[regex]::Matches($text,[regex]::Escape($oldSelfBreak)).Count
if($selfBreakCount-ne1){throw('R1 source-SelfTest line-ending matcher count='+$selfBreakCount)}
$text=$text.Replace($oldSelfBreak,$newSelfBreak)

# PowerShell represents $true/$false as VariableExpressionAst nodes. They are syntax literals,
# not Manager action variables, so the completeness guard must normalize them out.
$oldBool=@'
|Where-Object{$_-cne'script:InstanceRegistryActive'}|Sort-Object -Unique)
'@
$newBool=@'
|Where-Object{$_-cne'script:InstanceRegistryActive'-and$_-cne'true'-and$_-cne'false'}|Sort-Object -Unique)
'@
$oldBool=$oldBool.Trim();$newBool=$newBool.Trim()
$boolCount=[regex]::Matches($text,[regex]::Escape($oldBool)).Count
if($boolCount-ne1){throw('R1 AST boolean-normalization token count='+$boolCount)}
$text=$text.Replace($oldBool,$newBool)

$temp=Join-Path ([IO.Path]::GetTempPath()) ('Materialize-Manager41713EntryPolicy-r3-'+[guid]::NewGuid().ToString('N')+'.ps1')
try{
    [IO.File]::WriteAllText($temp,$text,$Utf8)
    $tokens=$null;$errors=$null
    [void][Management.Automation.Language.Parser]::ParseFile($temp,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){throw('Entry-policy R3 generated parser failed: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
    $exe=Join-Path $PSHOME 'powershell.exe'
    & $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $temp -RepositoryRoot $RepositoryRoot -ExpectedBase $ExpectedBase -EvidenceRoot $EvidenceRoot
    exit [int]$LASTEXITCODE
}finally{Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue}
