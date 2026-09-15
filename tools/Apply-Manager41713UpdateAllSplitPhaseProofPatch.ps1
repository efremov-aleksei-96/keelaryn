[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$runtimePath=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1'
if(-not(Test-Path -LiteralPath $runtimePath -PathType Leaf)){throw('Runtime missing: '+$runtimePath)}
$utf8=New-Object Text.UTF8Encoding($false)
$text=[IO.File]::ReadAllText($runtimePath,[Text.Encoding]::UTF8)

$anchor='$SkipHubBindingResolution = '
if([regex]::Matches($text,[regex]::Escape($anchor)).Count-ne1){throw 'Split-phase proof helper insertion anchor count mismatch.'}
$helper=@'
function Try-BindTokenBoundUpdateAllMetadataContextEarly {
    if(-not$UpdateAll-or[string]::IsNullOrWhiteSpace([string]$ExpectedInstanceId)){return $false}
    try{
        $registry=Read-InstanceRegistryEarly
        if(-not$registry){return $false}
        $active=Read-ActiveInstanceEarly
        if([string]$active.instance_id-cne[string]$ExpectedInstanceId){return $false}
        $matches=@($registry.instances|Where-Object{[string]$_.instance_id-ceq[string]$active.instance_id})
        if($matches.Count-ne1){return $false}
        $row=$matches[0]
        $path=[IO.Path]::GetFullPath([string]$row.vault_path).TrimEnd('\')
        if(Test-KeelarynPathOverlap $path $Root){return $false}
        if($CanonicalLayoutActive-and(Test-KeelarynPathOverlap $path $CanonicalTestsPath)){return $false}
        $script:InstanceRegistryActive=$true
        $script:ActiveInstanceId=[string]$row.instance_id
        $script:ActiveInstanceName=[string]$row.name
        $script:InvocationInstanceId=[string]$row.instance_id
        $script:Vault=$path
        Set-InstanceScopedOperationalPathsEarly ([string]$row.instance_id)
        return $true
    }catch{return $false}
}
'@
$text=$text.Replace($anchor,$helper+"`n"+$anchor)

$old=@'
    catch {
        $allowRegistryUnresolved=$Doctor-or$SelfTest-or$BuildDistribution-or$BuildRelease-or$BuildAIContext-or$UpdateManager-or$PrepareTests-or$InitializePresentation-or$InitializeInstanceRegistry-or$ListInstances-or$SwitchInstanceId-or$BindInstancePath-or$FinalizeFilesystemLayout
        if($allowRegistryUnresolved){
            $script:BindingResolutionError='Multi-Hub registry: '+$_.Exception.Message
            $script:InstanceRegistryActive=$false
            $script:Vault=$DefaultVault
            $script:HubInbox=$script:Inbox
        }else{throw('Invalid Keelaryn multi-Hub registry: '+$_.Exception.Message)}
    }
'@
$new=@'
    catch {
        $registryResolutionFailure=$_.Exception.Message
        $tokenBoundUpdateAllContextRecovered=Try-BindTokenBoundUpdateAllMetadataContextEarly
        $allowRegistryUnresolved=$Doctor-or$SelfTest-or$BuildDistribution-or$BuildRelease-or$BuildAIContext-or$UpdateManager-or$PrepareTests-or$InitializePresentation-or$InitializeInstanceRegistry-or$ListInstances-or$SwitchInstanceId-or$BindInstancePath-or$FinalizeFilesystemLayout
        if($tokenBoundUpdateAllContextRecovered){
            $script:BindingResolutionError='Multi-Hub registry: '+$registryResolutionFailure
        }elseif($allowRegistryUnresolved){
            $script:BindingResolutionError='Multi-Hub registry: '+$registryResolutionFailure
            $script:InstanceRegistryActive=$false
            $script:Vault=$DefaultVault
            $script:HubInbox=$script:Inbox
        }else{throw('Invalid Keelaryn multi-Hub registry: '+$registryResolutionFailure)}
    }
'@
if([regex]::Matches($text,[regex]::Escape($old)).Count-ne1){throw 'Split-phase proof catch replacement anchor count mismatch.'}
$text=$text.Replace($old,$new)

$oldShadow=@'
function Test-ActiveCompatibilityShadowReconciliationRequired {
    if(-not$script:InstanceRegistryActive){return $false}
    # Diagnostic/target-driven recovery and Manager-global operations must be reachable
    # without validating or repairing the old active Hub CURRENT they do not consume.
    if($Doctor-or$SelfTest-or$ListInstances-or$SwitchInstanceId-or$BindInstancePath-or$InitializeInstanceRegistry-or$UpdateManager-or$BuildDistribution-or$BuildRelease-or$BuildAIContext-or$PrepareTests-or$InitializePresentation-or$FinalizeFilesystemLayout){return $false}
    return $true
}
'@
$newShadow=@'
function Test-ActiveCompatibilityShadowReconciliationRequired {
    if(-not$script:InstanceRegistryActive){return $false}
    # A token-bound UpdateAll whose registry/active metadata was revalidated may run its
    # Manager-global phase even when the captured Hub itself is missing/corrupt. The
    # preserved BindingResolutionError keeps the subsequent Hub phase fail-closed.
    if($UpdateAll-and-not[string]::IsNullOrWhiteSpace([string]$ExpectedInstanceId)-and-not[string]::IsNullOrWhiteSpace([string]$script:BindingResolutionError)){return $false}
    # Diagnostic/target-driven recovery and Manager-global operations must be reachable
    # without validating or repairing the old active Hub CURRENT they do not consume.
    if($Doctor-or$SelfTest-or$ListInstances-or$SwitchInstanceId-or$BindInstancePath-or$InitializeInstanceRegistry-or$UpdateManager-or$BuildDistribution-or$BuildRelease-or$BuildAIContext-or$PrepareTests-or$InitializePresentation-or$FinalizeFilesystemLayout){return $false}
    return $true
}
'@
if([regex]::Matches($text,[regex]::Escape($oldShadow)).Count-ne1){throw 'Split-phase proof shadow-policy replacement anchor count mismatch.'}
$text=$text.Replace($oldShadow,$newShadow)
[IO.File]::WriteAllText($runtimePath,$text,$utf8)

$tokens=$null;$errors=$null
[void][Management.Automation.Language.Parser]::ParseFile($runtimePath,[ref]$tokens,[ref]$errors)
if(@($errors).Count){throw('Patched runtime parser failure: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
$patched=[IO.File]::ReadAllText($runtimePath,[Text.Encoding]::UTF8)
foreach($required in @('function Try-BindTokenBoundUpdateAllMetadataContextEarly','if(-not$UpdateAll-or[string]::IsNullOrWhiteSpace([string]$ExpectedInstanceId)){return $false}','$tokenBoundUpdateAllContextRecovered=Try-BindTokenBoundUpdateAllMetadataContextEarly',"`$script:BindingResolutionError='Multi-Hub registry: '+`$registryResolutionFailure",'if($UpdateAll-and-not[string]::IsNullOrWhiteSpace([string]$ExpectedInstanceId)-and-not[string]::IsNullOrWhiteSpace([string]$script:BindingResolutionError)){return $false}')){
    if(-not$patched.Contains($required)){throw('Patched runtime missing proof token: '+$required)}
}
if($patched.Contains('$allowRegistryUnresolved=$Doctor-or$SelfTest-or$BuildDistribution-or$BuildRelease-or$BuildAIContext-or$UpdateManager-or$UpdateAll')){throw 'Proof accidentally added generic UpdateAll unresolved-registry bypass.'}
Write-Host 'MANAGER 4.17.13 UPDATEALL SPLIT-PHASE PROOF PATCH: APPLIED' -ForegroundColor Green
Write-Host '  scope: disposable workflow checkout only'
Write-Host '  token-bound metadata recovery: enabled only after registry + active selection validation'
Write-Host '  compatibility-shadow bypass: only while preserved binding failure keeps Hub phase closed'
Write-Host '  product repository bytes: unchanged by this proof helper'