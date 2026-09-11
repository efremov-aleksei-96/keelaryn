[CmdletBinding()]
param(
    [string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'),
    [string]$OutputDirectory=(Join-Path $env:RUNNER_TEMP 'keelaryn-development-validation')
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[System.IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$OutputDirectory=[System.IO.Path]::GetFullPath($OutputDirectory).TrimEnd('\')
$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)

function Fail([string]$Message){throw $Message}
function Sha([string]$Path){
    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){Fail('Hash target missing: '+$Path)}
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Write-Json([string]$Path,$Object){
    $parent=[System.IO.Path]::GetDirectoryName($Path)
    if($parent -and -not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
    $text=(($Object|ConvertTo-Json -Depth 40).Replace("`r`n","`n"))+"`n"
    [System.IO.File]::WriteAllText($Path,$text,$Utf8NoBom)
}
function Parse-File([string]$Path){
    $tokens=$null;$errors=$null
    [void][System.Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors)
    if(@($errors).Count-ne 0){Fail('PowerShell parser failed: '+$Path+'; '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
}
function Invoke-Child([string]$Script,[string[]]$Arguments){
    if($null-eq $Arguments){$Arguments=@()}
    $powershell=Join-Path $PSHOME 'powershell.exe'
    $old=$ErrorActionPreference
    try{
        $ErrorActionPreference='Continue'
        $output=@(& $powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Script @Arguments 2>&1)
        $code=[int]$LASTEXITCODE
    }finally{$ErrorActionPreference=$old}
    foreach($line in @($output)){Write-Host ([string]$line)}
    if($code-ne 0){Fail('Child command failed. exit='+$code+' script='+$Script+' args='+($Arguments-join' ')+' output='+([string]::Join(' | ',@($output))))}
}
function Copy-Managed([string]$Source,[string]$Destination){
    $install=Get-Content -LiteralPath (Join-Path $Source 'product\install\INSTALLATION.json') -Raw -Encoding UTF8|ConvertFrom-Json
    if(Test-Path -LiteralPath $Destination){Remove-Item -LiteralPath $Destination -Recurse -Force}
    [void][System.IO.Directory]::CreateDirectory($Destination)
    foreach($raw in @($install.managed_files)){
        $relative=([string]$raw).Replace('/','\')
        $src=Join-Path $Source $relative
        $dst=Join-Path $Destination $relative
        if(-not(Test-Path -LiteralPath $src -PathType Leaf)){Fail('Managed source missing: '+$relative)}
        $parent=[System.IO.Path]::GetDirectoryName($dst)
        if($parent -and -not [System.IO.Directory]::Exists($parent)){[void][System.IO.Directory]::CreateDirectory($parent)}
        [System.IO.File]::Copy($src,$dst,$true)
    }
}
function Find-One([string]$Root,[string]$Name){
    $rows=@(Get-ChildItem -LiteralPath $Root -File -Recurse -Force -Filter $Name)
    if($rows.Count-ne 1){Fail('Expected one '+$Name+' below '+$Root+'; actual='+$rows.Count)}
    return $rows[0].FullName
}

$manager=Join-Path $RepositoryRoot 'manager'
$installPath=Join-Path $manager 'product\install\INSTALLATION.json'
if(-not(Test-Path -LiteralPath $installPath -PathType Leaf)){Fail 'Manager INSTALLATION.json is missing.'}
$install=Get-Content -LiteralPath $installPath -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$install.schema-cne 'keelaryn.manager.installation.v2'){Fail('Unsupported Manager installation schema: '+[string]$install.schema)}
$version=([string]$install.manager_version).Trim()
if($version-notmatch '^\d+\.\d+\.\d+$'){Fail('Invalid Manager version: '+$version)}

Write-Host ('Keelaryn development validation - Manager '+$version)
Write-Host '[1/5] Parse Manager PowerShell source...'
$psFiles=@(Get-ChildItem -LiteralPath $manager -File -Recurse -Force -Filter '*.ps1')
if($psFiles.Count-eq 0){Fail 'No Manager PowerShell files found.'}
foreach($file in $psFiles){Parse-File $file.FullName}
Write-Host ('Parser: PASS. files='+$psFiles.Count) -ForegroundColor Green

Write-Host '[2/5] Run Manager 4.17.2 review regressions...'
$reviewRegression=Join-Path $RepositoryRoot 'tools\Invoke-Manager4172ReviewRegression.ps1'
if(-not(Test-Path -LiteralPath $reviewRegression -PathType Leaf)){Fail 'Manager 4.17.2 review regression tool is missing.'}
Parse-File $reviewRegression
Invoke-Child $reviewRegression @('-RepositoryRoot',$RepositoryRoot)
Write-Host 'Review regressions: PASS' -ForegroundColor Green

Write-Host '[3/5] Run Manager and frontend SelfTests from source...'
$runtime=Join-Path $manager 'product\runtime\Keelaryn__Manager.ps1'
$menu=Join-Path $manager 'product\tools\KeelarynMenu.ps1'
Invoke-Child $runtime @('-SelfTest')
Invoke-Child $menu @('-SelfTest','-NoRootLauncher')
Write-Host 'SelfTests: PASS' -ForegroundColor Green

Write-Host '[4/5] Run deterministic BuildRelease x2 in isolated disposable Manager roots...'
if(Test-Path -LiteralPath $OutputDirectory){Remove-Item -LiteralPath $OutputDirectory -Recurse -Force}
[void][System.IO.Directory]::CreateDirectory($OutputDirectory)
$buildA=Join-Path $OutputDirectory 'build-a\manager'
$buildB=Join-Path $OutputDirectory 'build-b\manager'
Copy-Managed $manager $buildA
Copy-Managed $manager $buildB

foreach($copy in @($buildA,$buildB)){
    $copyRuntime=Join-Path $copy 'product\runtime\Keelaryn__Manager.ps1'
    Invoke-Child $copyRuntime @('-InitializePresentation')
    Invoke-Child $copyRuntime @('-SelfTest')
    Invoke-Child $copyRuntime @('-BuildRelease')
}

$expected=@(
    [string]::Concat('Keelaryn__Manager_SOURCE_v',$version,'.zip')
    [string]::Concat('Keelaryn__Manager_Distribution_v',$version,'.zip')
    [string]::Concat('Keelaryn__Manager_Update_v',$version,'_Built.zip')
    [string]::Concat('Keelaryn__Manager_AI_CONTEXT_v',$version,'.zip')
    [string]::Concat('Keelaryn__Manager_RELEASE_v',$version,'.json')
)
if($expected.Count-ne 5){Fail('Expected artifact-name set count mismatch: '+$expected.Count)}
$artifacts=New-Object System.Collections.ArrayList
foreach($name in $expected){
    $a=Find-One $buildA $name
    $b=Find-One $buildB $name
    $ha=Sha $a;$hb=Sha $b
    if($ha-cne $hb){Fail('Deterministic BuildRelease mismatch: '+$name+'; '+$ha+' != '+$hb)}
    [void]$artifacts.Add([ordered]@{name=$name;sha256=$ha;bytes=[long](Get-Item -LiteralPath $a -Force).Length})
}
Write-Host 'Deterministic BuildRelease x2: PASS' -ForegroundColor Green

Write-Host '[5/5] Write compact development evidence...'
$report=[ordered]@{
    schema='keelaryn.manager-development-validation.v1'
    classification='development_only'
    manager_version=$version
    source_sha=$env:GITHUB_SHA
    runner=$env:RUNNER_NAME
    parser_files=$psFiles.Count
    review_regressions_pass=$true
    manager_selftest_pass=$true
    frontend_selftest_pass=$true
    deterministic_build_release_pass=$true
    release_artifacts=@($artifacts)
    production_qualified=$false
    candidate_issued=$false
    production_hub_used=$false
    completed_utc=[DateTime]::UtcNow.ToString('o')
}
$evidence=Join-Path $OutputDirectory 'evidence'
[void][System.IO.Directory]::CreateDirectory($evidence)
$reportPath=Join-Path $evidence 'DEVELOPMENT_VALIDATION.json'
Write-Json $reportPath $report

Remove-Item -LiteralPath (Join-Path $OutputDirectory 'build-a') -Recurse -Force
Remove-Item -LiteralPath (Join-Path $OutputDirectory 'build-b') -Recurse -Force

Write-Host ''
Write-Host 'KEELARYN DEVELOPMENT VALIDATION: PASS' -ForegroundColor Green
Write-Host ('Evidence: '+$reportPath)
Write-Host 'Classification: development_only; production_qualified=false'
