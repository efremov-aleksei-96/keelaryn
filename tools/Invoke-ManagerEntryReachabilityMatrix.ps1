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
function Write-Utf8([string]$Path,[string]$Text){
    $parent=Split-Path -Parent $Path
    if($parent-and-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
    [IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)
}
function Write-Json([string]$Path,$Object){Write-Utf8 $Path ((($Object|ConvertTo-Json -Depth 30).Replace("`r`n","`n"))+"`n")}
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
function Invoke-Runtime([string]$Runtime,[string[]]$Arguments){
    if($null-eq$Arguments){$Arguments=@()}
    $exe=Join-Path $PSHOME 'powershell.exe';$old=$ErrorActionPreference
    try{
        $ErrorActionPreference='Continue'
        $output=@(& $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Runtime @Arguments 2>&1|ForEach-Object{[string]$_})
        $code=[int]$LASTEXITCODE
    }finally{$ErrorActionPreference=$old}
    return [pscustomobject]@{ExitCode=$code;Output=@($output);Text=[string]::Join("`n",@($output))}
}
function Invoke-Required([string]$Runtime,[string[]]$Arguments,[string]$Purpose){
    $r=Invoke-Runtime $Runtime $Arguments
    foreach($line in @($r.Output)){Write-Host $line}
    if($r.ExitCode-ne0){Fail($Purpose+' failed; exit='+$r.ExitCode+'; output='+$r.Text)}
    return $r
}
function Get-TreeDigest([string]$Root){
    if(-not(Test-Path -LiteralPath $Root -PathType Container)){return 'missing'}
    $rows=New-Object System.Collections.ArrayList
    foreach($f in @(Get-ChildItem -LiteralPath $Root -File -Recurse -Force|Sort-Object FullName)){
        $rel=$f.FullName.Substring($Root.Length).TrimStart('\').Replace('\','/')
        $h=(Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        [void]$rows.Add($rel+'='+$h)
    }
    $text=[string]::Join("`n",@($rows))
    $sha=[Security.Cryptography.SHA256]::Create()
    try{return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($text))).Replace('-','').ToLowerInvariant())}finally{$sha.Dispose()}
}
function Read-Registry([string]$ManagerRoot){return Get-Content -LiteralPath (Join-Path $ManagerRoot 'state\instances.json') -Raw -Encoding UTF8|ConvertFrom-Json}
function Read-Active([string]$ManagerRoot){return Get-Content -LiteralPath (Join-Path $ManagerRoot 'state\active_instance.json') -Raw -Encoding UTF8|ConvertFrom-Json}
function Add-Scenario($List,[string]$Id,[string]$State,[string]$Action,[bool]$Pass,[int]$ExitCode,[string]$Detail){
    [void]$List.Add([ordered]@{id=$Id;state=$State;action=$Action;pass=$Pass;exit_code=$ExitCode;detail=$Detail})
    $mark=if($Pass){'PASS'}else{'FAIL'};Write-Host ('  '+$mark+' '+$Id+' '+$State+' x '+$Action+' :: '+$Detail) -ForegroundColor $(if($Pass){'Green'}else{'Red'})
}

$modelPath=Join-Path $RepositoryRoot 'tests\knowledge\entry-reachability.json'
if(-not(Test-Path -LiteralPath $modelPath -PathType Leaf)){Fail 'Entry-reachability model is missing.'}
$model=Get-Content -LiteralPath $modelPath -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$model.schema-cne'keelaryn.manager-entry-reachability.v1'){Fail 'Unsupported entry-reachability model schema.'}

