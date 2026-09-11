[CmdletBinding()]
param(
    [string]$RepositoryRoot=(Join-Path $PSScriptRoot '..')
)

# Permanent regression coverage for the PR #48 review defects plus the pre-freeze ambiguous-commit edge case.
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$runtimePath=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1'
$menuPath=Join-Path $RepositoryRoot 'manager\product\tools\KeelarynMenu.ps1'
if(-not(Test-Path -LiteralPath $runtimePath -PathType Leaf)){throw 'Manager runtime missing.'}
if(-not(Test-Path -LiteralPath $menuPath -PathType Leaf)){throw 'Manager frontend missing.'}

function Get-FunctionText([string]$Path,[string]$Name){
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors)
    if(@($errors).Count-ne0){throw('Parser failed for '+$Path+': '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
    $rows=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$Name},$true))
    if($rows.Count-ne1){throw('Expected exactly one function '+$Name+' in '+$Path+'; actual='+$rows.Count)}
    return [string]$rows[0].Extent.Text
}
function Assert([bool]$Condition,[string]$Message){if(-not$Condition){throw $Message}}

# Import only the functions under test; all dependencies are controlled stubs.
Invoke-Expression (Get-FunctionText $runtimePath 'Invoke-RegisterExistingInstance')
Invoke-Expression (Get-FunctionText $runtimePath 'Invoke-GenesisRegisteredInstance')
Invoke-Expression (Get-FunctionText $menuPath 'ConvertTo-CanonicalFrontendInstanceId')
Invoke-Expression (Get-FunctionText $menuPath 'Get-FrontendInstanceContext')

