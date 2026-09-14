[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RepositoryRoot,
    [Parameter(Mandatory=$true)][string]$ExpectedBase,
    [string]$EvidenceRoot=''
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$Utf8=New-Object Text.UTF8Encoding($false)
$source=Join-Path $PSScriptRoot 'Materialize-Manager41713ProductR2.ps1'
if(-not(Test-Path -LiteralPath $source -PathType Leaf)){throw 'R2 materializer is missing.'}
$text=[IO.File]::ReadAllText($source,[Text.Encoding]::UTF8)

# R2 transforms the base materializer text. Insert one additional transform immediately
# after it reads the base source: `Args` is a PowerShell automatic variable, so using it
# as the child-argument parameter caused every Run(...) call to drop its explicit args.
$anchor='$text=[IO.File]::ReadAllText($source,[Text.Encoding]::UTF8)'
if(([regex]::Matches($text,[regex]::Escape($anchor))).Count-ne1){throw 'R2 base-read anchor is missing/ambiguous.'}
$replacement=@'
$text=[IO.File]::ReadAllText($source,[Text.Encoding]::UTF8)
$runSignature='function Run([string]$Script,[string[]]$Args){'
$runSignatureCount=[regex]::Matches($text,[regex]::Escape($runSignature)).Count
if($runSignatureCount-ne1){throw('Base materializer Run signature count='+$runSignatureCount)}
if(([regex]::Matches($text,[regex]::Escape('@Args 2>&1'))).Count-ne1){throw 'Base materializer @Args invocation count is not 1.'}
if(([regex]::Matches($text,[regex]::Escape("(`$Args-join' ')"))).Count-ne1){throw 'Base materializer Args diagnostic count is not 1.'}
$text=$text.Replace($runSignature,'function Run([string]$Script,[string[]]$Arguments){')
$text=$text.Replace('@Args 2>&1','@Arguments 2>&1')
$text=$text.Replace("(`$Args-join' ')","(`$Arguments-join' ')")
'@
$text=$text.Replace($anchor,$replacement.TrimEnd())

$temp=Join-Path ([IO.Path]::GetTempPath()) ('Materialize-Manager41713Product-r3-'+[guid]::NewGuid().ToString('N')+'.ps1')
try{
    [IO.File]::WriteAllText($temp,$text,$Utf8)
    $tokens=$null;$errors=$null
    [void][Management.Automation.Language.Parser]::ParseFile($temp,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){throw('R3 wrapper parser failed: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
    $exe=Join-Path $PSHOME 'powershell.exe'
    & $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $temp -RepositoryRoot $RepositoryRoot -ExpectedBase $ExpectedBase -EvidenceRoot $EvidenceRoot
    exit [int]$LASTEXITCODE
}finally{
    Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
}
