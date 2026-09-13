[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$Utf8NoBom=New-Object Text.UTF8Encoding($false)

function Fail([string]$Message){throw $Message}
function Assert([bool]$Condition,[string]$Message){if(-not$Condition){Fail $Message}}
function Write-Utf8NoBom([string]$Path,[string]$Text){
    $parent=Split-Path -Parent $Path
    if($parent-and-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
    [IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)
}
function Invoke-Captured([string]$Script,[string[]]$Arguments,[string]$Purpose){
    $exe=Join-Path $PSHOME 'powershell.exe'
    $old=$ErrorActionPreference
    try{
        $ErrorActionPreference='Continue'
        $output=@(& $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Script @Arguments 2>&1|ForEach-Object{[string]$_})
        $exit=[int]$LASTEXITCODE
    }finally{$ErrorActionPreference=$old}
    foreach($line in $output){Write-Host $line}
    if($exit-ne0){Fail($Purpose+' failed with exit='+$exit+'; output='+([string]::Join(' | ',$output)))}
    return @($output)
}
function Copy-ManagedManager([string]$SourceManager,[string]$DestinationManager){
    $installPath=Join-Path $SourceManager 'product\install\INSTALLATION.json'
    $install=Get-Content -LiteralPath $installPath -Raw -Encoding UTF8|ConvertFrom-Json
    Assert ([string]$install.schema-ceq'keelaryn.manager.installation.v2') 'Unsupported Manager installation schema in regression source.'
    Assert ([string]$install.manager_version-ceq'4.17.10') ('Regression requires Manager 4.17.10 source; observed '+[string]$install.manager_version)
    New-Item -ItemType Directory -Force -Path $DestinationManager|Out-Null
    foreach($raw in @($install.managed_files)){
        $rel=([string]$raw).Replace('/','\')
        $src=Join-Path $SourceManager $rel
        $dst=Join-Path $DestinationManager $rel
        if(-not(Test-Path -LiteralPath $src -PathType Leaf)){Fail('Managed regression source missing: '+$rel)}
        $parent=Split-Path -Parent $dst
        if(-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
        Copy-Item -LiteralPath $src -Destination $dst -Force
    }
}

$currentInstall=Get-Content -LiteralPath (Join-Path $RepositoryRoot 'manager\product\install\INSTALLATION.json') -Raw -Encoding UTF8|ConvertFrom-Json
$currentVersion=([string]$currentInstall.manager_version).Trim()
if($currentVersion-ceq'4.17.11'){
    $successor=Join-Path $RepositoryRoot 'tools\Invoke-Manager41711ReviewRegression.ps1'
    if(-not(Test-Path -LiteralPath $successor -PathType Leaf)){Fail('Manager 4.17.11 successor review regression missing: '+$successor)}
    $null=Invoke-Captured $successor @('-RepositoryRoot',$RepositoryRoot) 'Manager 4.17.11 successor review regression'
    Write-Host 'MANAGER 4.17.10 REVIEW REGRESSION: PASS VIA 4.17.11 SUCCESSOR CHAIN' -ForegroundColor Green
    exit 0
}
Assert ($currentVersion-ceq'4.17.10') ('Manager 4.17.10 review regression supports 4.17.10 or delegated 4.17.11 source; observed '+$currentVersion)

$inherited=Join-Path $RepositoryRoot 'tools\Invoke-Manager4179ConvergenceRegression.ps1'
if(-not(Test-Path -LiteralPath $inherited -PathType Leaf)){Fail('Inherited 4.17.9 convergence regression missing: '+$inherited)}
$null=Invoke-Captured $inherited @('-RepositoryRoot',$RepositoryRoot) 'Inherited Manager 4.17.9 convergence regression'
Write-Host '  PASS inherited Manager 4.17.9 convergence regression chain'

$sourceManager=Join-Path $RepositoryRoot 'manager'
$tempRoot=Join-Path ([IO.Path]::GetTempPath()) ('keelaryn-manager-41710-doctor-'+[guid]::NewGuid().ToString('N'))
$keelarynRoot=Join-Path $tempRoot 'keelaryn'
$managerRoot=Join-Path $keelarynRoot 'manager'
$config=Join-Path $tempRoot 'genesis.json'
try{
    New-Item -ItemType Directory -Force -Path $keelarynRoot|Out-Null
    Copy-ManagedManager $sourceManager $managerRoot
    $runtime=Join-Path $managerRoot 'product\runtime\Keelaryn__Manager.ps1'
    if(-not(Test-Path -LiteralPath $runtime -PathType Leaf)){Fail 'Disposable runtime missing after managed copy.'}

    $genesis=[ordered]@{
        schema='keelaryn.genesis-input.v1'
        language='en'
        purpose='mixed'
        timezone='UTC'
        areas=@('Qualification')
        projects=@('Manager 4.17.10 registry Doctor')
    }
    Write-Utf8NoBom $config ((($genesis|ConvertTo-Json -Depth 6).Replace("`r`n","`n"))+"`n")

    $null=Invoke-Captured $runtime @('-Genesis','-GenesisConfigPath',$config,'-GenesisConfirmed') 'Disposable Genesis'
    $null=Invoke-Captured $runtime @('-InitializeInstanceRegistry','-RegisterInstanceName','Primary') 'Disposable registry activation'

    $registry=Join-Path $managerRoot 'state\instances.json'
    $active=Join-Path $managerRoot 'state\active_instance.json'
    Assert (Test-Path -LiteralPath $registry -PathType Leaf) 'Registry activation did not publish instances.json.'
    Assert (Test-Path -LiteralPath $active -PathType Leaf) 'Registry activation did not publish active_instance.json.'

    $doctor=@(Invoke-Captured $runtime @('-Doctor') 'Registry-active Doctor')
    $doctorText=[string]::Join("`n",$doctor)
    Assert $doctorText.Contains('Keelaryn Doctor - Manager 4.17.10') 'Registry-active Doctor did not identify Manager 4.17.10.'
    Assert $doctorText.Contains('[OK] instances.registry:') 'Registry-active Doctor did not report the registry finding.'
    Assert $doctorText.Contains('[OK] inbox.hub_global:') 'Registry-active Doctor did not execute the global-Hub-inbox diagnostic path.'
    Assert (-not($doctorText-match '(?m)^\s*\[(WARN|ERROR)\]')) 'Clean registry-active Doctor unexpectedly produced WARN/ERROR.'
    Assert (-not($doctorText-match '(?i)cannot bind argument.*Rows|null.*Rows|uninitialized')) 'Registry-active Doctor exposed an accumulator initialization failure.'
    Write-Host '  PASS real Genesis -> registry activation -> Doctor executes registry-only global-inbox diagnostics' -ForegroundColor Green
}
finally{
    if(Test-Path -LiteralPath $tempRoot){Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue}
}

Write-Host 'MANAGER 4.17.10 REVIEW REGRESSION: PASS' -ForegroundColor Green
