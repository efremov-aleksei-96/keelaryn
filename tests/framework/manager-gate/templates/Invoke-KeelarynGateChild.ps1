[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$SpecPath)

$ErrorActionPreference='Stop'
$utf8=New-Object System.Text.UTF8Encoding($false)
try{[Console]::OutputEncoding=$utf8}catch{}
$OutputEncoding=$utf8
if($PSVersionTable.PSVersion.Major-ne5-or[string]$PSVersionTable.PSEdition-ne'Desktop'){
    throw 'Run this helper with Windows PowerShell 5.1 Desktop.'
}

$SpecPath=[System.IO.Path]::GetFullPath($SpecPath)
$spec=(Get-Content -LiteralPath $SpecPath -Raw -Encoding UTF8)|ConvertFrom-Json
$filePath=[string]$spec.file_path
$processArgs=@($spec.arguments|ForEach-Object{[string]$_})
$exitCodePath=[string]$spec.exit_code_path
if([string]::IsNullOrWhiteSpace($filePath)){throw 'Gate child spec file_path is empty.'}
if([string]::IsNullOrWhiteSpace($exitCodePath)){throw 'Gate child spec exit_code_path is empty.'}

$code=1
try{
    & $filePath @processArgs
    $commandSucceeded=$?
    $observedLastExitCode=$LASTEXITCODE
    if($null-ne$observedLastExitCode){$code=[int]$observedLastExitCode}
    elseif($commandSucceeded){$code=0}
    else{$code=1}
}catch{
    [Console]::Error.WriteLine($_.Exception.ToString())
    $code=1
}finally{
    try{
        $parent=Split-Path -Parent $exitCodePath
        if($parent){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
        [System.IO.File]::WriteAllText($exitCodePath,[string][int]$code,(New-Object System.Text.UTF8Encoding($false)))
    }catch{
        [Console]::Error.WriteLine('Failed to write gate exit-code sidecar: '+$_.Exception.Message)
        $code=125
    }
}
exit [int]$code
