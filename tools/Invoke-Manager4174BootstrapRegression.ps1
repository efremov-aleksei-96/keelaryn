[CmdletBinding()]
param(
    [string]$RepositoryRoot=(Join-Path $PSScriptRoot '..')
)

# Regression coverage for multi-Hub registry bootstrap commit outcome semantics.
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$runtimePath=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1'
if(-not(Test-Path -LiteralPath $runtimePath -PathType Leaf)){throw 'Manager runtime missing.'}

function Assert([bool]$Condition,[string]$Message){if(-not$Condition){throw $Message}}
function Get-FunctionText([string]$Path,[string]$Name){
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors)
    if(@($errors).Count-ne0){throw('Parser failed for '+$Path+': '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
    $rows=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$Name},$true))
    if($rows.Count-ne1){throw('Expected exactly one function '+$Name+'; actual='+$rows.Count)}
    return [string]$rows[0].Extent.Text
}

Invoke-Expression (Get-FunctionText $runtimePath 'Invoke-InitializeInstanceRegistry')

$temp=Join-Path ([IO.Path]::GetTempPath()) ('keelaryn_4174_bootstrap_regression_'+[guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($temp)
try{
    $id='55555555-5555-5555-5555-555555555555'
    $script:CanonicalLayoutActive=$true
    $script:StateLayoutActive=$true
    $script:InstanceRegistryFile=Join-Path $temp 'instances.json'
    $script:ActiveInstanceFile=Join-Path $temp 'active_instance.json'
    $script:LegacySingleInstanceCurrentZip=Join-Path $temp 'legacy-current-missing.zip'
    $script:Vault=Join-Path $temp 'hub'
    $script:RegisterInstanceName='Primary'
    [void][IO.Directory]::CreateDirectory($script:Vault)
    $script:StateRootForCase=$null
    $script:RegistryDocument=$null
    $script:WriteMode='success'
    $script:PostCommitResolveFailure=$false
    $script:RereadFailure=$false

    function Assert-InstanceBindingAvailable {}
    function Test-CanonicalBaselineConsistent {return [pscustomobject]@{State=[pscustomobject]@{InstanceId=$id}}}
    function New-RegisteredInstanceStateFromVault([string]$InstanceId,[string]$VaultPath){
        $root=Join-Path $temp ('state-'+[guid]::NewGuid().ToString('N'))
        $current=Join-Path $root 'baseline\Keelaryn__Hub_CURRENT.zip'
        [void][IO.Directory]::CreateDirectory((Split-Path -Parent $current))
        [IO.File]::WriteAllText($current,'current',(New-Object Text.UTF8Encoding($false)))
        $script:StateRootForCase=$root
        return [pscustomobject]@{Root=$root;Current=$current}
    }
    function Publish-CompatibilityShadowFromRegisteredInstance($Row,[string]$Reason){return $true}
    function Assert-RegisteredInstanceBaseline($Row){return $true}
    function Write-ManagerActiveInstance([string]$InstanceId){
        [IO.File]::WriteAllText($script:ActiveInstanceFile,$InstanceId,(New-Object Text.UTF8Encoding($false)))
    }
    function Read-ActiveInstanceEarly {
        if(-not(Test-Path -LiteralPath $script:ActiveInstanceFile -PathType Leaf)){throw 'active marker missing'}
        return [pscustomobject]@{instance_id=([IO.File]::ReadAllText($script:ActiveInstanceFile,[Text.Encoding]::UTF8)).Trim()}
    }
    function Write-ManagerInstanceRegistry($Registry){
        if($script:WriteMode-eq'precommit-fail'){throw 'simulated registry write failure before commit'}
        $script:RegistryDocument=[pscustomobject]@{schema='keelaryn.manager.instances.v1';registry_revision=[int]$Registry.registry_revision;instances=@($Registry.instances)}
        [IO.File]::WriteAllText($script:InstanceRegistryFile,'committed',(New-Object Text.UTF8Encoding($false)))
        if($script:WriteMode-eq'postcommit-fail'){throw 'simulated registry writer failure after durable commit'}
    }
    function Get-ManagerInstanceRegistry {
        if($script:RereadFailure){throw 'simulated registry reread failure'}
        if(-not(Test-Path -LiteralPath $script:InstanceRegistryFile -PathType Leaf)){throw 'Multi-Hub registry is not initialized.'}
        return $script:RegistryDocument
    }
    function Get-KeelarynNormalizedPathKey([string]$Path){return ([IO.Path]::GetFullPath($Path)).TrimEnd('\').ToLowerInvariant()}
    function Resolve-RegisteredInstanceContextEarly {
        if($script:PostCommitResolveFailure){throw 'simulated post-commit resolve failure'}
        return $true
    }

    function Reset-Case([string]$WriteMode,[bool]$ResolveFailure=$false,[bool]$RereadFailure=$false){
        Remove-Item -LiteralPath $script:InstanceRegistryFile -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $script:ActiveInstanceFile -Force -ErrorAction SilentlyContinue
        if($script:StateRootForCase-and(Test-Path -LiteralPath $script:StateRootForCase)){Remove-Item -LiteralPath $script:StateRootForCase -Recurse -Force}
        $script:StateRootForCase=$null
        $script:RegistryDocument=$null
        $script:WriteMode=$WriteMode
        $script:PostCommitResolveFailure=$ResolveFailure
        $script:RereadFailure=$RereadFailure
    }

    Reset-Case 'success' $true $false
    $message=$null
    try{$null=Invoke-InitializeInstanceRegistry;throw 'Expected post-commit resolve failure.'}catch{$message=$_.Exception.Message}
    Assert ($message.Contains('registry durable commit succeeded')) ('Post-commit bootstrap diagnostic missing: '+$message)
    Assert (Test-Path -LiteralPath $script:InstanceRegistryFile -PathType Leaf) 'Post-commit failure deleted durable instances.json.'
    Assert (Test-Path -LiteralPath $script:ActiveInstanceFile -PathType Leaf) 'Post-commit failure deleted active_instance.json.'
    Assert ($script:StateRootForCase-and(Test-Path -LiteralPath $script:StateRootForCase -PathType Container)) 'Post-commit failure deleted per-instance state.'
    Write-Host '  PASS bootstrap preserves durable registry commit on post-commit verification failure'

    Reset-Case 'postcommit-fail' $false $true
    $message=$null
    try{$null=Invoke-InitializeInstanceRegistry;throw 'Expected ambiguous post-write bootstrap failure.'}catch{$message=$_.Exception.Message}
    Assert ($message.Contains('commit status is ambiguous')) ('Ambiguous bootstrap diagnostic missing: '+$message)
    Assert (Test-Path -LiteralPath $script:InstanceRegistryFile -PathType Leaf) 'Ambiguous bootstrap failure deleted possible durable instances.json.'
    Assert (Test-Path -LiteralPath $script:ActiveInstanceFile -PathType Leaf) 'Ambiguous bootstrap failure deleted active_instance.json.'
    Assert ($script:StateRootForCase-and(Test-Path -LiteralPath $script:StateRootForCase -PathType Container)) 'Ambiguous bootstrap failure deleted per-instance state.'
    Write-Host '  PASS bootstrap preserves state when registry commit verification is ambiguous'

    Reset-Case 'precommit-fail' $false $false
    $message=$null
    try{$null=Invoke-InitializeInstanceRegistry;throw 'Expected pre-commit bootstrap failure.'}catch{$message=$_.Exception.Message}
    Assert ($message.Contains('failed before registry commit')) ('Pre-commit bootstrap diagnostic missing: '+$message)
    Assert (-not(Test-Path -LiteralPath $script:InstanceRegistryFile)) 'Pre-commit failure unexpectedly left instances.json.'
    Assert (-not(Test-Path -LiteralPath $script:ActiveInstanceFile)) 'Pre-commit failure did not roll back its active marker.'
    Assert (-not$script:StateRootForCase-or-not(Test-Path -LiteralPath $script:StateRootForCase)) 'Pre-commit failure did not roll back owned per-instance state.'
    Write-Host '  PASS bootstrap safely rolls back definitely uncommitted state'

    $text=Get-FunctionText $runtimePath 'Invoke-InitializeInstanceRegistry'
    Assert ($text.Contains('$registryWriteStarted=$true')) 'Bootstrap does not track registry write start.'
    Assert ($text.Contains('Multi-Hub registry durable commit succeeded')) 'Bootstrap lacks durable post-commit diagnostic.'
    Assert ($text.Contains('registry commit status is ambiguous')) 'Bootstrap lacks ambiguous commit diagnostic.'
    Write-Host 'MANAGER 4.17.4 BOOTSTRAP REGRESSION: PASS' -ForegroundColor Green
}finally{
    if(Test-Path -LiteralPath $temp){Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue}
}
