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
function Read-Json([string]$Relative){
    $path=Join-Path $RepositoryRoot ($Relative.Replace('/','\'))
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){Fail('Entry oracle dependency missing: '+$Relative)}
    try{return Get-Content -LiteralPath $path -Raw -Encoding UTF8|ConvertFrom-Json}
    catch{Fail('Invalid JSON '+$Relative+': '+$_.Exception.Message)}
}
function Write-Json([string]$Path,$Object){
    $parent=Split-Path -Parent $Path
    if($parent-and-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
    [IO.File]::WriteAllText($Path,(($Object|ConvertTo-Json -Depth 40).Replace("`r`n","`n"))+"`n",$Utf8NoBom)
}

$oracle=Read-Json 'tests/knowledge/entry-reachability-oracles.json'
if([string]$oracle.schema-cne'keelaryn.manager-entry-oracles.v2'){Fail 'Unexpected entry oracle schema.'}
if([string]$oracle.semantic_owner-cne'tests/knowledge/state-machines/multi-hub.json'){Fail 'Entry oracle semantic owner must remain the canonical multi-Hub state machine.'}
if([string]$oracle.planner_owner-cne'tools/Build-ManagerEntryReachabilityPlan.ps1'){Fail 'Entry oracle planner owner drifted.'}
if([string]$oracle.oracle_key-cne'winning_rule'){Fail 'Entry oracle key must remain canonical winning_rule.'}
if([string]$oracle.legacy_model_role-cne'migration_cross_check_only'){Fail 'Legacy Entry model must not regain semantic ownership.'}
if([bool]$oracle.fallback_oracle_permitted){Fail 'Entry oracle fallback is prohibited.'}
if([bool]$oracle.transaction_fault_properties_included){Fail 'Transaction fault properties must remain outside Entry Reachability.'}

$allowed=@(
    'list_success','registry_document_rejected_after_dispatch','target_success','target_rejected_no_mutation',
    'global_success','diagnostic_reached','doctor_stranded_global_diagnostic','fail_closed','stranded_global_blocked',
    'active_instance_candidate_visible','updateall_manager_updates_then_hub_fails_closed','captured_context_required_fail_closed',
    'active_instance_candidate_transport_scope','active_instance_candidate_restore_scope','registry_init_rejected_after_dispatch',
    'registry_init_reconciles_global_input','registry_init_mixed_invalid_preserves_completed_handoff_and_failed_claim'
)
$oracleByRule=@{}
foreach($row in @($oracle.rule_oracles)){
    $rule=([string]$row.winning_rule).Trim();$mode=([string]$row.observation_mode).Trim()
    if([string]::IsNullOrWhiteSpace($rule)-or[string]::IsNullOrWhiteSpace($mode)){Fail 'Entry oracle row contains an empty required field.'}
    if($allowed-cnotcontains$mode){Fail('Unsupported entry observation mode: '+$mode)}
    if($oracleByRule.ContainsKey($rule)){Fail('Duplicate entry oracle winning rule: '+$rule)}
    $actions=@()
    if($null-ne$row.PSObject.Properties['action']){$actions=@(([string]$row.action).Trim())}
    elseif($null-ne$row.PSObject.Properties['actions']){$actions=@($row.actions|ForEach-Object{([string]$_).Trim()})}
    if($actions.Count-eq0-or@($actions|Where-Object{[string]::IsNullOrWhiteSpace($_)}).Count-ne0){Fail('Entry oracle has no explicit action ownership: '+$rule)}
    if($actions.Count-ne@($actions|Sort-Object -Unique).Count){Fail('Entry oracle has duplicate actions: '+$rule)}
    $oracleByRule[$rule]=[pscustomobject]@{Mode=$mode;Actions=@($actions)}
}

$tempPlan=Join-Path ([IO.Path]::GetTempPath()) ('MANAGER_ENTRY_PLAN_ORACLE_CONTRACT_'+[guid]::NewGuid().ToString('N')+'.json')
try{
    $planner=Join-Path $RepositoryRoot 'tools\Build-ManagerEntryReachabilityPlan.ps1';$exe=Join-Path $PSHOME 'powershell.exe'
    & $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $planner -RepositoryRoot $RepositoryRoot -OutputPath $tempPlan
    if($LASTEXITCODE-ne0){Fail('Bounded entry planner failed with exit '+$LASTEXITCODE)}
    $plan=Get-Content -LiteralPath $tempPlan -Raw -Encoding UTF8|ConvertFrom-Json
    if([string]$plan.schema-cne'keelaryn.manager-entry-plan.v1'){Fail 'Unexpected bounded entry plan schema.'}
    if([bool]$plan.fixed_scenario_count_requirement){Fail 'Bounded planner must not require a fixed scenario count.'}
    if([bool]$plan.transaction_fault_injection_included){Fail 'Bounded planner must exclude transaction fault injection.'}

    $seenRules=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
    $modeCounts=@{}
    foreach($edge in @($plan.edges)){
        $rule=[string]$edge.winning_rule;$action=[string]$edge.action
        if(-not$oracleByRule.ContainsKey($rule)){Fail('Canonical planner winning rule has no explicit oracle: '+$rule+'; edge='+[string]$edge.id)}
        $entry=$oracleByRule[$rule]
        if(@($entry.Actions)-cnotcontains$action){Fail('Entry oracle action ownership mismatch: rule='+$rule+' action='+$action)}
        [void]$seenRules.Add($rule)
        $mode=[string]$entry.Mode;if(-not$modeCounts.ContainsKey($mode)){$modeCounts[$mode]=0};$modeCounts[$mode]=[int]$modeCounts[$mode]+1
    }
    if($seenRules.Count-ne$oracleByRule.Count){$extra=@($oracleByRule.Keys|Where-Object{-not$seenRules.Contains([string]$_)});Fail('Oracle contract contains winning rules absent from canonical planner: '+([string]::Join(', ',@($extra))))}

    $report=[ordered]@{schema='keelaryn.manager-entry-oracle-contract-check.v2';semantic_owner=[string]$oracle.semantic_owner;planner_owner=[string]$oracle.planner_owner;derived_edge_count=@($plan.edges).Count;winning_rule_count=$seenRules.Count;explicit_oracle_count=$oracleByRule.Count;fallback_oracle_permitted=$false;transaction_fault_properties_included=$false;observation_mode_counts=[ordered]@{};pass=$true}
    foreach($mode in @($modeCounts.Keys|Sort-Object)){$report.observation_mode_counts[$mode]=[int]$modeCounts[$mode]}
    if(-not[string]::IsNullOrWhiteSpace($OutputPath)){Write-Json ([IO.Path]::GetFullPath($OutputPath)) $report}
    Write-Host ('MANAGER ENTRY ORACLE CONTRACT: PASS; derived_edges='+@($plan.edges).Count+' winning_rules='+$seenRules.Count+' explicit_oracles='+$oracleByRule.Count) -ForegroundColor Green
    Write-Host '  semantic owner: canonical multi-Hub state machine'
    Write-Host '  fallback oracle: prohibited'
    Write-Host '  transaction fault properties: separate'
}finally{if(Test-Path -LiteralPath $tempPlan){Remove-Item -LiteralPath $tempPlan -Force -ErrorAction SilentlyContinue}}
exit 0
