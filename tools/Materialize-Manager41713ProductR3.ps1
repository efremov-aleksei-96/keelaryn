[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RepositoryRoot,
    [Parameter(Mandatory=$true)][string]$ExpectedBase,
    [string]$EvidenceRoot=''
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$Utf8=New-Object Text.UTF8Encoding($false)
$r2Source=Join-Path $PSScriptRoot 'Materialize-Manager41713ProductR2.ps1'
$baseSource=Join-Path $PSScriptRoot 'Materialize-Manager41713Product.ps1'
foreach($p in @($r2Source,$baseSource)){if(-not(Test-Path -LiteralPath $p -PathType Leaf)){throw('Required materializer source is missing: '+$p)}}
$text=[IO.File]::ReadAllText($r2Source,[Text.Encoding]::UTF8)

# R2 transforms the base materializer text. Insert additional transforms immediately
# after it reads the base source.
$anchor='$text=[IO.File]::ReadAllText($source,[Text.Encoding]::UTF8)'
if(([regex]::Matches($text,[regex]::Escape($anchor))).Count-ne1){throw 'R2 base-read anchor is missing/ambiguous.'}
$replacement=@'
$text=[IO.File]::ReadAllText($source,[Text.Encoding]::UTF8)

# `Args` is a PowerShell automatic variable. Using it as the child-argument parameter
# caused Run(...) calls to drop explicit arguments such as -RepositoryRoot.
$runSignature='function Run([string]$Script,[string[]]$Args){'
$runSignatureCount=[regex]::Matches($text,[regex]::Escape($runSignature)).Count
if($runSignatureCount-ne1){throw('Base materializer Run signature count='+$runSignatureCount)}
if(([regex]::Matches($text,[regex]::Escape('@Args 2>&1'))).Count-ne1){throw 'Base materializer @Args invocation count is not 1.'}
if(([regex]::Matches($text,[regex]::Escape("(`$Args-join' ')"))).Count-ne1){throw 'Base materializer Args diagnostic count is not 1.'}
$text=$text.Replace($runSignature,'function Run([string]$Script,[string[]]$Arguments){')
$text=$text.Replace('@Args 2>&1','@Arguments 2>&1')
$text=$text.Replace("(`$Args-join' ')","(`$Arguments-join' ')")

# Keep the managed README machine-bound to the canonical release-instruction guard.
$releaseIdentityOld='version-independent behavioral regressions, the 4.17.13 review regression'
$releaseIdentityNew='inherited and 4.17.13 regressions, the version-independent behavioral regression suite'
$releaseIdentityCount=[regex]::Matches($text,[regex]::Escape($releaseIdentityOld)).Count
if($releaseIdentityCount-ne1){throw('4.17.13 README regression identity token count='+$releaseIdentityCount)}
$text=$text.Replace($releaseIdentityOld,$releaseIdentityNew)
'@
$text=$text.Replace($anchor,$replacement.TrimEnd())

$tempRoot=Join-Path ([IO.Path]::GetTempPath()) ('keelaryn-41713-r3-'+[guid]::NewGuid().ToString('N'))
$tempR2=Join-Path $tempRoot 'Materialize-Manager41713ProductR2.ps1'
$tempBase=Join-Path $tempRoot 'Materialize-Manager41713Product.ps1'
try{
    [void][IO.Directory]::CreateDirectory($tempRoot)
    [IO.File]::WriteAllText($tempR2,$text,$Utf8)
    Copy-Item -LiteralPath $baseSource -Destination $tempBase -Force
    $tokens=$null;$errors=$null
    [void][Management.Automation.Language.Parser]::ParseFile($tempR2,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){throw('R3 wrapper parser failed: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
    $exe=Join-Path $PSHOME 'powershell.exe'
    & $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $tempR2 -RepositoryRoot $RepositoryRoot -ExpectedBase $ExpectedBase -EvidenceRoot $EvidenceRoot
    exit [int]$LASTEXITCODE
}finally{
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