$temp=Join-Path ([IO.Path]::GetTempPath()) ('keelaryn_4172_review_regression_'+[guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($temp)
try{
    $alphaId='11111111-1111-1111-1111-111111111111'
    $betaId='22222222-2222-2222-2222-222222222222'
    $script:InstanceRegistryFile=Join-Path $temp 'instances.json'
    [IO.File]::WriteAllText($script:InstanceRegistryFile,'{}',(New-Object Text.UTF8Encoding($false)))
    $TestHubCandidate={param($Path) $true}
    $script:RegressionRegistry=$null
    $script:RegressionStateRoot=$null
    $script:ThrowInsideWrite=$false
    $script:ThrowRegistryReadAfterWrite=$false
    $script:RegistryWriteAttempted=$false
    $script:RegressionMetadataMode='registration'
    $script:RegressionActive=[pscustomobject]@{instance_id=$alphaId}

    function Get-ManagerInstanceRegistry {
        if($script:ThrowRegistryReadAfterWrite -and $script:RegistryWriteAttempted){throw 'simulated registry reread failure after write attempt'}
        return $script:RegressionRegistry
    }
    function Assert-RegisteredVaultStructuralSafetyEarly([string]$Path){return [IO.Path]::GetFullPath($Path)}
    function Read-VaultMetadataAt([string]$Path){
        if($script:RegressionMetadataMode-eq'registration'){return [pscustomobject]@{InstanceId=$betaId}}
        throw 'Read-VaultMetadataAt must not run after registered Genesis cancellation.'
    }
    function Read-VaultArtifactManifestAt([string]$Path){
        if($script:RegressionMetadataMode-eq'registration'){return [pscustomobject]@{InstanceId=$betaId}}
        throw 'Read-VaultArtifactManifestAt must not run after registered Genesis cancellation.'
    }
    function Get-KeelarynNormalizedPathKey([string]$Path){return ([IO.Path]::GetFullPath($Path)).TrimEnd('\').ToLowerInvariant()}
    function Test-KeelarynPathOverlap([string]$A,[string]$B){return $false}
    function New-RegisteredInstanceStateFromVault([string]$Id,[string]$Path){
        [void][IO.Directory]::CreateDirectory($script:RegressionStateRoot)
        [IO.File]::WriteAllText((Join-Path $script:RegressionStateRoot 'baseline.marker'),'preserve')
        return [pscustomobject]@{Root=$script:RegressionStateRoot}
    }
    function Write-ManagerInstanceRegistry($Registry){
        $script:RegressionRegistry=[pscustomobject]@{
            schema='keelaryn.manager.instances.v1'
            registry_revision=[int]$Registry.registry_revision
            instances=@($Registry.instances)
        }
        $script:RegistryWriteAttempted=$true
        if($script:ThrowInsideWrite){throw 'simulated post-publication registry verification failure'}
    }
    function Invoke-SwitchRegisteredInstance([string]$Id){throw 'simulated activation failure after durable registry commit'}
    function Assert-InvocationInstanceUnchanged {}
    function Read-ActiveInstanceEarly {return $script:RegressionActive}
    function Assert-NewRegisteredHubTargetPathSafe([string]$Path){return [IO.Path]::GetFullPath($Path)}
    function Invoke-Genesis([string]$ConfigPath,[bool]$Confirmed){return 0}

    function Reset-RegistrationFixture([string]$CaseName,[bool]$ThrowInWrite,[bool]$ThrowOnVerifyRead=$false){
        $alphaPath=Join-Path $temp ('alpha-'+$CaseName)
        $betaPath=Join-Path $temp ('beta-'+$CaseName)
        $script:RegressionRegistry=[pscustomobject]@{
            schema='keelaryn.manager.instances.v1';registry_revision=1;instances=@(
                [pscustomobject]@{instance_id=$alphaId;name='Alpha';vault_path=$alphaPath;registered_utc='x'}
            )
        }
        $script:RegressionStateRoot=Join-Path $temp ('state-'+$CaseName)
        $script:ThrowInsideWrite=$ThrowInWrite
        $script:ThrowRegistryReadAfterWrite=$ThrowOnVerifyRead
        $script:RegistryWriteAttempted=$false
        $script:RegressionMetadataMode='registration'
        return $betaPath
    }

    foreach($case in @(
        [pscustomobject]@{Name='switch-failure';ThrowInWrite=$false},
        [pscustomobject]@{Name='write-postcommit-failure';ThrowInWrite=$true}
    )){
        $betaPath=Reset-RegistrationFixture $case.Name $case.ThrowInWrite
        $message=$null
        try{$null=Invoke-RegisterExistingInstance $betaPath 'Beta' $true;throw('Expected '+$case.Name+' to throw.')}catch{$message=$_.Exception.Message}
        Assert ($message.Contains('Hub registration durable commit succeeded')) ($case.Name+': durable-commit diagnostic missing: '+$message)
        Assert (Test-Path -LiteralPath $script:RegressionStateRoot -PathType Container) ($case.Name+': committed per-instance state was deleted.')
        Assert (Test-Path -LiteralPath (Join-Path $script:RegressionStateRoot 'baseline.marker') -PathType Leaf) ($case.Name+': committed state marker was deleted.')
        $betaRows=@($script:RegressionRegistry.instances|Where-Object{[string]$_.instance_id-eq$betaId})
        Assert ($betaRows.Count-eq1) ($case.Name+': durable registry row was not preserved.')
    }
    Write-Host '  PASS committed registration state survives post-commit failures'

    $betaPath=Reset-RegistrationFixture 'ambiguous-postcommit-reread' $true $true
    $message=$null
    try{$null=Invoke-RegisterExistingInstance $betaPath 'Beta' $true;throw 'Expected ambiguous post-commit reread case to throw.'}catch{$message=$_.Exception.Message}
    Assert ($message.Contains('registry commit status is ambiguous')) ('ambiguous-postcommit-reread: ambiguity diagnostic missing: '+$message)
    Assert ($message.Contains('registered state was preserved')) ('ambiguous-postcommit-reread: preservation diagnostic missing: '+$message)
    Assert (Test-Path -LiteralPath $script:RegressionStateRoot -PathType Container) 'ambiguous-postcommit-reread: state was deleted while commit status was unknown.'
    Assert (Test-Path -LiteralPath (Join-Path $script:RegressionStateRoot 'baseline.marker') -PathType Leaf) 'ambiguous-postcommit-reread: state marker was deleted while commit status was unknown.'
    $betaRows=@($script:RegressionRegistry.instances|Where-Object{[string]$_.instance_id-eq$betaId})
    Assert ($betaRows.Count-eq1) 'ambiguous-postcommit-reread: simulated durable registry row was lost.'
    Write-Host '  PASS ambiguous registry commit verification preserves per-instance state'

    $script:ThrowRegistryReadAfterWrite=$false
    $script:RegistryWriteAttempted=$false
    $script:InstanceRegistryActive=$true
    $script:InstancesStateRoot=Join-Path $temp 'registered-state'
    $script:RegressionRegistry=[pscustomobject]@{
        schema='keelaryn.manager.instances.v1';registry_revision=1;instances=@(
            [pscustomobject]@{instance_id=$alphaId;name='Alpha';vault_path=(Join-Path $temp 'alpha-genesis');registered_utc='x'}
        )
    }
    $script:RegressionActive=[pscustomobject]@{instance_id=$alphaId}
    $script:RegressionMetadataMode='cancel'
    $WorkRoot=Join-Path $temp 'work'
    [void][IO.Directory]::CreateDirectory($WorkRoot)
    $target=Join-Path $temp 'beta-cancelled'
    $rc=Invoke-GenesisRegisteredInstance $target 'Beta' '' $false
    Assert ($rc-eq0) 'Interactive registered Genesis cancellation did not return success/cancel code 0.'
    Assert (-not(Test-Path -LiteralPath $target)) 'Interactive registered Genesis cancellation published a Hub unexpectedly.'
    Assert (@($script:RegressionRegistry.instances).Count-eq1) 'Interactive registered Genesis cancellation mutated the registry.'

    $nonInteractiveMessage=$null
    try{$null=Invoke-GenesisRegisteredInstance (Join-Path $temp 'beta-noninteractive') 'Beta' (Join-Path $temp 'config.json') $true;throw 'Expected silent non-interactive Genesis success to be rejected.'}catch{$nonInteractiveMessage=$_.Exception.Message}
    Assert ($nonInteractiveMessage.Contains('Nested non-interactive Genesis returned success without staged Hub/CURRENT.')) ('Non-interactive missing-output classification mismatch: '+$nonInteractiveMessage)
    Assert (@($script:RegressionRegistry.instances).Count-eq1) 'Rejected non-interactive Genesis mutated the registry.'
    Write-Host '  PASS registered Genesis cancellation/missing-output classification'

    $StateLayoutActive=$true
    $StateRoot=Join-Path $temp 'frontend-state'
    $HubRoot=Join-Path $temp 'frontend-hub'
    $Inbox=Join-Path $StateRoot 'inbox'
    $ExchangeParent=Join-Path $temp 'exchange'
    [void][IO.Directory]::CreateDirectory($StateRoot)
    $registryPath=Join-Path $StateRoot 'instances.json'
    $activePath=Join-Path $StateRoot 'active_instance.json'
    $utf8=New-Object Text.UTF8Encoding($false)
    $bad='..\..\outside'
    $badRegistry=[ordered]@{schema='keelaryn.manager.instances.v1';registry_revision=1;instances=@([ordered]@{instance_id=$bad;name='Bad';vault_path=(Join-Path $temp 'bad-hub')})}
    $badActive=[ordered]@{schema='keelaryn.manager.active-instance.v1';instance_id=$bad}
    [IO.File]::WriteAllText($registryPath,($badRegistry|ConvertTo-Json -Depth 8),$utf8)
    [IO.File]::WriteAllText($activePath,($badActive|ConvertTo-Json -Depth 8),$utf8)
    $badContext=Get-FrontendInstanceContext
    Assert ($badContext.RegistryActive) 'Malformed registry should remain classified as registry-active error state.'
    Assert ([string]::IsNullOrWhiteSpace([string]$badContext.InstanceId)) 'Frontend accepted malformed instance_id.'
    Assert ([IO.Path]::GetFullPath([string]$badContext.ExchangeRoot)-ceq[IO.Path]::GetFullPath((Join-Path $ExchangeParent 'chatgpt'))) 'Malformed instance_id escaped into frontend exchange path.'
    Assert ([IO.Path]::GetFullPath([string]$badContext.CurrentZip)-ceq[IO.Path]::GetFullPath((Join-Path $StateRoot 'baseline\Keelaryn__Hub_CURRENT.zip'))) 'Malformed instance_id escaped into frontend state path.'

    $goodRegistry=[ordered]@{schema='keelaryn.manager.instances.v1';registry_revision=2;instances=@([ordered]@{instance_id=$betaId;name='Beta';vault_path=(Join-Path $temp 'good-hub')})}
    $goodActive=[ordered]@{schema='keelaryn.manager.active-instance.v1';instance_id=$betaId}
    [IO.File]::WriteAllText($registryPath,($goodRegistry|ConvertTo-Json -Depth 8),$utf8)
    [IO.File]::WriteAllText($activePath,($goodActive|ConvertTo-Json -Depth 8),$utf8)
    $goodContext=Get-FrontendInstanceContext
    Assert ([string]$goodContext.InstanceId-ceq$betaId) 'Valid frontend instance_id did not resolve.'
    Assert ([IO.Path]::GetFullPath([string]$goodContext.CurrentZip).Contains(('instances\'+$betaId+'\baseline\Keelaryn__Hub_CURRENT.zip'))) 'Valid frontend CURRENT path is not instance-scoped.'
    Assert ([IO.Path]::GetFullPath([string]$goodContext.ExchangeRoot).Contains(('instances\'+$betaId+'\chatgpt'))) 'Valid frontend exchange path is not instance-scoped.'
    Write-Host '  PASS frontend rejects malformed instance_id before path construction'

    Write-Host 'MANAGER 4.17.2 REVIEW REGRESSION: PASS' -ForegroundColor Green
}finally{
    if(Test-Path -LiteralPath $temp){Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue}
}
