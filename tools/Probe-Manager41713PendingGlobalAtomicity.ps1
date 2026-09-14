[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RepositoryRoot,
    [Parameter(Mandatory=$true)][string]$ExpectedHead,
    [Parameter(Mandatory=$true)][string]$OutputPath
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$ExpectedHead=$ExpectedHead.Trim().ToLowerInvariant()
$Utf8NoBom=New-Object Text.UTF8Encoding($false)

function Fail([string]$Message){throw $Message}
function Write-Utf8([string]$Path,[string]$Text){$parent=Split-Path -Parent $Path;if($parent-and-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null};[IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)}
function Write-Json([string]$Path,$Object){Write-Utf8 $Path ((($Object|ConvertTo-Json -Depth 20).Replace("`r`n","`n"))+"`n")}
function Copy-ManagedManager([string]$Source,[string]$Destination){
    $install=Get-Content -LiteralPath (Join-Path $Source 'product\install\INSTALLATION.json') -Raw -Encoding UTF8|ConvertFrom-Json
    New-Item -ItemType Directory -Force -Path $Destination|Out-Null
    foreach($raw in @($install.managed_files)){
        $rel=([string]$raw).Replace('/','\');$src=Join-Path $Source $rel;$dst=Join-Path $Destination $rel
        if(-not(Test-Path -LiteralPath $src -PathType Leaf)){Fail('Managed source missing: '+$rel)}
        $parent=Split-Path -Parent $dst;if($parent-and-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
        Copy-Item -LiteralPath $src -Destination $dst -Force
    }
    return [string]$install.manager_version
}
function Invoke-Runtime([string]$Runtime,[string[]]$Arguments){
    $exe=Join-Path $PSHOME 'powershell.exe';$old=$ErrorActionPreference
    try{$ErrorActionPreference='Continue';$out=@(& $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Runtime @Arguments 2>&1|ForEach-Object{[string]$_});$code=[int]$LASTEXITCODE}finally{$ErrorActionPreference=$old}
    return [pscustomobject]@{ExitCode=$code;Text=[string]::Join("`n",@($out));Output=@($out)}
}
function Require-Success([string]$Runtime,[string[]]$Arguments,[string]$Purpose){$r=Invoke-Runtime $Runtime $Arguments;foreach($line in @($r.Output)){Write-Host $line};if($r.ExitCode-ne0){Fail($Purpose+' failed: '+$r.Text)};return $r}

$actual=(& git.exe -C $RepositoryRoot rev-parse HEAD).Trim().ToLowerInvariant()
if($actual-cne$ExpectedHead){Fail('Probe checkout mismatch: '+$actual+' expected='+$ExpectedHead)}

$temp=Join-Path ([IO.Path]::GetTempPath()) ('keelaryn-pending-global-atomicity-'+[guid]::NewGuid().ToString('N'))
$harnessError=$null;$result=$null
try{
    $root=Join-Path $temp 'keelaryn';$manager=Join-Path $root 'manager';New-Item -ItemType Directory -Force -Path $root|Out-Null
    $version=Copy-ManagedManager (Join-Path $RepositoryRoot 'manager') $manager
    $runtime=Join-Path $manager 'product\runtime\Keelaryn__Manager.ps1'
    $config=Join-Path $temp 'alpha.json'
    Write-Json $config ([ordered]@{schema='keelaryn.genesis-input.v1';language='en';purpose='mixed';timezone='UTC';areas=@('Qualification');projects=@('Pending global atomicity')})
    $null=Require-Success $runtime @('-Genesis','-GenesisConfigPath',$config,'-GenesisConfirmed') 'Genesis'
    $null=Require-Success $runtime @('-InitializeInstanceRegistry','-RegisterInstanceName','Alpha') 'Registry initialization'

    $state=Join-Path $manager 'state';$registry=Get-Content -LiteralPath (Join-Path $state 'instances.json') -Raw -Encoding UTF8|ConvertFrom-Json
    if(@($registry.instances).Count-ne1){Fail('Expected one registry row; actual='+@($registry.instances).Count)}
    $id=[string]$registry.instances[0].instance_id
    $current=Join-Path $state ('instances\'+$id+'\baseline\Keelaryn__Hub_CURRENT.zip')
    $globalInbox=Join-Path $state 'inbox';$instanceInbox=Join-Path $state ('instances\'+$id+'\inbox')
    foreach($p in @($current,$globalInbox,$instanceInbox)){if(-not(Test-Path -LiteralPath $p)){Fail('Required initialized path missing: '+$p)}}

    # Name ordering is deliberate: the valid object is processed first by Get-GlobalHubOwnedInboxObjects,
    # then a recognized but invalid Hub ZIP fails identity validation. A transactional implementation must
    # not publish the first object into the active per-instance inbox before all inputs pass preflight.
    $validName='Keelaryn__Hub_APPROVED_A_valid.zip';$invalidName='Keelaryn__Hub_APPROVED_Z_invalid.zip'
    $validSource=Join-Path $globalInbox $validName;$invalidSource=Join-Path $globalInbox $invalidName;$validTarget=Join-Path $instanceInbox $validName
    Copy-Item -LiteralPath $current -Destination $validSource -Force
    Write-Utf8 $invalidSource 'not-a-valid-hub-zip'
    $validSha=(Get-FileHash -LiteralPath $validSource -Algorithm SHA256).Hash.ToLowerInvariant()
    if(Test-Path -LiteralPath $validTarget){Fail('Valid target unexpectedly existed before probe: '+$validTarget)}

    $invoke=Invoke-Runtime $runtime @('-InitializeInstanceRegistry')
    foreach($line in @($invoke.Output)){Write-Host $line}
    $validSourceRemains=Test-Path -LiteralPath $validSource -PathType Leaf
    $invalidSourceRemains=Test-Path -LiteralPath $invalidSource -PathType Leaf
    $targetExists=Test-Path -LiteralPath $validTarget -PathType Leaf
    $targetHashOk=$false;if($targetExists){$targetHashOk=((Get-FileHash -LiteralPath $validTarget -Algorithm SHA256).Hash.ToLowerInvariant()-ceq$validSha)}
    $lateFailure=($invoke.ExitCode-ne0)
    $partialMutation=($lateFailure-and$validSourceRemains-and$invalidSourceRemains-and$targetExists-and$targetHashOk)
    $safeFailure=($lateFailure-and$validSourceRemains-and$invalidSourceRemains-and-not$targetExists)
    $result=[ordered]@{
        schema='keelaryn.manager-41713-pending-global-atomicity-probe.v1';manager_version=$version;tested_head=$ExpectedHead
        runtime_exit_code=$invoke.ExitCode;late_failure_observed=$lateFailure;valid_source_remains=$validSourceRemains;invalid_source_remains=$invalidSourceRemains
        valid_target_exists=$targetExists;valid_target_hash_matches=$targetHashOk;partial_durable_handoff_reproduced=$partialMutation;safe_fail_closed_observed=$safeFailure
        output=$invoke.Text;harness_error=$null;completed_utc=[DateTime]::UtcNow.ToString('o')
    }
}catch{$harnessError=$_.Exception.Message;$result=[ordered]@{schema='keelaryn.manager-41713-pending-global-atomicity-probe.v1';tested_head=$ExpectedHead;partial_durable_handoff_reproduced=$false;safe_fail_closed_observed=$false;harness_error=$harnessError;completed_utc=[DateTime]::UtcNow.ToString('o')}}
finally{try{Write-Json $OutputPath $result}catch{Write-Host ('Could not write probe evidence: '+$_.Exception.Message) -ForegroundColor Red};if(Test-Path -LiteralPath $temp){Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue}}

if($harnessError){Write-Host ('PENDING GLOBAL ATOMICITY PROBE: HARNESS ERROR: '+$harnessError) -ForegroundColor Red;exit 2}
if([bool]$result.partial_durable_handoff_reproduced){Write-Host 'PENDING GLOBAL ATOMICITY PROBE: RED - partial per-instance publication occurred before later input validation failed.' -ForegroundColor Red;exit 1}
if([bool]$result.safe_fail_closed_observed){Write-Host 'PENDING GLOBAL ATOMICITY PROBE: PASS - late invalid input caused no per-instance publication.' -ForegroundColor Green;exit 0}
Write-Host 'PENDING GLOBAL ATOMICITY PROBE: INDETERMINATE - expected late-failure contract was not observed.' -ForegroundColor Red
exit 3
