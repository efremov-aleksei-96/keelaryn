[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$CandidateRepositoryRoot,
    [Parameter(Mandatory=$true)][string]$BaselineRepositoryRoot
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$Utf8NoBom=New-Object Text.UTF8Encoding($false)

function Fail([string]$Message){throw $Message}
function Assert([bool]$Condition,[string]$Message){if(-not$Condition){Fail $Message}}
function Write-Utf8NoBom([string]$Path,[string]$Text){
    $parent=Split-Path -Parent $Path
    if($parent-and-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
    [IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)
}
function Invoke-Raw([string]$Script,[string[]]$Arguments){
    $exe=Join-Path $PSHOME 'powershell.exe'
    $old=$ErrorActionPreference
    try{
        $ErrorActionPreference='Continue'
        $output=@(& $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Script @Arguments 2>&1|ForEach-Object{[string]$_})
        $exit=[int]$LASTEXITCODE
    }finally{$ErrorActionPreference=$old}
    return [pscustomobject]@{ExitCode=$exit;Output=@($output);Text=[string]::Join("`n",@($output))}
}
function Copy-ManagedManager([string]$SourceManager,[string]$DestinationManager,[string]$ExpectedVersion){
    $installPath=Join-Path $SourceManager 'product\install\INSTALLATION.json'
    Assert (Test-Path -LiteralPath $installPath -PathType Leaf) ('Missing source installation manifest: '+$installPath)
    $install=Get-Content -LiteralPath $installPath -Raw -Encoding UTF8|ConvertFrom-Json
    Assert ([string]$install.schema-ceq'keelaryn.manager.installation.v2') 'Unexpected installation schema.'
    Assert ([string]$install.manager_version-ceq$ExpectedVersion) ('Expected Manager '+$ExpectedVersion+'; observed '+[string]$install.manager_version)
    New-Item -ItemType Directory -Force -Path $DestinationManager|Out-Null
    foreach($raw in @($install.managed_files)){
        $rel=([string]$raw).Replace('/','\')
        $src=Join-Path $SourceManager $rel
        $dst=Join-Path $DestinationManager $rel
        Assert (Test-Path -LiteralPath $src -PathType Leaf) ('Managed source missing: '+$rel)
        $parent=Split-Path -Parent $dst
        if(-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
        Copy-Item -LiteralPath $src -Destination $dst -Force
    }
}
function Test-Version([string]$RepositoryRoot,[string]$Version){
    $temp=Join-Path ([IO.Path]::GetTempPath()) ('keelaryn-doctor-lock-'+$Version.Replace('.','_')+'-'+[guid]::NewGuid().ToString('N'))
    $keelaryn=Join-Path $temp 'keelaryn'
    $manager=Join-Path $keelaryn 'manager'
    $config=Join-Path $temp 'genesis.json'
    $lock=$null
    try{
        New-Item -ItemType Directory -Force -Path $keelaryn|Out-Null
        Copy-ManagedManager (Join-Path $RepositoryRoot 'manager') $manager $Version
        $runtime=Join-Path $manager 'product\runtime\Keelaryn__Manager.ps1'
        $genesis=[ordered]@{schema='keelaryn.genesis-input.v1';language='en';purpose='mixed';timezone='UTC';areas=@('Qualification');projects=@('Doctor report sharing-lock diagnostic')}
        Write-Utf8NoBom $config ((($genesis|ConvertTo-Json -Depth 6).Replace("`r`n","`n"))+"`n")

        $g=Invoke-Raw $runtime @('-Genesis','-GenesisConfigPath',$config,'-GenesisConfirmed')
        Assert ($g.ExitCode-eq0) ('Genesis failed for '+$Version+': '+$g.Text)

        $first=Invoke-Raw $runtime @('-Doctor')
        Assert ($first.ExitCode-eq0) ('Initial Doctor failed for '+$Version+': '+$first.Text)
        $report=Join-Path $manager 'state\logs\DOCTOR_REPORT.json'
        Assert (Test-Path -LiteralPath $report -PathType Leaf) ('Doctor report missing for '+$Version)

        $lock=[IO.File]::Open($report,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::None)
        $locked=Invoke-Raw $runtime @('-Doctor')
        $lock.Dispose();$lock=$null

        $sharingMessage=($locked.Text.Contains('being used by another process') -or $locked.Text.Contains('process cannot access the file'))
        Assert ($locked.ExitCode-eq1) ('Locked Doctor did not fail with exit=1 for '+$Version+'; exit='+$locked.ExitCode+'; output='+$locked.Text)
        Assert $sharingMessage ('Locked Doctor failure was not a Windows sharing violation for '+$Version+': '+$locked.Text)

        $after=Invoke-Raw $runtime @('-Doctor')
        Assert ($after.ExitCode-eq0) ('Doctor did not recover after releasing report lock for '+$Version+': '+$after.Text)

        Write-Host ('DOCTOR_REPORT_LOCK_REPRO '+$Version+': PASS (initial=0 locked=1 released=0)') -ForegroundColor Yellow
        return [pscustomobject]@{Version=$Version;LockedExit=$locked.ExitCode;SharingViolation=$sharingMessage;RecoveredExit=$after.ExitCode}
    }
    finally{
        if($lock){$lock.Dispose()}
        if(Test-Path -LiteralPath $temp){Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue}
    }
}

$candidate=Test-Version ([IO.Path]::GetFullPath($CandidateRepositoryRoot)) '4.17.11'
$baseline=Test-Version ([IO.Path]::GetFullPath($BaselineRepositoryRoot)) '4.17.10'

Assert ($candidate.LockedExit-eq1-and$baseline.LockedExit-eq1) 'Expected deterministic sharing-lock failure was not reproduced in both versions.'
Write-Host 'CLASSIFICATION EVIDENCE: Doctor report sharing-lock failure is deterministic in both frozen 4.17.11 g1 and production-qualified 4.17.10.' -ForegroundColor Cyan
Write-Host 'The failure is pre-existing Manager product resilience behavior, not a 4.17.11 regression and not a Gate Framework false positive.' -ForegroundColor Cyan
