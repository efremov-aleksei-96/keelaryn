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
function Test-FileSha([string]$Path,[string]$Expected){return (Test-Path -LiteralPath $Path -PathType Leaf)-and((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()-ceq$Expected)}
function Assert-PowerShellParses([string]$Path,[string]$Purpose){$tokens=$null;$errors=$null;[void][Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors);if(@($errors).Count){Fail($Purpose+' parser failure: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}}
function Set-EntryActionSentinelInstrumentation([string]$Runtime,[string]$Action){
    $text=[IO.File]::ReadAllText($Runtime,[Text.Encoding]::UTF8)
    $probe='if(-not[string]::IsNullOrWhiteSpace([string]$env:KEELARYN_ENTRY_ACTION_SENTINEL)){[IO.File]::WriteAllText([string]$env:KEELARYN_ENTRY_ACTION_SENTINEL,'+[char]39+$Action+[char]39+',[Text.Encoding]::ASCII)}'
    switch($Action){
        'SelfTest' {$anchor='if ($SelfTest) {';$replacement=$anchor+"`r`n    "+$probe}
        'InitializePresentation' {$anchor='if ($InitializePresentation) { $exitCode=Initialize-ManagerPresentationState }';$replacement='if ($InitializePresentation) { '+$probe+'; $exitCode=Initialize-ManagerPresentationState }'}
        default {Fail('Sentinel instrumentation is unsupported for '+$Action)}
    }
    if([regex]::Matches($text,[regex]::Escape($anchor)).Count-ne1){Fail('Sentinel instrumentation anchor count mismatch for '+$Action)}
    Write-Utf8 $Runtime ($text.Replace($anchor,$replacement));Assert-PowerShellParses $Runtime ('Sentinel-instrumented '+$Action+' runtime')
}
function Set-RollbackFaultInstrumentation([string]$Runtime){
    $text=[IO.File]::ReadAllText($Runtime,[Text.Encoding]::UTF8)
    $anchor='[System.IO.File]::Move([string]$plan.Stage,[string]$plan.Destination)'
    if([regex]::Matches($text,[regex]::Escape($anchor)).Count-ne1){Fail 'Rollback fault-injection anchor count mismatch.'}
    $fault="if([string]`$env:KEELARYN_ENTRY_ROLLBACK_FAULT -eq 'source_loss_after_first' -and `$published.Count -ge 1){`$firstPublished=`$published[0];if(Test-Path -LiteralPath ([string]`$firstPublished.Source) -PathType Leaf){Remove-Item -LiteralPath ([string]`$firstPublished.Source) -Force -ErrorAction Stop};throw 'KEELARYN_ENTRY_ROLLBACK_FAULT_AFTER_FIRST_PUBLICATION_WITH_SOURCE_LOSS'};if([string]`$env:KEELARYN_ENTRY_ROLLBACK_FAULT -eq '1' -and `$published.Count -ge 1){throw 'KEELARYN_ENTRY_ROLLBACK_FAULT_AFTER_FIRST_PUBLICATION'}"
    Write-Utf8 $Runtime ($text.Replace($anchor,($fault+"`r`n            "+$anchor)));Assert-PowerShellParses $Runtime 'Rollback-fault-instrumented runtime'
}
function Set-SyntheticManagerVersion([string]$ManagerRoot,[string]$FromVersion,[string]$ToVersion){
    $runtimePath=Join-Path $ManagerRoot 'product\runtime\Keelaryn__Manager.ps1'
    $text=[IO.File]::ReadAllText($runtimePath,[Text.Encoding]::UTF8)
    $old='$ManagerVersion = "'+$FromVersion+'"';$new='$ManagerVersion = "'+$ToVersion+'"'
    if([regex]::Matches($text,[regex]::Escape($old)).Count-ne1){Fail('Synthetic runtime version marker count mismatch for '+$FromVersion)}
    Write-Utf8 $runtimePath ($text.Replace($old,$new))
    foreach($rel in @('product\install\INSTALLATION.json','product\manager_release.json')){$p=Join-Path $ManagerRoot $rel;$j=Get-Content -LiteralPath $p -Raw -Encoding UTF8|ConvertFrom-Json;$j.manager_version=$ToVersion;Write-Json $p $j}
    $readme=Join-Path $ManagerRoot 'README_FIRST.md';$rt=[IO.File]::ReadAllText($readme,[Text.Encoding]::UTF8)
    $rx=New-Object Text.RegularExpressions.Regex(('(?m)^# Keelaryn Manager '+[regex]::Escape($FromVersion)+'\r?$'))
    if($rx.Matches($rt).Count-ne1){Fail('Synthetic README version header count mismatch for '+$FromVersion)}
    Write-Utf8 $readme ($rx.Replace($rt,('# Keelaryn Manager '+$ToVersion),1))
}
function New-SyntheticSuccessorUpdate([string]$SourceManager,[string]$TempRoot,[string]$CurrentVersion){
    $v=[version]$CurrentVersion;if($v.Build-lt0){Fail('Cannot derive synthetic successor from '+$CurrentVersion)}
    $next=('{0}.{1}.{2}' -f $v.Major,$v.Minor,($v.Build+1));$builder=Join-Path $TempRoot 'successor-builder\manager';$null=Copy-ManagedManager $SourceManager $builder
    Set-SyntheticManagerVersion $builder $CurrentVersion $next;$builderRuntime=Join-Path $builder 'product\runtime\Keelaryn__Manager.ps1'
    $null=Invoke-Required $builderRuntime @('-InitializePresentation') 'Synthetic successor InitializePresentation';$null=Invoke-Required $builderRuntime @('-SelfTest') 'Synthetic successor SelfTest';$null=Invoke-Required $builderRuntime @('-BuildRelease') 'Synthetic successor BuildRelease'
    $built=Join-Path $builder ('state\releases\Keelaryn__Manager_Update_v'+$next+'_Built.zip');if(-not(Test-Path -LiteralPath $built -PathType Leaf)){Fail('Synthetic successor UPDATE missing: '+$built)}
    $fixtureDir=Join-Path $TempRoot 'fixtures';New-Item -ItemType Directory -Force -Path $fixtureDir|Out-Null;$fixture=Join-Path $fixtureDir ([IO.Path]::GetFileName($built));Copy-Item -LiteralPath $built -Destination $fixture -Force
    return [pscustomobject]@{Version=$next;Path=$fixture;FileName=[IO.Path]::GetFileName($fixture)}
}

$modelPath=Join-Path $RepositoryRoot 'tests\knowledge\entry-reachability.json';$supplementPath=Join-Path $RepositoryRoot 'tests\knowledge\entry-reachability-supplemental.json'
foreach($p in @($modelPath,$supplementPath)){if(-not(Test-Path -LiteralPath $p -PathType Leaf)){Fail('Entry-reachability knowledge file is missing: '+$p)}}
$model=Get-Content -LiteralPath $modelPath -Raw -Encoding UTF8|ConvertFrom-Json;$supplement=Get-Content -LiteralPath $supplementPath -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$model.schema-cne'keelaryn.manager-entry-reachability.v2'){Fail 'Unsupported entry-reachability model schema.'}
if([string]$supplement.schema-cne'keelaryn.manager-entry-reachability-supplemental.v1'){Fail 'Unsupported entry-reachability supplemental schema.'}
if(@($supplement.scenarios).Count-ne2){Fail('Entry-reachability supplemental scenario count must be exactly 2; actual='+@($supplement.scenarios).Count)}
$modelSha=(Get-FileHash -LiteralPath $modelPath -Algorithm SHA256).Hash.ToLowerInvariant();$supplementSha=(Get-FileHash -LiteralPath $supplementPath -Algorithm SHA256).Hash.ToLowerInvariant()
$stateById=@{};foreach($s in @($model.states)){$stateById[[string]$s.id]=$s};$actionById=@{};foreach($a in @($model.actions)){$actionById[[string]$a.id]=$a}
$scenarioSpecs=New-Object System.Collections.ArrayList;$ordinal=0
foreach($req in @($model.coverage_requirements)){foreach($sid0 in @($req.states)){foreach($aid0 in @($req.actions)){$ordinal++;$sid=[string]$sid0;$aid=[string]$aid0;$mode=[string]$actionById[$aid].expected_mode;if($null-ne$req.PSObject.Properties['expected_mode']-and-not[string]::IsNullOrWhiteSpace([string]$req.expected_mode)){$mode=[string]$req.expected_mode};[void]$scenarioSpecs.Add([pscustomobject]@{Id=('ER-{0:D3}' -f $ordinal);Requirement=[string]$req.id;State=$sid;Action=$aid;Mode=$mode;Fixture=[string]$stateById[$sid].fixture;Supplemental=$false})}}}
if($scenarioSpecs.Count-ne102){Fail('Canonical entry-reachability scenario count must remain 102; actual='+$scenarioSpecs.Count)}
foreach($s in @($supplement.scenarios)){
    if([string]$s.state-cne'REGISTRY_PENDING_GLOBAL'-or[string]$s.action-cne'InitializeInstanceRegistry'-or[string]$s.fixture-cne'registry_pending_global_rollback_fault'){Fail('Supplemental rollback scenario common identity/contract mismatch: '+[string]$s.id)}
    switch([string]$s.id){
        'ER-103' {if([string]$s.expected_mode-cne'registry_init_publication_fault_rolls_back_batch'-or[string]$s.proof_mode-cne'phase4_fault_after_first_verified_publication'){Fail 'ER-103 rollback scenario contract mismatch.'}}
        'ER-104' {if([string]$s.expected_mode-cne'registry_init_publication_fault_preserves_verified_destination_on_source_loss'-or[string]$s.proof_mode-cne'phase4_fault_after_first_publication_with_source_loss'){Fail 'ER-104 rollback source-loss scenario contract mismatch.'}}
        default {Fail('Unknown supplemental rollback scenario: '+[string]$s.id)}
    }
    [void]$scenarioSpecs.Add([pscustomobject]@{Id=[string]$s.id;Requirement=[string]$s.requirement;State=[string]$s.state;Action=[string]$s.action;Mode=[string]$s.expected_mode;Fixture=[string]$s.fixture;ProofMode=[string]$s.proof_mode;Supplemental=$true})
}
if($scenarioSpecs.Count-ne104){Fail('Total executable entry-reachability scenario count must be 104; actual='+$scenarioSpecs.Count)}

$sourceManager=Join-Path $RepositoryRoot 'manager';$tempRoot=Join-Path ([IO.Path]::GetTempPath()) ('keelaryn-entry-reachability-'+[guid]::NewGuid().ToString('N'));$keelarynRoot=Join-Path $tempRoot 'keelaryn';$managerRoot=Join-Path $keelarynRoot 'manager';$configA=Join-Path $tempRoot 'alpha.json';$configB=Join-Path $tempRoot 'beta.json'
$results=New-Object System.Collections.ArrayList;$version='unknown';$harnessError=$null;$successor=$null
if([string]::IsNullOrWhiteSpace($OutputPath)){$OutputPath=Join-Path ([IO.Path]::GetTempPath()) ('ENTRY_REACHABILITY_RESULT_'+[guid]::NewGuid().ToString('N')+'.json')}

try{
    New-Item -ItemType Directory -Force -Path $keelarynRoot|Out-Null;$version=Copy-ManagedManager $sourceManager $managerRoot;$runtime=Join-Path $managerRoot 'product\runtime\Keelaryn__Manager.ps1'
    foreach($pair in @(@($configA,'Alpha'),@($configB,'Beta'))){$cfg=[ordered]@{schema='keelaryn.genesis-input.v1';language='en';purpose='mixed';timezone='UTC';areas=@('Qualification');projects=@('Entry reachability '+[string]$pair[1])};Write-Json ([string]$pair[0]) $cfg}
    Write-Host ('=== MANAGER ENTRY REACHABILITY MATRIX / '+$version+' ===');$null=Invoke-Required $runtime @('-Genesis','-GenesisConfigPath',$configA,'-GenesisConfirmed') 'Alpha Genesis';$null=Invoke-Required $runtime @('-InitializeInstanceRegistry','-RegisterInstanceName','Alpha') 'Registry activation'
    $betaPath=Join-Path $keelarynRoot 'hubs\beta';$null=Invoke-Required $runtime @('-GenesisInstancePath',$betaPath,'-GenesisInstanceName','Beta','-GenesisConfigPath',$configB,'-GenesisConfirmed') 'Beta registered Genesis'
    $registry=Read-Registry $managerRoot;if(@($registry.instances).Count-ne2){Fail('Expected two registered Hubs; actual='+@($registry.instances).Count)}
    $alpha=@($registry.instances|Where-Object{[string]$_.name-ceq'Alpha'});$beta=@($registry.instances|Where-Object{[string]$_.name-ceq'Beta'});if($alpha.Count-ne1-or$beta.Count-ne1){Fail 'Could not resolve Alpha/Beta registry rows.'};$alpha=$alpha[0];$beta=$beta[0]
    $alphaId=[string]$alpha.instance_id;$betaId=[string]$beta.instance_id;$alphaPath=[string]$alpha.vault_path;$betaPath=[string]$beta.vault_path;$stateRoot=Join-Path $managerRoot 'state';$alphaCurrent=Join-Path $stateRoot ('instances\'+$alphaId+'\baseline\Keelaryn__Hub_CURRENT.zip');$legacyCurrent=Join-Path $stateRoot 'baseline\Keelaryn__Hub_CURRENT.zip';$activeFile=Join-Path $stateRoot 'active_instance.json';$globalInbox=Join-Path $stateRoot 'inbox';$alphaInbox=Join-Path $stateRoot ('instances\'+$alphaId+'\inbox')
    foreach($p in @($alphaCurrent,$legacyCurrent,$activeFile)){if(-not(Test-Path -LiteralPath $p -PathType Leaf)){Fail('Required initialized state missing: '+$p)}}
    $betaRelocatedPath=Join-Path $keelarynRoot 'hubs\beta-relocated';Copy-DirectoryExact $betaPath $betaRelocatedPath;$successor=New-SyntheticSuccessorUpdate $sourceManager $tempRoot $version
    $snapRoot=Join-Path $tempRoot 'snapshots';New-Item -ItemType Directory -Force -Path $snapRoot|Out-Null;$snapManager=Join-Path $snapRoot 'manager';$snapAlpha=Join-Path $snapRoot 'alpha-hub';$snapBeta=Join-Path $snapRoot 'beta-hub';$snapBetaRelocated=Join-Path $snapRoot 'beta-relocated-hub';Copy-DirectoryExact $managerRoot $snapManager;Copy-DirectoryExact $alphaPath $snapAlpha;Copy-DirectoryExact $betaPath $snapBeta;Copy-DirectoryExact $betaRelocatedPath $snapBetaRelocated

    function Reset-ScenarioBaseline {Copy-DirectoryExact $snapManager $managerRoot;Copy-DirectoryExact $snapAlpha $alphaPath;Copy-DirectoryExact $snapBeta $betaPath;Copy-DirectoryExact $snapBetaRelocated $betaRelocatedPath}
    function Apply-DegradedFixture([string]$Fixture){
        $script:ScenarioPendingGlobalSource=$null;$script:ScenarioPendingGlobalTarget=$null;$script:ScenarioPendingGlobalSha=$null;$script:ScenarioPendingGlobalInvalidSource=$null;$script:ScenarioPendingGlobalSources=@();$script:ScenarioPendingGlobalTargets=@();$script:ScenarioPendingGlobalHashes=@()
        switch($Fixture){
            'registry_document_invalid' {Write-Utf8 (Join-Path $stateRoot 'instances.json') '{ not-json'}
            'registry_healthy' {}
            'inactive_hub_missing' {Remove-Item -LiteralPath $betaPath -Recurse -Force}
            'inactive_hub_corrupt' {$stateDoc=Join-Path $betaPath '_System\STATE.md';if(Test-Path -LiteralPath $stateDoc){Remove-Item -LiteralPath $stateDoc -Force}else{Fail('Beta structural marker missing before corruption fixture: '+$stateDoc)}}
            'registry_pending_global' {$name='Keelaryn__Hub_APPROVED_entry-reachability.zip';$dst=Join-Path $globalInbox $name;Copy-Item -LiteralPath $alphaCurrent -Destination $dst -Force;$script:ScenarioPendingGlobalSource=$dst;$script:ScenarioPendingGlobalTarget=Join-Path $alphaInbox $name;$script:ScenarioPendingGlobalSha=(Get-FileHash -LiteralPath $dst -Algorithm SHA256).Hash.ToLowerInvariant()}
            'registry_pending_global_mixed_invalid' {$validName='Keelaryn__Hub_APPROVED_A_entry-reachability.zip';$invalidName='Keelaryn__Hub_APPROVED_Z_entry-reachability.zip';$valid=Join-Path $globalInbox $validName;$invalid=Join-Path $globalInbox $invalidName;Copy-Item -LiteralPath $alphaCurrent -Destination $valid -Force;Write-Utf8 $invalid 'not-a-valid-hub-zip';$script:ScenarioPendingGlobalSource=$valid;$script:ScenarioPendingGlobalInvalidSource=$invalid;$script:ScenarioPendingGlobalTarget=Join-Path $alphaInbox $validName;$script:ScenarioPendingGlobalSha=(Get-FileHash -LiteralPath $valid -Algorithm SHA256).Hash.ToLowerInvariant()}
            'registry_pending_global_rollback_fault' {foreach($suffix in @('A','B')){$name='Keelaryn__Hub_APPROVED_'+$suffix+'_rollback-proof.zip';$src=Join-Path $globalInbox $name;$target=Join-Path $alphaInbox $name;Copy-Item -LiteralPath $alphaCurrent -Destination $src -Force;$sha=(Get-FileHash -LiteralPath $src -Algorithm SHA256).Hash.ToLowerInvariant();$script:ScenarioPendingGlobalSources+=,$src;$script:ScenarioPendingGlobalTargets+=,$target;$script:ScenarioPendingGlobalHashes+=,$sha}}
            'registry_pending_instance' {$name='Keelaryn__Hub_APPROVED_entry-reachability.zip';Copy-Item -LiteralPath $alphaCurrent -Destination (Join-Path $alphaInbox $name) -Force}
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
        $classification='product_contract_failure';$detail='';$exitCode=-999;$pass=$false;$oldSentinel=$env:KEELARYN_ENTRY_ACTION_SENTINEL;$oldFault=$env:KEELARYN_ENTRY_ROLLBACK_FAULT
        try{
            Reset-ScenarioBaseline;Apply-DegradedFixture ([string]$spec.Fixture);$proofMode=[string]$actionById[[string]$spec.Action].proof_mode;$updateInboxPath=$null;$sentinelPath=$null
            if([string]$spec.Action-ceq'UpdateManager'){$updateInboxPath=Join-Path $managerRoot ('state\inbox\'+[string]$successor.FileName);Copy-Item -LiteralPath ([string]$successor.Path) -Destination $updateInboxPath -Force}
            if([string]$spec.Action-ceq'PrepareTests' -and (Test-Path -LiteralPath (Join-Path $keelarynRoot 'tests'))){Remove-Item -LiteralPath (Join-Path $keelarynRoot 'tests') -Recurse -Force}
            if([string]$spec.Mode-ceq'global_success' -and @('SelfTest','InitializePresentation') -ccontains [string]$spec.Action){$sentinelPath=Join-Path $tempRoot ('dispatch-'+[string]$spec.Id+'.txt');if(Test-Path -LiteralPath $sentinelPath){Remove-Item -LiteralPath $sentinelPath -Force};Set-EntryActionSentinelInstrumentation $runtime ([string]$spec.Action);$env:KEELARYN_ENTRY_ACTION_SENTINEL=$sentinelPath}else{$env:KEELARYN_ENTRY_ACTION_SENTINEL=$null}
            if([string]$spec.Mode-ceq'registry_init_publication_fault_rolls_back_batch'){Set-RollbackFaultInstrumentation $runtime;$env:KEELARYN_ENTRY_ROLLBACK_FAULT='1'}elseif([string]$spec.Mode-ceq'registry_init_publication_fault_preserves_verified_destination_on_source_loss'){Set-RollbackFaultInstrumentation $runtime;$env:KEELARYN_ENTRY_ROLLBACK_FAULT='source_loss_after_first'}else{$env:KEELARYN_ENTRY_ROLLBACK_FAULT=$null}
            $alphaBefore=Get-TreeDigest $alphaPath;$betaBefore=Get-TreeDigest $betaPath;$betaRelocatedBefore=Get-TreeDigest $betaRelocatedPath;$registryControl=Join-Path $stateRoot 'instances.json';$registryBefore=if(Test-Path -LiteralPath $registryControl -PathType Leaf){(Get-FileHash -LiteralPath $registryControl -Algorithm SHA256).Hash.ToLowerInvariant()}else{'missing'};$activeBefore=if(Test-Path -LiteralPath $activeFile -PathType Leaf){(Get-FileHash -LiteralPath $activeFile -Algorithm SHA256).Hash.ToLowerInvariant()}else{'missing'};$instancesStatePath=Join-Path $stateRoot 'instances';$compatBaselinePath=Join-Path $stateRoot 'baseline';$instancesStateBefore=Get-TreeDigest $instancesStatePath;$compatBaselineBefore=Get-TreeDigest $compatBaselinePath
            $r=Invoke-Runtime $runtime (Get-ActionArguments $spec.Action);$exitCode=$r.ExitCode
            $hubsUnchanged=((Get-TreeDigest $alphaPath)-ceq$alphaBefore-and(Get-TreeDigest $betaPath)-ceq$betaBefore-and(Get-TreeDigest $betaRelocatedPath)-ceq$betaRelocatedBefore);$registryAfter=if(Test-Path -LiteralPath $registryControl -PathType Leaf){(Get-FileHash -LiteralPath $registryControl -Algorithm SHA256).Hash.ToLowerInvariant()}else{'missing'};$activeAfter=if(Test-Path -LiteralPath $activeFile -PathType Leaf){(Get-FileHash -LiteralPath $activeFile -Algorithm SHA256).Hash.ToLowerInvariant()}else{'missing'};$controlStateUnchanged=($registryAfter-ceq$registryBefore-and$activeAfter-ceq$activeBefore);$instancesStateAfter=Get-TreeDigest $instancesStatePath;$compatBaselineAfter=Get-TreeDigest $compatBaselinePath;$lifecycleStateUnchanged=($controlStateUnchanged-and$instancesStateAfter-ceq$instancesStateBefore-and$compatBaselineAfter-ceq$compatBaselineBefore)
            switch([string]$spec.Mode){
                'list_success' {$pass=($r.ExitCode-eq0-and$r.Text.Contains('Registered Hubs:')-and$hubsUnchanged-and$lifecycleStateUnchanged);$detail=if($pass){'real process entry reached registry listing without Hub mutation'}else{'listing unreachable/failed or Hub bytes changed: '+$r.Text}}
                'target_success' {$activeOk=$false;$registryPathOk=$true;if($r.ExitCode-eq0){try{$activeOk=([string](Read-Active $managerRoot).instance_id-ceq$betaId);if([string]$spec.Action-ceq'BindInstance'){$rows=@((Read-Registry $managerRoot).instances|Where-Object{[string]$_.instance_id-ceq$betaId});$registryPathOk=($rows.Count-eq1-and(Get-PathKey ([string]$rows[0].vault_path))-ceq(Get-PathKey $betaRelocatedPath))}}catch{$activeOk=$false;$registryPathOk=$false}};$pass=($r.ExitCode-eq0-and$activeOk-and$registryPathOk-and$hubsUnchanged);if([string]$spec.Action-ceq'BindInstance'){$detail=if($pass){'real changed-path rebind committed the relocated Beta path, activated the same instance_id, and left both old/relocated Hub bytes unchanged'}else{'changed-path rebind transaction unreachable/failed, registry path not committed, or Hub bytes changed: '+$r.Text}}else{$detail=if($pass){'healthy requested target became active without moving/cloning Hub bytes'}else{'target-driven recovery unreachable/failed or mutated Hub bytes: '+$r.Text}}}
                'global_success' {
                    if([string]$spec.Action-ceq'UpdateManager'){$installed=(Get-InstalledManagerVersion $managerRoot);$restartObserved=$r.Text.Contains('Manager update: no newer valid Manager package was found.');$packageConsumed=(-not(Test-Path -LiteralPath $updateInboxPath -PathType Leaf));$pass=($r.ExitCode-eq0-and$hubsUnchanged-and$lifecycleStateUnchanged-and$installed-ceq[string]$successor.Version-and$restartObserved-and$packageConsumed);$detail=if($pass){'valid disposable successor installed, post-install self-test passed, restarted -UpdateManager reached completion, and Hub bytes stayed unchanged'}else{'real Manager install/restart proof failed; installed='+$installed+' restart='+$restartObserved+' package_consumed='+$packageConsumed+' output='+$r.Text}}
                    elseif([string]$spec.Action-ceq'InitializeInstanceRegistry'){$pass=($r.ExitCode-eq0-and$hubsUnchanged-and$lifecycleStateUnchanged-and$r.Text.Contains('Multi-Hub registry is already initialized and valid.'));$detail=if($pass){'existing-registry initialization remained reachable and preserved Hub lifecycle state'}else{'existing-registry initialization did not reach intended idempotent/recovery success or mutated lifecycle state: '+$r.Text}}
                    elseif($proofMode-ceq'manager_global_execution'){
                        $evidenceOk=$false;$evidence=''
                        switch([string]$spec.Action){
                            'BuildDistribution' {$artifact=Join-Path $managerRoot ('state\releases\Keelaryn__Manager_Distribution_v'+$version+'.zip');$evidenceOk=($r.Text.Contains('Generic distribution:')-and(Test-Path -LiteralPath $artifact -PathType Leaf));$evidence='distribution marker+artifact'}
                            'BuildRelease' {
                                $releaseRoot=Join-Path $managerRoot 'state\releases'
                                $names=@(
                                    ('Keelaryn__Manager_SOURCE_v'+$version+'.zip'),
                                    ('Keelaryn__Manager_Distribution_v'+$version+'.zip'),
                                    ('Keelaryn__Manager_Update_v'+$version+'_Built.zip'),
                                    ('Keelaryn__Manager_AI_CONTEXT_v'+$version+'.zip'),
                                    ('Keelaryn__Manager_RELEASE_v'+$version+'.json')
                                )
                                $missing=New-Object System.Collections.ArrayList
                                foreach($name in @($names)){
                                    $expectedPath=Join-Path $releaseRoot ([string]$name)
                                    if(-not(Test-Path -LiteralPath $expectedPath -PathType Leaf)){[void]$missing.Add([string]$name)}
                                }
                                $evidenceOk=($r.Text.Contains('Release build: PASS')-and$missing.Count-eq0)
                                $evidence='release PASS marker+five-artifact bundle'
                                if($missing.Count-ne0){$evidence+='; missing='+[string]::Join(',',@($missing))}
                            }
                            'BuildAIContext' {$artifact=Join-Path $managerRoot ('state\releases\Keelaryn__Manager_AI_CONTEXT_v'+$version+'.zip');$evidenceOk=($r.Text.Contains('AI_CONTEXT build: PASS')-and(Test-Path -LiteralPath $artifact -PathType Leaf));$evidence='AI_CONTEXT marker+artifact'}
                            'SelfTest' {$evidenceOk=($sentinelPath-and(Test-Path -LiteralPath $sentinelPath -PathType Leaf)-and([IO.File]::ReadAllText($sentinelPath,[Text.Encoding]::ASCII)-ceq'SelfTest'));$evidence='test-only exact SelfTest dispatch sentinel'}
                            'PrepareTests' {$receipt=Join-Path $keelarynRoot 'tests\WORKSPACE.json';$evidenceOk=($r.Text.Contains('Keelaryn tests workspace ready.')-and(Test-Path -LiteralPath $receipt -PathType Leaf));$evidence='tests-workspace marker+receipt'}
                            'InitializePresentation' {$evidenceOk=($sentinelPath-and(Test-Path -LiteralPath $sentinelPath -PathType Leaf)-and([IO.File]::ReadAllText($sentinelPath,[Text.Encoding]::ASCII)-ceq'InitializePresentation'));$evidence='test-only exact InitializePresentation dispatch sentinel'}
                            'FinalizeFilesystemLayout' {$layout=Join-Path $managerRoot 'state\layout.json';$evidenceOk=($r.Text.Contains('Manager filesystem layout is already finalized.')-and(Test-Path -LiteralPath $layout -PathType Leaf));$evidence='already-finalized marker+layout receipt'}
                            default {Fail('manager_global_execution proof_mode lacks action-specific oracle for '+[string]$spec.Action)}
                        }
                        $pass=($r.ExitCode-eq0-and$hubsUnchanged-and$lifecycleStateUnchanged-and$evidenceOk);$detail=if($pass){'Manager-global action reached its action-specific proof ('+$evidence+') without Hub lifecycle mutation'}else{'Manager-global action-specific proof failed ('+$evidence+'): '+$r.Text}
                    }else{Fail('Unsupported global_success proof_mode '+$proofMode+' for '+[string]$spec.Action)}
                }
                'diagnostic_reached' {$pass=($r.Text.Contains('Keelaryn Doctor - Manager')-and$hubsUnchanged-and$lifecycleStateUnchanged);$detail=if($pass){'Doctor reached diagnostic body and preserved Hub lifecycle state; exit='+$r.ExitCode}else{'Doctor was blocked before diagnostic body or mutated Hub lifecycle state: '+$r.Text}}
                'registry_document_rejected_after_dispatch' {$startupBlocked=$r.Text.Contains('Invalid Keelaryn multi-Hub registry:');$operationReached=$r.Text.Contains('Manager instance registry JSON is invalid:');$pass=($r.ExitCode-ne0-and$hubsUnchanged-and$lifecycleStateUnchanged-and-not$startupBlocked-and$operationReached);$detail=if($pass){'unsafe registry passed startup allow-dispatch, reached action-level parsing, and was rejected without lifecycle mutation'}else{'action-level unsafe-registry rejection was not proven, startup blocked first, or state mutated: '+$r.Text}}
                'registry_init_rejected_after_dispatch' {$reached=$r.Text.Contains('Existing multi-Hub registry is invalid:');$pass=($r.ExitCode-ne0-and$hubsUnchanged-and$lifecycleStateUnchanged-and$reached);$detail=if($pass){'InitializeInstanceRegistry reached its existing-registry validator and rejected invalid authoritative registry state without mutation'}else{'registry initialization was blocked before operation-specific validation, succeeded unexpectedly, or mutated state: '+$r.Text}}
                'registry_init_reconciles_global_input' {$sourceConsumed=($script:ScenarioPendingGlobalSource-and-not(Test-Path -LiteralPath $script:ScenarioPendingGlobalSource -PathType Leaf));$targetOk=$false;if($script:ScenarioPendingGlobalTarget-and(Test-Path -LiteralPath $script:ScenarioPendingGlobalTarget -PathType Leaf)){$targetOk=((Get-FileHash -LiteralPath $script:ScenarioPendingGlobalTarget -Algorithm SHA256).Hash.ToLowerInvariant()-ceq[string]$script:ScenarioPendingGlobalSha)};$pass=($r.ExitCode-eq0-and$hubsUnchanged-and$controlStateUnchanged-and$compatBaselineAfter-ceq$compatBaselineBefore-and$sourceConsumed-and$targetOk-and$r.Text.Contains('Reconciled 1 identity-bound Hub input(s)'));$detail=if($pass){'InitializeInstanceRegistry moved the validated identity-bound global input into the active registered per-instance inbox while preserving registry/active/baseline state'}else{'pending-global Initialize reconciliation proof failed: '+$r.Text}}
                'registry_init_mixed_invalid_rejected_without_partial_handoff' {$validSourceRemains=($script:ScenarioPendingGlobalSource-and(Test-Path -LiteralPath $script:ScenarioPendingGlobalSource -PathType Leaf));$invalidSourceRemains=($script:ScenarioPendingGlobalInvalidSource-and(Test-Path -LiteralPath $script:ScenarioPendingGlobalInvalidSource -PathType Leaf));$targetAbsent=($script:ScenarioPendingGlobalTarget-and-not(Test-Path -LiteralPath $script:ScenarioPendingGlobalTarget));$pass=($r.ExitCode-ne0-and$hubsUnchanged-and$lifecycleStateUnchanged-and$validSourceRemains-and$invalidSourceRemains-and$targetAbsent);$detail=if($pass){'mixed valid/invalid stranded-input batch failed before any per-instance destination publication and preserved both global sources plus Hub lifecycle state'}else{'mixed pending-global atomicity proof failed: '+$r.Text}}
                'registry_init_publication_fault_rolls_back_batch' {$sourcesOk=$script:ScenarioPendingGlobalSources.Count-eq2;$targetsAbsent=$script:ScenarioPendingGlobalTargets.Count-eq2;for($i=0;$i-lt$script:ScenarioPendingGlobalSources.Count;$i++){$sourcesOk=$sourcesOk-and(Test-FileSha ([string]$script:ScenarioPendingGlobalSources[$i]) ([string]$script:ScenarioPendingGlobalHashes[$i]))};foreach($target in @($script:ScenarioPendingGlobalTargets)){$targetsAbsent=$targetsAbsent-and-not(Test-Path -LiteralPath ([string]$target));$parent=Split-Path -Parent ([string]$target);if(Test-Path -LiteralPath $parent -PathType Container){$stages=@(Get-ChildItem -LiteralPath $parent -File -Force -ErrorAction SilentlyContinue|Where-Object{$_.Name-like'*.stage.*'});$targetsAbsent=$targetsAbsent-and$stages.Count-eq0}};$rollbackReported=$r.Text.Contains('all destinations created by this invocation were rolled back and global sources were preserved');$pass=($r.ExitCode-ne0-and$hubsUnchanged-and$lifecycleStateUnchanged-and$sourcesOk-and$targetsAbsent-and$rollbackReported);$detail=if($pass){'phase-4 injected second-publication fault executed real rollback: first published destination removed, both valid global sources preserved by exact hash, no stage residue, lifecycle unchanged'}else{'phase-4 rollback proof failed: '+$r.Text}}
                'registry_init_publication_fault_preserves_verified_destination_on_source_loss' {$source0Missing=(-not(Test-Path -LiteralPath ([string]$script:ScenarioPendingGlobalSources[0])));$source1Ok=Test-FileSha ([string]$script:ScenarioPendingGlobalSources[1]) ([string]$script:ScenarioPendingGlobalHashes[1]);$target0Ok=Test-FileSha ([string]$script:ScenarioPendingGlobalTargets[0]) ([string]$script:ScenarioPendingGlobalHashes[0]);$target1Absent=(-not(Test-Path -LiteralPath ([string]$script:ScenarioPendingGlobalTargets[1])));$stageClean=$true;foreach($target in @($script:ScenarioPendingGlobalTargets)){$parent=Split-Path -Parent ([string]$target);if(Test-Path -LiteralPath $parent -PathType Container){$stages=@(Get-ChildItem -LiteralPath $parent -File -Force -ErrorAction SilentlyContinue|Where-Object{$_.Name-like'*.stage.*'});$stageClean=$stageClean-and$stages.Count-eq0}};$rollbackReported=$r.Text.Contains('rollback was incomplete')-and$r.Text.Contains('verified destination retained');$pass=($r.ExitCode-ne0-and$hubsUnchanged-and$controlStateUnchanged-and$compatBaselineAfter-ceq$compatBaselineBefore-and$source0Missing-and$source1Ok-and$target0Ok-and$target1Absent-and$stageClean-and$rollbackReported);$detail=if($pass){'phase-4 source-loss fault retained the first verified destination as the only proven-good copy, preserved the second source, published no second destination, left no stage residue, and reported partial durable handoff fail-closed'}else{'phase-4 source-loss preservation proof failed: '+$r.Text}}
                'fail_closed' {$pass=($r.ExitCode-ne0-and$hubsUnchanged-and$lifecycleStateUnchanged);$detail=if($pass){'Hub/context-bound action failed closed without Hub lifecycle mutation'}else{'expected fail-closed lifecycle outcome not observed: '+$r.Text}}
                default {Fail('Unsupported expected mode: '+[string]$spec.Mode)}
            }
        }catch{$classification='harness_or_fixture_error';$detail=$_.Exception.Message;$pass=$false}
        finally{$env:KEELARYN_ENTRY_ACTION_SENTINEL=$oldSentinel;$env:KEELARYN_ENTRY_ROLLBACK_FAULT=$oldFault}
        [void]$results.Add([ordered]@{id=[string]$spec.Id;requirement=[string]$spec.Requirement;state=[string]$spec.State;action=[string]$spec.Action;expected_mode=[string]$spec.Mode;proof_mode=if([bool]$spec.Supplemental){[string]$spec.ProofMode}else{[string]$actionById[[string]$spec.Action].proof_mode};supplemental=[bool]$spec.Supplemental;pass=$pass;classification=if($pass){'pass'}else{$classification};exit_code=$exitCode;detail=$detail});Write-Host ('  '+$(if($pass){'PASS'}else{'FAIL'})+' '+$spec.Id+' '+$spec.State+' x '+$spec.Action+' :: '+$detail) -ForegroundColor $(if($pass){'Green'}else{'Red'})
    }
}catch{$harnessError=$_.Exception.Message;Write-Host ('ENTRY MATRIX HARNESS ERROR: '+$harnessError) -ForegroundColor Red}

$failed=@($results|Where-Object{-not[bool]$_.pass});$syntheticSuccessorVersion=if($null-ne$successor){[string]$successor.Version}else{''}
$report=[ordered]@{schema='keelaryn.manager-entry-reachability-result.v2';manager_version=$version;model_sha256=$modelSha;supplemental_model_sha256=$supplementSha;canonical_scenario_count=102;supplemental_scenario_count=2;scenario_count=@($scenarioSpecs).Count;executed_count=@($results).Count;pass=($null-eq$harnessError-and$failed.Count-eq0);harness_error=$harnessError;failures=@($failed|ForEach-Object{[string]$_.id});scenarios=@($results);production_hub_used=$false;scenario_reset='direct_external_full_manager_and_hub_snapshot_restore';transactional_proof_revision=6;synthetic_successor_version=$syntheticSuccessorVersion;completed_utc=[DateTime]::UtcNow.ToString('o')}
try{Write-Json $OutputPath $report;Write-Host ('Evidence: '+$OutputPath)}catch{Write-Host ('Could not write entry-reachability evidence: '+$_.Exception.Message) -ForegroundColor Red;if(-not$harnessError){$harnessError=$_.Exception.Message}}
try{if(Test-Path -LiteralPath $tempRoot){Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction Stop}}catch{Write-Warning('Disposable cleanup failed: '+$_.Exception.Message)}
if($harnessError-or$failed.Count-ne0){Write-Host ('MANAGER ENTRY REACHABILITY MATRIX: FAIL; failures='+$failed.Count+'; harness_error='+[bool]$harnessError) -ForegroundColor Red;exit 1}
Write-Host ('MANAGER ENTRY REACHABILITY MATRIX: PASS; scenarios='+@($results).Count+' (canonical=102 supplemental=2)') -ForegroundColor Green
exit 0