$sourceManager=Join-Path $RepositoryRoot 'manager'
$tempRoot=Join-Path ([IO.Path]::GetTempPath()) ('keelaryn-entry-reachability-'+[guid]::NewGuid().ToString('N'))
$keelarynRoot=Join-Path $tempRoot 'keelaryn';$managerRoot=Join-Path $keelarynRoot 'manager'
$configA=Join-Path $tempRoot 'alpha.json';$configB=Join-Path $tempRoot 'beta.json'
$results=New-Object System.Collections.ArrayList
try{
    New-Item -ItemType Directory -Force -Path $keelarynRoot|Out-Null
    $version=Copy-ManagedManager $sourceManager $managerRoot
    $runtime=Join-Path $managerRoot 'product\runtime\Keelaryn__Manager.ps1'
    foreach($pair in @(@($configA,'Alpha'),@($configB,'Beta'))){
        $cfg=[ordered]@{schema='keelaryn.genesis-input.v1';language='en';purpose='mixed';timezone='UTC';areas=@('Qualification');projects=@('Entry reachability '+[string]$pair[1])}
        Write-Json ([string]$pair[0]) $cfg
    }

    Write-Host ('=== MANAGER ENTRY REACHABILITY MATRIX / '+$version+' ===')
    $null=Invoke-Required $runtime @('-Genesis','-GenesisConfigPath',$configA,'-GenesisConfirmed') 'Alpha Genesis'
    $null=Invoke-Required $runtime @('-InitializeInstanceRegistry','-RegisterInstanceName','Alpha') 'Registry activation'
    $betaPath=Join-Path $keelarynRoot 'hubs\beta'
    $null=Invoke-Required $runtime @('-GenesisInstancePath',$betaPath,'-GenesisInstanceName','Beta','-GenesisConfigPath',$configB,'-GenesisConfirmed') 'Beta registered Genesis'

    $registry=Read-Registry $managerRoot
    if(@($registry.instances).Count-ne2){Fail('Expected two registered Hubs; actual='+@($registry.instances).Count)}
    $alpha=@($registry.instances|Where-Object{[string]$_.name-ceq'Alpha'});$beta=@($registry.instances|Where-Object{[string]$_.name-ceq'Beta'})
    if($alpha.Count-ne1-or$beta.Count-ne1){Fail 'Could not resolve Alpha/Beta registry rows.'}
    $alpha=$alpha[0];$beta=$beta[0]
    $alphaId=[string]$alpha.instance_id;$betaId=[string]$beta.instance_id
    $alphaPath=[string]$alpha.vault_path;$betaPath=[string]$beta.vault_path
    $alphaCurrent=Join-Path $managerRoot ('state\instances\'+$alphaId+'\baseline\Keelaryn__Hub_CURRENT.zip')
    $legacyCurrent=Join-Path $managerRoot 'state\baseline\Keelaryn__Hub_CURRENT.zip'
    $activeFile=Join-Path $managerRoot 'state\active_instance.json'
    foreach($p in @($alphaCurrent,$legacyCurrent,$activeFile)){if(-not(Test-Path -LiteralPath $p -PathType Leaf)){Fail('Required initialized state missing: '+$p)}}
    $backupRoot=Join-Path $tempRoot 'backups';New-Item -ItemType Directory -Force -Path $backupRoot|Out-Null
    $alphaCurrentBackup=Join-Path $backupRoot 'alpha-current.zip';Copy-Item -LiteralPath $alphaCurrent -Destination $alphaCurrentBackup -Force

    function Restore-HealthyAlpha {
        if(-not(Test-Path -LiteralPath $alphaCurrent -PathType Leaf)){Copy-Item -LiteralPath $alphaCurrentBackup -Destination $alphaCurrent -Force}
        $r=Invoke-Runtime $runtime @('-SwitchInstanceId',$alphaId)
        if($r.ExitCode-ne0){Fail('Could not restore healthy Alpha active context: '+$r.Text)}
        if(-not(Test-Path -LiteralPath $legacyCurrent -PathType Leaf)){Fail 'Healthy Alpha switch did not republish compatibility CURRENT.'}
    }
    function Break-AlphaCurrentMissing {
        Restore-HealthyAlpha
        Remove-Item -LiteralPath $alphaCurrent -Force
        Remove-Item -LiteralPath $legacyCurrent -Force
    }
    function Break-AlphaCurrentCorrupt {
        Restore-HealthyAlpha
        Write-Utf8 $alphaCurrent 'not-a-zip'
        Write-Utf8 $legacyCurrent 'not-a-zip'
    }
    function Restore-HealthyAlphaAndActiveMetadata {
        if(Test-Path -LiteralPath $alphaCurrent){Remove-Item -LiteralPath $alphaCurrent -Force}
        Copy-Item -LiteralPath $alphaCurrentBackup -Destination $alphaCurrent -Force
        $r=Invoke-Runtime $runtime @('-SwitchInstanceId',$alphaId)
        if($r.ExitCode-ne0){Fail('Could not restore Alpha before active-metadata scenario: '+$r.Text)}
    }

    # Missing CURRENT: diagnostic/recovery/global actions must be reachable from process entry.
    Break-AlphaCurrentMissing
    $r=Invoke-Runtime $runtime @('-ListInstances')
    Add-Scenario $results 'ER-001' 'REGISTRY_ACTIVE_CURRENT_MISSING' 'ListInstances' ($r.ExitCode-eq0-and$r.Text.Contains('Registered Hubs:')) $r.ExitCode $(if($r.ExitCode-eq0){'process entry reached registry listing'}else{'blocked before/inside listing: '+$r.Text})

    Break-AlphaCurrentMissing
    $r=Invoke-Runtime $runtime @('-SwitchInstanceId',$betaId)
    $activeOk=$false;if($r.ExitCode-eq0){try{$activeOk=([string](Read-Active $managerRoot).instance_id-ceq$betaId)}catch{}}
    Add-Scenario $results 'ER-002' 'REGISTRY_ACTIVE_CURRENT_MISSING' 'SwitchInstance' ($r.ExitCode-eq0-and$activeOk) $r.ExitCode $(if($activeOk){'healthy requested target became active'}else{'target-driven switch was unreachable/failed: '+$r.Text})

    Break-AlphaCurrentMissing
    $r=Invoke-Runtime $runtime @('-BindInstancePath',$betaPath,'-RegisterInstanceName','Beta')
    $activeOk=$false;if($r.ExitCode-eq0){try{$activeOk=([string](Read-Active $managerRoot).instance_id-ceq$betaId)}catch{}}
    Add-Scenario $results 'ER-003' 'REGISTRY_ACTIVE_CURRENT_MISSING' 'BindInstance' ($r.ExitCode-eq0-and$activeOk) $r.ExitCode $(if($activeOk){'healthy requested target was bound/activated'}else{'target-driven bind was unreachable/failed: '+$r.Text})

    Break-AlphaCurrentMissing
    $alphaDigest=Get-TreeDigest $alphaPath;$betaDigest=Get-TreeDigest $betaPath
    $r=Invoke-Runtime $runtime @('-UpdateManager')
    $unchanged=((Get-TreeDigest $alphaPath)-ceq$alphaDigest-and(Get-TreeDigest $betaPath)-ceq$betaDigest)
    Add-Scenario $results 'ER-004' 'REGISTRY_ACTIVE_CURRENT_MISSING' 'UpdateManager' ($r.ExitCode-eq0-and$unchanged) $r.ExitCode $(if($r.ExitCode-eq0-and$unchanged){'Manager-global update path remained independent of Hub CURRENT'}else{'global action blocked or Hub bytes changed: '+$r.Text})

    Break-AlphaCurrentMissing
    $r=Invoke-Runtime $runtime @('-BuildDistribution')
    Add-Scenario $results 'ER-005' 'REGISTRY_ACTIVE_CURRENT_MISSING' 'BuildDistribution' ($r.ExitCode-eq0) $r.ExitCode $(if($r.ExitCode-eq0){'Manager-global build reached from degraded active context'}else{'global build was blocked: '+$r.Text})

    Break-AlphaCurrentMissing
    $alphaDigest=Get-TreeDigest $alphaPath;$betaDigest=Get-TreeDigest $betaPath
    $r=Invoke-Runtime $runtime @('-RepairCurrentTransport')
    $unchanged=((Get-TreeDigest $alphaPath)-ceq$alphaDigest-and(Get-TreeDigest $betaPath)-ceq$betaDigest)
    Add-Scenario $results 'ER-006' 'REGISTRY_ACTIVE_CURRENT_MISSING' 'RepairCurrent' ($r.ExitCode-ne0-and$unchanged) $r.ExitCode $(if($r.ExitCode-ne0-and$unchanged){'missing CURRENT failed closed without Hub mutation'}else{'unexpected success or Hub mutation: '+$r.Text})

    Break-AlphaCurrentMissing
    $alphaDigest=Get-TreeDigest $alphaPath;$betaDigest=Get-TreeDigest $betaPath
    $r=Invoke-Runtime $runtime @('-UpdateHub')
    $unchanged=((Get-TreeDigest $alphaPath)-ceq$alphaDigest-and(Get-TreeDigest $betaPath)-ceq$betaDigest)
    Add-Scenario $results 'ER-007' 'REGISTRY_ACTIVE_CURRENT_MISSING' 'UpdateHub' ($r.ExitCode-ne0-and$unchanged) $r.ExitCode $(if($r.ExitCode-ne0-and$unchanged){'Hub-bound action failed closed without Hub mutation'}else{'unexpected success or Hub mutation: '+$r.Text})

    Break-AlphaCurrentMissing
    $alphaDigest=Get-TreeDigest $alphaPath;$betaDigest=Get-TreeDigest $betaPath
    $r=Invoke-Runtime $runtime @('-BuildCandidateTransport')
    $unchanged=((Get-TreeDigest $alphaPath)-ceq$alphaDigest-and(Get-TreeDigest $betaPath)-ceq$betaDigest)
    Add-Scenario $results 'ER-008' 'REGISTRY_ACTIVE_CURRENT_MISSING' 'BuildCandidateTransport' ($r.ExitCode-ne0-and$unchanged) $r.ExitCode $(if($r.ExitCode-ne0-and$unchanged){'instance-bound transport build failed closed'}else{'unexpected success or Hub mutation: '+$r.Text})

    # Invalid active metadata: registry diagnostics and target-driven switch remain reachable.
    Restore-HealthyAlphaAndActiveMetadata
    Write-Utf8 $activeFile '{ not-json'
    $r=Invoke-Runtime $runtime @('-ListInstances')
    Add-Scenario $results 'ER-009' 'REGISTRY_ACTIVE_METADATA_INVALID' 'ListInstances' ($r.ExitCode-eq0-and$r.Text.Contains('Registered Hubs:')) $r.ExitCode $(if($r.ExitCode-eq0){'registry remained listable'}else{'listing blocked: '+$r.Text})

    Restore-HealthyAlphaAndActiveMetadata
    Write-Utf8 $activeFile '{ not-json'
    $r=Invoke-Runtime $runtime @('-SwitchInstanceId',$betaId)
    $activeOk=$false;if($r.ExitCode-eq0){try{$activeOk=([string](Read-Active $managerRoot).instance_id-ceq$betaId)}catch{}}
    Add-Scenario $results 'ER-010' 'REGISTRY_ACTIVE_METADATA_INVALID' 'SwitchInstance' ($r.ExitCode-eq0-and$activeOk) $r.ExitCode $(if($activeOk){'target-driven recovery replaced invalid active metadata'}else{'switch blocked: '+$r.Text})

    # Corrupt CURRENT must exercise the same process-entry recovery contract, not only missing-file behavior.
    Break-AlphaCurrentCorrupt
    $r=Invoke-Runtime $runtime @('-ListInstances')
    Add-Scenario $results 'ER-011' 'REGISTRY_ACTIVE_CURRENT_CORRUPT' 'ListInstances' ($r.ExitCode-eq0-and$r.Text.Contains('Registered Hubs:')) $r.ExitCode $(if($r.ExitCode-eq0){'listing bypassed corrupt old CURRENT'}else{'listing blocked: '+$r.Text})

    Break-AlphaCurrentCorrupt
    $r=Invoke-Runtime $runtime @('-SwitchInstanceId',$betaId)
    $activeOk=$false;if($r.ExitCode-eq0){try{$activeOk=([string](Read-Active $managerRoot).instance_id-ceq$betaId)}catch{}}
    Add-Scenario $results 'ER-012' 'REGISTRY_ACTIVE_CURRENT_CORRUPT' 'SwitchInstance' ($r.ExitCode-eq0-and$activeOk) $r.ExitCode $(if($activeOk){'target-driven switch bypassed corrupt old CURRENT'}else{'switch blocked: '+$r.Text})

    $failed=@($results|Where-Object{-not[bool]$_.pass})
    $report=[ordered]@{
        schema='keelaryn.manager-entry-reachability-result.v1';manager_version=$version;classification='development_integration_regression';scenarios=@($results);pass=($failed.Count-eq0);failures=@($failed|ForEach-Object{[string]$_.id});production_hub_used=$false;completed_utc=[DateTime]::UtcNow.ToString('o')
    }
    if([string]::IsNullOrWhiteSpace($OutputPath)){$OutputPath=Join-Path $tempRoot 'ENTRY_REACHABILITY_RESULT.json'}
    Write-Json $OutputPath $report
    Write-Host ('Evidence: '+$OutputPath)
    if($failed.Count-ne0){Write-Host ('MANAGER ENTRY REACHABILITY MATRIX: FAIL ('+$failed.Count+' scenario(s))') -ForegroundColor Red;exit 1}
    Write-Host 'MANAGER ENTRY REACHABILITY MATRIX: PASS' -ForegroundColor Green
    exit 0
}
finally{
    if(Test-Path -LiteralPath $tempRoot){Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue}
}
