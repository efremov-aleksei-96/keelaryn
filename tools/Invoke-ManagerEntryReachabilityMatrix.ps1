[CmdletBinding()]
param(
    [string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'),
    [string]$OutputPath=''
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$Utf8NoBom=New-Object Text.UTF8Encoding($false)

function Fail([string]$Message){throw $Message}
function Write-Utf8([string]$Path,[string]$Text){$parent=Split-Path -Parent $Path;if($parent-and-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null};[IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)}
function Write-Json([string]$Path,$Object){Write-Utf8 $Path ((($Object|ConvertTo-Json -Depth 40).Replace("`r`n","`n"))+"`n")}
function Copy-ManagedManager([string]$SourceManager,[string]$DestinationManager){
    $install=Get-Content -LiteralPath (Join-Path $SourceManager 'product\install\INSTALLATION.json') -Raw -Encoding UTF8|ConvertFrom-Json
    if([string]$install.schema-cne'keelaryn.manager.installation.v2'){Fail 'Unsupported Manager installation schema.'}
    New-Item -ItemType Directory -Force -Path $DestinationManager|Out-Null
    foreach($raw in @($install.managed_files)){
        $rel=([string]$raw).Replace('/','\');$src=Join-Path $SourceManager $rel;$dst=Join-Path $DestinationManager $rel
        if(-not(Test-Path -LiteralPath $src -PathType Leaf)){Fail('Managed source missing: '+$rel)}
        $parent=Split-Path -Parent $dst;if($parent-and-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
        Copy-Item -LiteralPath $src -Destination $dst -Force
    }
    return [string]$install.manager_version
}
function Copy-DirectoryExact([string]$Source,[string]$Destination){
    if(-not(Test-Path -LiteralPath $Source -PathType Container)){Fail('Snapshot source directory missing: '+$Source)}
    if(Test-Path -LiteralPath $Destination){Remove-Item -LiteralPath $Destination -Recurse -Force}
    $parent=Split-Path -Parent $Destination;if($parent-and-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
    Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
}
function Invoke-Runtime([string]$Runtime,[string[]]$Arguments){
    if($null-eq$Arguments){$Arguments=@()};$exe=Join-Path $PSHOME 'powershell.exe';$old=$ErrorActionPreference
    try{$ErrorActionPreference='Continue';$output=@(& $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Runtime @Arguments 2>&1|ForEach-Object{[string]$_});$code=[int]$LASTEXITCODE}finally{$ErrorActionPreference=$old}
    return [pscustomobject]@{ExitCode=$code;Output=@($output);Text=[string]::Join("`n",@($output))}
}
function Invoke-Required([string]$Runtime,[string[]]$Arguments,[string]$Purpose){$r=Invoke-Runtime $Runtime $Arguments;foreach($line in @($r.Output)){Write-Host $line};if($r.ExitCode-ne0){Fail($Purpose+' failed; exit='+$r.ExitCode+'; output='+$r.Text)};return $r}
function Get-TreeDigest([string]$Root){
    if(-not(Test-Path -LiteralPath $Root -PathType Container)){return 'missing'}
    $rows=New-Object System.Collections.ArrayList
    foreach($f in @(Get-ChildItem -LiteralPath $Root -File -Recurse -Force|Sort-Object FullName)){$rel=$f.FullName.Substring($Root.Length).TrimStart('\').Replace('\','/');$h=(Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash.ToLowerInvariant();[void]$rows.Add($rel+'='+$h)}
    $sha=[Security.Cryptography.SHA256]::Create();try{return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes([string]::Join("`n",@($rows))))).Replace('-','').ToLowerInvariant())}finally{$sha.Dispose()}
}
function Read-Registry([string]$ManagerRoot){return Get-Content -LiteralPath (Join-Path $ManagerRoot 'state\instances.json') -Raw -Encoding UTF8|ConvertFrom-Json}
function Read-Active([string]$ManagerRoot){return Get-Content -LiteralPath (Join-Path $ManagerRoot 'state\active_instance.json') -Raw -Encoding UTF8|ConvertFrom-Json}
function Get-PathKey([string]$Path){return [IO.Path]::GetFullPath($Path).TrimEnd('\').ToLowerInvariant()}
function Get-InstalledManagerVersion([string]$ManagerRoot){
    $p=Join-Path $ManagerRoot 'product\install\INSTALLATION.json'
    if(-not(Test-Path -LiteralPath $p -PathType Leaf)){return ''}
    try{return ([string]((Get-Content -LiteralPath $p -Raw -Encoding UTF8|ConvertFrom-Json).manager_version)).Trim()}catch{return ''}
}
function Set-SyntheticManagerVersion([string]$ManagerRoot,[string]$FromVersion,[string]$ToVersion){
    $runtimePath=Join-Path $ManagerRoot 'product\runtime\Keelaryn__Manager.ps1'
    $text=[IO.File]::ReadAllText($runtimePath,[Text.Encoding]::UTF8)
    $old='$ManagerVersion = "'+$FromVersion+'"';$new='$ManagerVersion = "'+$ToVersion+'"'
    if([regex]::Matches($text,[regex]::Escape($old)).Count-ne1){Fail('Synthetic runtime version marker count mismatch for '+$FromVersion)}
    Write-Utf8 $runtimePath ($text.Replace($old,$new))
    foreach($rel in @('product\install\INSTALLATION.json','product\manager_release.json')){
        $p=Join-Path $ManagerRoot $rel;$j=Get-Content -LiteralPath $p -Raw -Encoding UTF8|ConvertFrom-Json;$j.manager_version=$ToVersion;Write-Json $p $j
    }
    $readme=Join-Path $ManagerRoot 'README_FIRST.md';$rt=[IO.File]::ReadAllText($readme,[Text.Encoding]::UTF8)
    $rx=New-Object Text.RegularExpressions.Regex(('(?m)^# Keelaryn Manager '+[regex]::Escape($FromVersion)+'\r?$'))
    if($rx.Matches($rt).Count-ne1){Fail('Synthetic README version header count mismatch for '+$FromVersion)}
    Write-Utf8 $readme ($rx.Replace($rt,('# Keelaryn Manager '+$ToVersion),1))
}
function New-SyntheticSuccessorUpdate([string]$SourceManager,[string]$TempRoot,[string]$CurrentVersion){
    $v=[version]$CurrentVersion;if($v.Build-lt0){Fail('Cannot derive synthetic successor from '+$CurrentVersion)}
    $next=('{0}.{1}.{2}' -f $v.Major,$v.Minor,($v.Build+1))
    $builder=Join-Path $TempRoot 'successor-builder\manager';$null=Copy-ManagedManager $SourceManager $builder
    Set-SyntheticManagerVersion $builder $CurrentVersion $next
    $builderRuntime=Join-Path $builder 'product\runtime\Keelaryn__Manager.ps1'
    $null=Invoke-Required $builderRuntime @('-InitializePresentation') 'Synthetic successor InitializePresentation'
    $null=Invoke-Required $builderRuntime @('-SelfTest') 'Synthetic successor SelfTest'
    $null=Invoke-Required $builderRuntime @('-BuildRelease') 'Synthetic successor BuildRelease'
    $built=Join-Path $builder ('state\releases\Keelaryn__Manager_Update_v'+$next+'_Built.zip')
    if(-not(Test-Path -LiteralPath $built -PathType Leaf)){Fail('Synthetic successor UPDATE missing: '+$built)}
    $fixtureDir=Join-Path $TempRoot 'fixtures';New-Item -ItemType Directory -Force -Path $fixtureDir|Out-Null
    $fixture=Join-Path $fixtureDir ([IO.Path]::GetFileName($built));Copy-Item -LiteralPath $built -Destination $fixture -Force
    return [pscustomobject]@{Version=$next;Path=$fixture;FileName=[IO.Path]::GetFileName($fixture)}
}

$modelPath=Join-Path $RepositoryRoot 'tests\knowledge\entry-reachability.json'
if(-not(Test-Path -LiteralPath $modelPath -PathType Leaf)){Fail 'Entry-reachability model is missing.'}
$model=Get-Content -LiteralPath $modelPath -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$model.schema-cne'keelaryn.manager-entry-reachability.v2'){Fail 'Unsupported entry-reachability model schema.'}
$modelSha=(Get-FileHash -LiteralPath $modelPath -Algorithm SHA256).Hash.ToLowerInvariant()
$stateById=@{};foreach($s in @($model.states)){$stateById[[string]$s.id]=$s}
$actionById=@{};foreach($a in @($model.actions)){$actionById[[string]$a.id]=$a}
$scenarioSpecs=New-Object System.Collections.ArrayList;$ordinal=0
foreach($req in @($model.coverage_requirements)){
    foreach($sid0 in @($req.states)){
        foreach($aid0 in @($req.actions)){
            $ordinal++;$sid=[string]$sid0;$aid=[string]$aid0
            [void]$scenarioSpecs.Add([pscustomobject]@{Id=('ER-{0:D3}' -f $ordinal);Requirement=[string]$req.id;State=$sid;Action=$aid;Mode=[string]$actionById[$aid].expected_mode})
        }
    }
}

$sourceManager=Join-Path $RepositoryRoot 'manager'
$tempRoot=Join-Path ([IO.Path]::GetTempPath()) ('keelaryn-entry-reachability-'+[guid]::NewGuid().ToString('N'))
$keelarynRoot=Join-Path $tempRoot 'keelaryn';$managerRoot=Join-Path $keelarynRoot 'manager'
$configA=Join-Path $tempRoot 'alpha.json';$configB=Join-Path $tempRoot 'beta.json'
$results=New-Object System.Collections.ArrayList;$version='unknown';$harnessError=$null
if([string]::IsNullOrWhiteSpace($OutputPath)){$OutputPath=Join-Path ([IO.Path]::GetTempPath()) ('ENTRY_REACHABILITY_RESULT_'+[guid]::NewGuid().ToString('N')+'.json')}

try{
    New-Item -ItemType Directory -Force -Path $keelarynRoot|Out-Null
    $version=Copy-ManagedManager $sourceManager $managerRoot
    $runtime=Join-Path $managerRoot 'product\runtime\Keelaryn__Manager.ps1'
    foreach($pair in @(@($configA,'Alpha'),@($configB,'Beta'))){$cfg=[ordered]@{schema='keelaryn.genesis-input.v1';language='en';purpose='mixed';timezone='UTC';areas=@('Qualification');projects=@('Entry reachability '+[string]$pair[1])};Write-Json ([string]$pair[0]) $cfg}

    Write-Host ('=== MANAGER ENTRY REACHABILITY MATRIX / '+$version+' ===')
    $null=Invoke-Required $runtime @('-Genesis','-GenesisConfigPath',$configA,'-GenesisConfirmed') 'Alpha Genesis'
    $null=Invoke-Required $runtime @('-InitializeInstanceRegistry','-RegisterInstanceName','Alpha') 'Registry activation'
    $betaPath=Join-Path $keelarynRoot 'hubs\beta'
    $null=Invoke-Required $runtime @('-GenesisInstancePath',$betaPath,'-GenesisInstanceName','Beta','-GenesisConfigPath',$configB,'-GenesisConfirmed') 'Beta registered Genesis'

    $registry=Read-Registry $managerRoot
    if(@($registry.instances).Count-ne2){Fail('Expected two registered Hubs; actual='+@($registry.instances).Count)}
    $alpha=@($registry.instances|Where-Object{[string]$_.name-ceq'Alpha'});$beta=@($registry.instances|Where-Object{[string]$_.name-ceq'Beta'})
    if($alpha.Count-ne1-or$beta.Count-ne1){Fail 'Could not resolve Alpha/Beta registry rows.'};$alpha=$alpha[0];$beta=$beta[0]
    $alphaId=[string]$alpha.instance_id;$betaId=[string]$beta.instance_id;$alphaPath=[string]$alpha.vault_path;$betaPath=[string]$beta.vault_path
    $stateRoot=Join-Path $managerRoot 'state';$alphaCurrent=Join-Path $stateRoot ('instances\'+$alphaId+'\baseline\Keelaryn__Hub_CURRENT.zip');$legacyCurrent=Join-Path $stateRoot 'baseline\Keelaryn__Hub_CURRENT.zip';$activeFile=Join-Path $stateRoot 'active_instance.json'
    foreach($p in @($alphaCurrent,$legacyCurrent,$activeFile)){if(-not(Test-Path -LiteralPath $p -PathType Leaf)){Fail('Required initialized state missing: '+$p)}}

    # Build proof fixtures outside the tested installation. Bind uses a relocated copy with the same immutable instance_id;
    # UpdateManager receives a real valid higher-version UPDATE that must install, self-test and restart.
    $betaRelocatedPath=Join-Path $keelarynRoot 'hubs\beta-relocated';Copy-DirectoryExact $betaPath $betaRelocatedPath
    $successor=New-SyntheticSuccessorUpdate $sourceManager $tempRoot $version

    # Baseline snapshots live outside the tested installation. Scenario reset never invokes Manager runtime.
    # The entire Manager root is restored because UpdateManager is now intentionally mutating product bytes.
    $snapRoot=Join-Path $tempRoot 'snapshots';New-Item -ItemType Directory -Force -Path $snapRoot|Out-Null
    $snapManager=Join-Path $snapRoot 'manager';$snapAlpha=Join-Path $snapRoot 'alpha-hub';$snapBeta=Join-Path $snapRoot 'beta-hub';$snapBetaRelocated=Join-Path $snapRoot 'beta-relocated-hub'
    Copy-DirectoryExact $managerRoot $snapManager;Copy-DirectoryExact $alphaPath $snapAlpha;Copy-DirectoryExact $betaPath $snapBeta;Copy-DirectoryExact $betaRelocatedPath $snapBetaRelocated

    function Reset-ScenarioBaseline {Copy-DirectoryExact $snapManager $managerRoot;Copy-DirectoryExact $snapAlpha $alphaPath;Copy-DirectoryExact $snapBeta $betaPath;Copy-DirectoryExact $snapBetaRelocated $betaRelocatedPath}
    function Apply-DegradedFixture([string]$Fixture){
        switch($Fixture){
            'active_metadata_invalid' {Write-Utf8 $activeFile '{ not-json'}
            'active_hub_missing' {Remove-Item -LiteralPath $alphaPath -Recurse -Force}
            'active_hub_corrupt' {$stateDoc=Join-Path $alphaPath '_System\STATE.md';if(Test-Path -LiteralPath $stateDoc){Remove-Item -LiteralPath $stateDoc -Force}else{Fail('Alpha structural marker missing before corruption fixture: '+$stateDoc)}}
            'active_current_missing' {Remove-Item -LiteralPath $alphaCurrent -Force;Remove-Item -LiteralPath $legacyCurrent -Force}
            'active_current_corrupt' {Write-Utf8 $alphaCurrent 'not-a-zip';Write-Utf8 $legacyCurrent 'not-a-zip'}
            default {Fail('Unknown degraded-state fixture: '+$Fixture)}
        }
    }
    function Get-ActionArguments([string]$Action){
        switch($Action){
            'ListInstances' {return @('-ListInstances')}
            'SwitchInstance' {return @('-SwitchInstanceId',$betaId)}
            'BindInstance' {return @('-BindInstancePath',$betaRelocatedPath,'-RegisterInstanceName','Beta')}
            'UpdateManager' {return @('-UpdateManager')}
            'BuildDistribution' {return @('-BuildDistribution')}
            'BuildRelease' {return @('-BuildRelease')}
            'BuildAIContext' {return @('-BuildAIContext')}
            'Doctor' {return @('-Doctor')}
            'SelfTest' {return @('-SelfTest')}
            'PrepareTests' {return @('-PrepareTests')}
            'InitializePresentation' {return @('-InitializePresentation')}
            'FinalizeFilesystemLayout' {return @('-FinalizeFilesystemLayout')}
            'InitializeInstanceRegistry' {return @('-InitializeInstanceRegistry')}
            'UpdateHub' {return @('-UpdateHub')}
            'UpdateAll' {return @('-UpdateAll')}
            'RepairCurrent' {return @('-RepairCurrentTransport')}
            'BuildCandidateTransport' {return @('-BuildCandidateTransport')}
            'RestoreCandidateTransport' {return @('-RestoreCandidateTransport')}
            default {Fail('Unknown entry-reachability action: '+$Action)}
        }
    }

    foreach($spec in @($scenarioSpecs)){
        $classification='product_contract_failure';$detail='';$exitCode=-999;$pass=$false
        try{
            Reset-ScenarioBaseline
            $fixture=[string]$stateById[$spec.State].fixture;Apply-DegradedFixture $fixture
            $proofMode=[string]$actionById[[string]$spec.Action].proof_mode
            $updateInboxPath=$null
            if([string]$spec.Action-ceq'UpdateManager'){
                $updateInboxPath=Join-Path $managerRoot ('state\inbox\'+[string]$successor.FileName)
                Copy-Item -LiteralPath ([string]$successor.Path) -Destination $updateInboxPath -Force
            }
            $alphaBefore=Get-TreeDigest $alphaPath;$betaBefore=Get-TreeDigest $betaPath;$betaRelocatedBefore=Get-TreeDigest $betaRelocatedPath
            $r=Invoke-Runtime $runtime (Get-ActionArguments $spec.Action);$exitCode=$r.ExitCode
            $hubsUnchanged=((Get-TreeDigest $alphaPath)-ceq$alphaBefore-and(Get-TreeDigest $betaPath)-ceq$betaBefore-and(Get-TreeDigest $betaRelocatedPath)-ceq$betaRelocatedBefore)
            switch([string]$spec.Mode){
                'list_success' {$pass=($r.ExitCode-eq0-and$r.Text.Contains('Registered Hubs:')-and$hubsUnchanged);$detail=if($pass){'real process entry reached registry listing without Hub mutation'}else{'listing unreachable/failed or Hub bytes changed: '+$r.Text}}
                'target_success' {
                    $activeOk=$false;$registryPathOk=$true
                    if($r.ExitCode-eq0){
                        try{
                            $activeOk=([string](Read-Active $managerRoot).instance_id-ceq$betaId)
                            if([string]$spec.Action-ceq'BindInstance'){
                                $rows=@((Read-Registry $managerRoot).instances|Where-Object{[string]$_.instance_id-ceq$betaId})
                                $registryPathOk=($rows.Count-eq1-and(Get-PathKey ([string]$rows[0].vault_path))-ceq(Get-PathKey $betaRelocatedPath))
                            }
                        }catch{$activeOk=$false;$registryPathOk=$false}
                    }
                    $pass=($r.ExitCode-eq0-and$activeOk-and$registryPathOk-and$hubsUnchanged)
                    if([string]$spec.Action-ceq'BindInstance'){$detail=if($pass){'real changed-path rebind committed the relocated Beta path, activated the same instance_id, and left both old/relocated Hub bytes unchanged'}else{'changed-path rebind transaction unreachable/failed, registry path not committed, or Hub bytes changed: '+$r.Text}}
                    else{$detail=if($pass){'healthy requested target became active without moving/cloning Hub bytes'}else{'target-driven recovery unreachable/failed or mutated Hub bytes: '+$r.Text}}
                }
                'global_success' {
                    if([string]$spec.Action-ceq'UpdateManager'){
                        $installed=(Get-InstalledManagerVersion $managerRoot);$restartObserved=$r.Text.Contains('Manager update: no newer valid Manager package was found.');$packageConsumed=(-not(Test-Path -LiteralPath $updateInboxPath -PathType Leaf))
                        $pass=($r.ExitCode-eq0-and$hubsUnchanged-and$installed-ceq[string]$successor.Version-and$restartObserved-and$packageConsumed)
                        $detail=if($pass){'valid disposable successor installed, post-install self-test passed, restarted -UpdateManager reached completion, and Hub bytes stayed unchanged'}else{'real Manager install/restart proof failed; installed='+$installed+' restart='+$restartObserved+' package_consumed='+$packageConsumed+' output='+$r.Text}
                    }else{
                        $pass=($r.ExitCode-eq0-and$hubsUnchanged);$detail=if($pass){'Manager-global action completed independently of degraded Hub context'}else{'Manager-global action blocked/failed or mutated Hub bytes: '+$r.Text}
                    }
                }
                'diagnostic_reached' {$pass=($r.Text.Contains('Keelaryn Doctor - Manager')-and$hubsUnchanged);$detail=if($pass){'Doctor reached diagnostic body and left Hub bytes unchanged; exit='+$r.ExitCode}else{'Doctor was blocked before diagnostic body or mutated Hub bytes: '+$r.Text}}
                'fail_closed' {$pass=($r.ExitCode-ne0-and$hubsUnchanged);$detail=if($pass){'Hub/context-bound action failed closed without Hub mutation'}else{'expected fail-closed outcome not observed: '+$r.Text}}
                default {Fail('Unsupported expected mode: '+[string]$spec.Mode)}
            }
        }catch{
            $classification='harness_or_fixture_error';$detail=$_.Exception.Message;$pass=$false
        }
        [void]$results.Add([ordered]@{id=[string]$spec.Id;requirement=[string]$spec.Requirement;state=[string]$spec.State;action=[string]$spec.Action;expected_mode=[string]$spec.Mode;proof_mode=[string]$actionById[[string]$spec.Action].proof_mode;pass=$pass;classification=if($pass){'pass'}else{$classification};exit_code=$exitCode;detail=$detail})
        Write-Host ('  '+$(if($pass){'PASS'}else{'FAIL'})+' '+$spec.Id+' '+$spec.State+' x '+$spec.Action+' :: '+$detail) -ForegroundColor $(if($pass){'Green'}else{'Red'})
    }
}catch{$harnessError=$_.Exception.Message;Write-Host ('ENTRY MATRIX HARNESS ERROR: '+$harnessError) -ForegroundColor Red}

$failed=@($results|Where-Object{-not[bool]$_.pass})
$report=[ordered]@{
    schema='keelaryn.manager-entry-reachability-result.v2';manager_version=$version;model_sha256=$modelSha;scenario_count=@($scenarioSpecs).Count;executed_count=@($results).Count;pass=($null-eq$harnessError-and$failed.Count-eq0);harness_error=$harnessError;failures=@($failed|ForEach-Object{[string]$_.id});scenarios=@($results);production_hub_used=$false;scenario_reset='direct_external_full_manager_and_hub_snapshot_restore';transactional_proof_revision=2;synthetic_successor_version=[string]$successor.Version;completed_utc=[DateTime]::UtcNow.ToString('o')
}
try{Write-Json $OutputPath $report;Write-Host ('Evidence: '+$OutputPath)}catch{Write-Host ('Could not write entry-reachability evidence: '+$_.Exception.Message) -ForegroundColor Red;if(-not$harnessError){$harnessError=$_.Exception.Message}}
try{if(Test-Path -LiteralPath $tempRoot){Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction Stop}}catch{Write-Warning('Disposable cleanup failed: '+$_.Exception.Message)}

if($harnessError-or$failed.Count-ne0){Write-Host ('MANAGER ENTRY REACHABILITY MATRIX: FAIL; failures='+$failed.Count+'; harness_error='+[bool]$harnessError) -ForegroundColor Red;exit 1}
Write-Host ('MANAGER ENTRY REACHABILITY MATRIX: PASS; scenarios='+@($results).Count) -ForegroundColor Green
exit 0
