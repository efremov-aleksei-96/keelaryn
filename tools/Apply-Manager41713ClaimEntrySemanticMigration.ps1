[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$Utf8NoBom=New-Object Text.UTF8Encoding($false)

function Fail([string]$Message){throw $Message}
function Read-Normalized([string]$Path){return [IO.File]::ReadAllText($Path,[Text.Encoding]::UTF8).Replace("`r`n","`n")}
function Write-Normalized([string]$Path,[string]$Text){[IO.File]::WriteAllText($Path,$Text.Replace("`r`n","`n"),$Utf8NoBom)}
function Replace-One([string]$Text,[string]$Old,[string]$New,[string]$Label){
    $count=[regex]::Matches($Text,[regex]::Escape($Old)).Count
    if($count-ne1){Fail($Label+' replacement anchor count='+$count)}
    return $Text.Replace($Old,$New)
}
function Assert-Json([string]$Path,[string]$Label){try{$null=Get-Content -LiteralPath $Path -Raw -Encoding UTF8|ConvertFrom-Json}catch{Fail($Label+' JSON validation failed: '+$_.Exception.Message)}}
function Assert-Parse([string]$Path,[string]$Label){$tokens=$null;$errors=$null;[void][Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors);if(@($errors).Count){Fail($Label+' parser failure: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}}

$machinePath=Join-Path $RepositoryRoot 'tests\knowledge\state-machines\multi-hub.json'
$oraclePath=Join-Path $RepositoryRoot 'tests\knowledge\entry-reachability-oracles.json'
$runnerPath=Join-Path $RepositoryRoot 'tools\Invoke-ManagerBoundedEntryReachability.ps1'
$contractPath=Join-Path $RepositoryRoot 'tools\Test-ManagerEntryOracleContract.ps1'
foreach($p in @($machinePath,$oraclePath,$runnerPath,$contractPath)){if(-not(Test-Path -LiteralPath $p -PathType Leaf)){Fail('Semantic migration dependency missing: '+$p)}}

# 1. Canonical semantic owner: replace obsolete whole-batch rollback rule with the
# reviewed per-artifact durable-claim contract. Earlier exact publications survive a
# later invalid artifact; the failed artifact remains a durable blocking claim.
$machine=Read-Normalized $machinePath
$oldMachine=@'
                      "outcome":  "reject_fail_closed",
                      "invariants":  [
                                         "MH-INBOX-001",
                                         "MH-COMMIT-001",
                                         "MH-LIFECYCLE-001"
                                     ],
                      "reason":  "Existing-registry reconciliation must validate the complete stranded-input batch before publishing any per-instance destination; a later invalid input must leave all global sources and per-instance lifecycle state unchanged."
'@.TrimEnd()
$newMachine=@'
                      "outcome":  "reconcile_per_artifact_preserve_completed_handoff_and_failed_claim",
                      "invariants":  [
                                         "MH-INBOX-001",
                                         "MH-COMMIT-001",
                                         "MH-LIFECYCLE-001",
                                         "MH-HANDOFF-001"
                                     ],
                      "reason":  "Existing-registry reconciliation is per artifact: earlier exact handoffs remain durable; a later invalid recognized input remains a durable blocking claim and must not roll back completed publications."
'@.TrimEnd()
$machine=Replace-One $machine $oldMachine $newMachine 'state-machine claim semantics'
Write-Normalized $machinePath $machine
Assert-Json $machinePath 'multi-Hub state machine'

# 2. Winning-rule oracle now names the reviewed claim-aware observation.
$oracle=Read-Normalized $oraclePath
$oracle=Replace-One $oracle '"registry_init_mixed_invalid_rejected_without_partial_handoff"' '"registry_init_mixed_invalid_preserves_completed_handoff_and_failed_claim"' 'Entry oracle mixed-invalid mode'
Write-Normalized $oraclePath $oracle
Assert-Json $oraclePath 'Entry oracle contract'

# 3. Oracle validator allowlist follows the canonical semantic migration.
$contract=Read-Normalized $contractPath
$contract=Replace-One $contract "'registry_init_mixed_invalid_rejected_without_partial_handoff'" "'registry_init_mixed_invalid_preserves_completed_handoff_and_failed_claim'" 'Entry oracle validator mode'
Write-Normalized $contractPath $contract
Assert-Parse $contractPath 'Entry oracle validator'

# 4. Bounded executor accepts both legacy-global and claim-aware refusal wording during
# the pre-materialization transition, while preserving fail-closed/source/no-mutation
# assertions. Mixed-invalid initialization gets a new structural oracle: exact valid
# handoff survives, invalid source is consumed into one durable claim, no invalid
# per-instance copy appears, and registry/active/Hub bytes stay coherent.
$runner=Read-Normalized $runnerPath
$planAnchor="$planTool=Join-Path `$RepositoryRoot 'tools\Build-ManagerEntryReachabilityPlan.ps1'"
$helper=@'
function Get-BoundedReconciliationClaims([string]$ManagerRoot){
    $root=Join-Path $ManagerRoot 'state\reconciliation\hub-inputs'
    $rows=New-Object System.Collections.ArrayList
    if(-not(Test-Path -LiteralPath $root -PathType Container)){return @($rows)}
    $rootItem=Get-Item -LiteralPath $root -Force -ErrorAction Stop
    if(-not$rootItem.PSIsContainer-or($rootItem.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){Fail('Bounded reconciliation root is unsafe: '+$root)}
    foreach($dir in @(Get-ChildItem -LiteralPath $root -Directory -Force -ErrorAction Stop|Sort-Object Name)){
        if(($dir.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){Fail('Bounded reconciliation claim is unsafe: '+$dir.FullName)}
        $metaPath=Join-Path $dir.FullName 'claim.json'
        if(-not(Test-Path -LiteralPath $metaPath -PathType Leaf)){Fail('Bounded reconciliation claim metadata missing: '+$metaPath)}
        try{$meta=Get-Content -LiteralPath $metaPath -Raw -Encoding UTF8|ConvertFrom-Json}catch{Fail('Bounded reconciliation claim metadata invalid: '+$metaPath+'; '+$_.Exception.Message)}
        if([string]$meta.schema-cne'keelaryn.manager.hub-input-reconciliation-claim.v1'){Fail('Unexpected bounded reconciliation claim schema: '+[string]$meta.schema)}
        $payload=Join-Path (Join-Path $dir.FullName 'payload') ([string]$meta.original_name)
        [void]$rows.Add([pscustomobject]@{Directory=$dir.FullName;Metadata=$meta;Payload=$payload})
    }
    return @($rows)
}

'@
$runner=Replace-One $runner $planAnchor ($helper+$planAnchor) 'bounded claim helper insertion'

$oldBlocked=@'
                'stranded_global_blocked' {$sourceRemains=($script:ScenarioPendingGlobalSource-and(Test-Path -LiteralPath $script:ScenarioPendingGlobalSource -PathType Leaf));$reached=$r.Text.Contains('remain in the global Manager inbox')-and$r.Text.Contains('reconcile identity-bound inputs first');$pass=($r.ExitCode-ne0-and$sourceRemains-and$reached-and$hubsUnchanged-and$lifecycleStateUnchanged);$detail=if($pass){'stranded global Hub input explicitly blocked instance-bound operation without mutation'}else{'stranded-global blocking proof failed: '+$r.Text}}
'@.TrimEnd()
$newBlocked=@'
                'stranded_global_blocked' {$sourceRemains=($script:ScenarioPendingGlobalSource-and(Test-Path -LiteralPath $script:ScenarioPendingGlobalSource -PathType Leaf));$legacySignal=$r.Text.Contains('remain in the global Manager inbox')-and$r.Text.Contains('reconcile identity-bound inputs first');$claimSignal=$r.Text.Contains('refused because unresolved Hub-input reconciliation state remains')-and$r.Text.Contains('Run Initialize instance registry');$reached=($legacySignal-or$claimSignal);$pass=($r.ExitCode-ne0-and$sourceRemains-and$reached-and$hubsUnchanged-and$lifecycleStateUnchanged);$detail=if($pass){'unresolved global Hub input explicitly blocked instance-bound operation without mutation'}else{'stranded-global blocking proof failed: '+$r.Text}}
'@.TrimEnd()
$runner=Replace-One $runner $oldBlocked $newBlocked 'bounded stranded-global matcher'

$oldMixed=@'
                'registry_init_mixed_invalid_rejected_without_partial_handoff' {$validRemains=($script:ScenarioPendingGlobalSource-and(Test-Path -LiteralPath $script:ScenarioPendingGlobalSource -PathType Leaf));$invalidRemains=($script:ScenarioPendingGlobalInvalidSource-and(Test-Path -LiteralPath $script:ScenarioPendingGlobalInvalidSource -PathType Leaf));$targetAbsent=($script:ScenarioPendingGlobalTarget-and-not(Test-Path -LiteralPath $script:ScenarioPendingGlobalTarget));$pass=($r.ExitCode-ne0-and$validRemains-and$invalidRemains-and$targetAbsent-and$hubsUnchanged-and$lifecycleStateUnchanged);$detail=if($pass){'current pre-product-fix mixed-invalid contract rejected batch without partial handoff'}else{'mixed-invalid registry-init proof failed: '+$r.Text}}
'@.TrimEnd()
$newMixed=@'
                'registry_init_mixed_invalid_preserves_completed_handoff_and_failed_claim' {$validName=[IO.Path]::GetFileName([string]$script:ScenarioPendingGlobalSource);$invalidName=[IO.Path]::GetFileName([string]$script:ScenarioPendingGlobalInvalidSource);$validConsumed=($script:ScenarioPendingGlobalSource-and-not(Test-Path -LiteralPath $script:ScenarioPendingGlobalSource -PathType Leaf));$invalidConsumed=($script:ScenarioPendingGlobalInvalidSource-and-not(Test-Path -LiteralPath $script:ScenarioPendingGlobalInvalidSource -PathType Leaf));$targetExact=$false;if($script:ScenarioPendingGlobalTarget-and(Test-Path -LiteralPath $script:ScenarioPendingGlobalTarget -PathType Leaf)){$targetExact=((Get-FileHash -LiteralPath $script:ScenarioPendingGlobalTarget -Algorithm SHA256).Hash.ToLowerInvariant()-ceq[string]$script:ScenarioPendingGlobalSha)};$validCopies=@(Get-ChildItem -LiteralPath $instancesStatePath -File -Recurse -Force|Where-Object{$_.Name-ceq$validName});$validScoped=($validCopies.Count-eq1-and[IO.Path]::GetFullPath($validCopies[0].FullName)-ceq[IO.Path]::GetFullPath([string]$script:ScenarioPendingGlobalTarget));$invalidCopies=@(Get-ChildItem -LiteralPath $instancesStatePath -File -Recurse -Force|Where-Object{$_.Name-ceq$invalidName});$claims=@(Get-BoundedReconciliationClaims $managerRoot);$invalidClaims=@($claims|Where-Object{[string]$_.Metadata.original_name-ceq$invalidName});$invalidClaimDurable=($invalidClaims.Count-eq1-and(Test-Path -LiteralPath ([string]$invalidClaims[0].Payload) -PathType Leaf));$pass=($r.ExitCode-ne0-and$validConsumed-and$invalidConsumed-and$targetExact-and$validScoped-and$invalidCopies.Count-eq0-and$invalidClaimDurable-and$claims.Count-eq1-and$hubsUnchanged-and$controlStateUnchanged-and$compatBaselineAfter-ceq$compatBaselineBefore);$detail=if($pass){'per-artifact reconciliation preserved the earlier exact handoff and retained the later invalid artifact as one durable blocking claim'}else{'mixed-invalid claim-aware registry-init proof failed: '+$r.Text}}
'@.TrimEnd()
$runner=Replace-One $runner $oldMixed $newMixed 'bounded mixed-invalid claim oracle'
Write-Normalized $runnerPath $runner
Assert-Parse $runnerPath 'bounded Entry executor'

Write-Host 'MANAGER 4.17.13 CLAIM-FIRST ENTRY SEMANTIC MIGRATION: PASS' -ForegroundColor Green
Write-Host '  canonical mixed-invalid rule: per-artifact durable claim semantics'
Write-Host '  stranded-global refusal matcher: legacy + claim-aware transition-safe'
Write-Host '  mixed-invalid oracle: exact completed handoff + durable failed claim'
