[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')

function Fail([string]$Message){throw $Message}
function Read-Json([string]$RelativePath){
    $path=Join-Path $RepositoryRoot ($RelativePath.Replace('/','\'))
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){Fail('Missing qualification architecture dependency: '+$RelativePath)}
    try{return Get-Content -LiteralPath $path -Raw -Encoding UTF8|ConvertFrom-Json}
    catch{Fail('Invalid JSON '+$RelativePath+': '+$_.Exception.Message)}
}
function Read-Text([string]$RelativePath){
    $path=Join-Path $RepositoryRoot ($RelativePath.Replace('/','\'))
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){Fail('Missing qualification architecture implementation: '+$RelativePath)}
    return [IO.File]::ReadAllText($path,[Text.Encoding]::UTF8)
}
function Require-True([bool]$Value,[string]$Message){if(-not$Value){Fail($Message)}}
function Require-False([bool]$Value,[string]$Message){if($Value){Fail($Message)}}
function Require-Contains($Values,[string]$Expected,[string]$Owner){
    if(@($Values|ForEach-Object{[string]$_}) -cnotcontains $Expected){Fail($Owner+' omitted required value: '+$Expected)}
}

$architecturePath='tests/knowledge/architecture/qualification-consolidation-4.17.13.json'
$architecture=Read-Json $architecturePath
$machine=Read-Json 'tests/knowledge/state-machines/multi-hub.json'
$developmentState=Read-Json 'MANAGER_DEVELOPMENT_STATE.json'
$proofManifest=Read-Json 'tests/knowledge/qualification/capability-proofs.json'
$strandedDesign=Read-Json 'tests/knowledge/architecture/stranded-input-reconciliation-4.17.13.json'

if([string]$architecture.schema-cne'keelaryn.manager-qualification-architecture.v1'){Fail 'Unexpected qualification architecture schema.'}
if([string]$architecture.work_item_id-cne'MQA-41713-001'){Fail 'Unexpected qualification architecture work-item id.'}
if([string]$architecture.status-cne'in_progress'){Fail '4.17.13 qualification consolidation must remain in_progress until its acceptance sequence is complete.'}
Require-False ([bool]$architecture.product_bytes_changed_by_work_item) 'Qualification-consolidation work item must not claim product-byte changes before the product implementation commit.'
Require-False ([bool]$architecture.production_hub_mutation_permitted) 'Manager Development must not permit production Hub mutation.'
Require-False ([bool]$architecture.candidate_freeze_permitted) 'Candidate freeze must remain blocked during qualification consolidation.'

$entry=$architecture.qualification_contract.entry_reachability
if([string]$entry.semantic_owner-cne'tests/knowledge/state-machines/multi-hub.json'){Fail 'State machine must be the semantic owner of Entry Reachability.'}
if([string]$entry.coverage_basis-cne'winning_rule_and_control_flow_edge_cover'){Fail 'Entry Reachability coverage must be a winning-rule/control-flow edge cover.'}
Require-False ([bool]$entry.fixed_scenario_count_is_requirement) 'Entry Reachability must not use a fixed scenario count as a qualification requirement.'
Require-False ([bool]$entry.supplemental_fault_scenarios_are_entry_reachability) 'Transaction fault scenarios must not be modeled as Entry Reachability supplementals.'
Require-True ([bool]$entry.must_preserve_state_dependent_behavior) 'Entry Reachability consolidation must preserve real state-dependent behavior.'
Require-True ([bool]$entry.bounded_planner_implemented) 'Bounded Entry Reachability planner must remain implemented.'
Require-True ([bool]$entry.legacy_count_based_executor_pending_replacement) 'Legacy count-based executor must remain explicitly marked pending until replaced.'

Require-True ([bool]$architecture.qualification_contract.transaction_fault_properties.separate_from_entry_reachability) 'Transaction fault/property tests must be separate from Entry Reachability.'
Require-False ([bool]$architecture.qualification_contract.risk_gate.direct_child_execution_target) 'Risk Gate target architecture must verify receipts rather than directly execute child proofs.'
Require-True ([bool]$architecture.qualification_contract.risk_gate.receipt_verifier_implemented) 'Risk Gate receipt verifier must be implemented.'
$schedulerContract=$architecture.qualification_contract.execution_scheduler
Require-True ([bool]$schedulerContract.implemented) 'Single qualification scheduler must be implemented.'
if([string]$schedulerContract.implementation-cne'tools/Invoke-ManagerQualificationScheduler.ps1'){Fail 'Unexpected qualification scheduler implementation path.'}
if([string]$schedulerContract.proof_manifest-cne'tests/knowledge/qualification/capability-proofs.json'){Fail 'Unexpected qualification proof manifest path.'}
Require-False ([bool]$schedulerContract.same_sha_same_boundary_duplicate_execution_permitted) 'Same-SHA proof duplication within one trust boundary must remain prohibited.'
foreach($token in @('exact_source_commit','exact_source_tree','risk_context_identity','selected_requirement_ids','selected_capability_suite_ids','executed_proof_ids','result')){Require-Contains $schedulerContract.receipt_must_bind $token 'scheduler receipt contract'}
Require-True ([bool]$architecture.qualification_contract.fresh_validation_at_new_boundary_required) 'Fresh validation must remain required at new trust boundaries.'
Require-False ([bool]$architecture.qualification_contract.source_gate_full_gate_production_acceptance_deduplication_permitted) 'Development deduplication must not weaken Source/Full Gate or production acceptance.'

Require-False ([bool]$architecture.capability_suite_direction.recursive_suite_invocation_permitted) 'Capability suites must not recursively invoke another suite.'
if([int]$architecture.capability_suite_direction.orchestrator_count-ne1){Fail 'Exactly one proof orchestrator must own suite selection/execution per trust boundary.'}
Require-True ([bool]$architecture.capability_suite_direction.legacy_version_scripts.freeze_blocker) 'Legacy recursive version scripts must remain a freeze blocker until flattened.'

if([string]$proofManifest.schema-cne'keelaryn.manager-qualification-proofs.v1'){Fail 'Unexpected qualification proof manifest schema.'}
if([int]$proofManifest.execution_contract.same_path_same_boundary_max_execution_count-ne1){Fail 'Proof manifest must allow each path at most once per boundary.'}
Require-False ([bool]$proofManifest.execution_contract.risk_gate_executes_child_proofs) 'Proof manifest must prohibit Risk Gate child-proof execution.'
Require-True ([bool]$proofManifest.execution_contract.scheduler_receipt_required) 'Proof manifest must require scheduler receipt.'
Require-False ([bool]$proofManifest.execution_contract.fresh_boundary_receipt_reuse_permitted) 'Proof receipt must not cross trust boundaries.'

$requiredSafety=@(
    'immutable_canonical_instance_id',
    'registry_authority_once_active',
    'exact_artifact_instance_binding',
    'cross_instance_fail_closed',
    'captured_invocation_context',
    'fresh_commit_boundary_validation',
    'deterministic_atomic_publication_semantics',
    'destination_collision_detection',
    'durable_commit_vs_post_commit_failure_distinction',
    'downgrade_compatibility_isolation',
    'Doctor',
    'actual_update_install_rollback_qualification',
    'exact_source_and_artifact_identity',
    'fresh_qualification_at_freeze_and_production_boundaries'
)
foreach($token in $requiredSafety){Require-Contains $architecture.preserved_safety_invariants $token 'qualification architecture'}

$transaction=$architecture.stranded_input_transaction_review
if([string]$transaction.source_symbol-cne'Reconcile-StrandedGlobalHubInputsForExistingRegistry'){Fail 'Unexpected stranded-input source symbol.'}
if([string]$transaction.current_semantic_rule-cne'R-REGISTRY-PENDING-GLOBAL-INVALID-INIT'){Fail 'Unexpected stranded-input semantic-rule owner.'}
if([string]$transaction.open_defect-cne'MGR-DEF-0034'){Fail 'Stage-loss blocker must be MGR-DEF-0034.'}
Require-True ([bool]$transaction.state_machine_review_completed) 'Stranded-input state-machine review must be complete before product implementation.'
Require-False ([bool]$transaction.product_change_deferred_until_state_machine_review) 'Product change must no longer be blocked on a completed semantic review.'
Require-True ([bool]$transaction.implementation_authorized) 'Reviewed stranded-input contract must authorize implementation.'
if([string]$transaction.selected_contract.name-cne'per_artifact_claim_validate_publish'){Fail 'Unexpected stranded-input selected contract.'}
Require-True ([bool]$transaction.selected_contract.requires_state_machine_change) 'Selected stranded-input contract must require canonical state-machine update.'
Require-True ([bool]$transaction.selected_contract.implementation_pending) 'Product transaction implementation must remain pending until product bytes actually change and pass coverage.'

if([string]$strandedDesign.schema-cne'keelaryn.stranded-input-reconciliation-design.v1'-or[string]$strandedDesign.design_id-cne'SIR-41713-001'){Fail 'Unexpected stranded-input design identity.'}
if([string]$strandedDesign.status-cne'semantic_review_complete_implementation_pending'){Fail 'Stranded-input design must remain implementation-pending.'}
if([string]$strandedDesign.selected_semantics-cne'per-artifact claim_validate_publish'.Replace(' ','_')){Fail 'Stranded-input design selected semantics drifted.'}
Require-True ([bool]$strandedDesign.claim_recovery_contract.claim_is_durable_transaction_state) 'Reconciliation claim must be durable transaction state.'
Require-True ([bool]$strandedDesign.claim_recovery_contract.claim_is_never_silently_deleted) 'Reconciliation claim must never be silently deleted.'
Require-True ([bool]$strandedDesign.claim_recovery_contract.claim_must_remain_discoverable_after_restart) 'Reconciliation claim must survive restart discovery.'
Require-True ([bool]$strandedDesign.claim_recovery_contract.claim_must_be_visible_to_doctor) 'Doctor must surface reconciliation claims.'
Require-True ([bool]$strandedDesign.implementation_authorization.state_machine_review_completed) 'Stranded-input implementation authorization lacks state-machine review.'
Require-True ([bool]$strandedDesign.implementation_authorization.product_implementation_may_start) 'Stranded-input product implementation is not authorized.'
Require-False ([bool]$strandedDesign.implementation_authorization.candidate_freeze_permitted) 'Stranded-input design must not permit candidate freeze before implementation/evidence.'

$semanticRule=@($machine.rules|Where-Object{[string]$_.id-ceq[string]$transaction.current_semantic_rule})
if($semanticRule.Count-ne1){Fail 'Stranded-input semantic rule is missing or duplicated.'}
if([string]$semanticRule[0].operation-cne'InitializeRegistry'){Fail 'Stranded-input semantic rule no longer governs InitializeRegistry.'}

$defectFiles=@(Get-ChildItem -LiteralPath (Join-Path $RepositoryRoot 'tests\knowledge\defects') -File -Filter '*.json'|Sort-Object Name)
$allDefects=New-Object System.Collections.ArrayList
foreach($file in $defectFiles){
    $doc=Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8|ConvertFrom-Json
    foreach($defect in @($doc.defects)){[void]$allDefects.Add($defect)}
}
$stageLoss=@($allDefects|Where-Object{[string]$_.id-ceq'MGR-DEF-0034'})
if($stageLoss.Count-ne1){Fail 'MGR-DEF-0034 must exist exactly once.'}
if([string]$stageLoss[0].status-cne'open'-or[string]$stageLoss[0].severity-cne'P1'-or-not[bool]$stageLoss[0].release_blocker){Fail 'MGR-DEF-0034 must remain an open P1 release blocker until the transaction design is corrected.'}

$schedulerText=Read-Text 'tools/Invoke-ManagerQualificationScheduler.ps1'
$riskGateText=Read-Text 'tools/Invoke-ManagerRiskDefectGate.ps1'
$developmentText=Read-Text 'tools/Invoke-DevelopmentValidation.ps1'
$entryWorkflowText=Read-Text '.github/workflows/entry-reachability-validation.yml'
if(-not$schedulerText.Contains('keelaryn.manager-qualification-execution-receipt.v1')){Fail 'Qualification scheduler does not emit the required receipt schema.'}
if(-not$schedulerText.Contains('duplicate_execution_count=0')){Fail 'Qualification scheduler does not explicitly bind zero duplicate execution.'}
if(-not$riskGateText.Contains('ExecutionReceiptPath')){Fail 'Risk Gate does not require an execution receipt.'}
if($riskGateText.Contains('Invoke-Child $path')){Fail 'Risk Gate still directly executes risk-selected regression scripts.'}
if(-not$developmentText.Contains('Invoke-ManagerQualificationScheduler.ps1')){Fail 'Development Validation does not invoke the single qualification scheduler.'}
if($developmentText.Contains('foreach($regressionName')){Fail 'Development Validation still independently owns review-regression execution.'}
if($entryWorkflowText.Contains('Invoke-ManagerEntryReachabilityMatrix.ps1')){Fail 'Dedicated Entry Reachability workflow still duplicates executable matrix ownership.'}

Require-Contains $developmentState.open_release_blockers 'MGR-DEF-0034' 'development state'
if([string]$developmentState.next_exact_goal.id-cne'MANAGER-41713-CONSOLIDATION-001'){Fail 'Development state must point at the qualification-consolidation goal.'}
if([bool]$developmentState.next_exact_goal.candidate_freeze_permitted){Fail 'Development state must keep candidate freeze blocked.'}
if(([string]$developmentState.next_exact_goal.description)-match'(?<!\d)10[234](?!\d)'){Fail 'Development next goal must not preserve a magic Entry Reachability scenario count.'}

Write-Host 'MANAGER QUALIFICATION ARCHITECTURE: PASS' -ForegroundColor Green
Write-Host ('  work item: '+[string]$architecture.work_item_id)
Write-Host ('  scheduler: '+[string]$schedulerContract.implementation)
Write-Host '  Risk Gate: receipt verification only'
Write-Host ('  semantic owner: '+[string]$entry.semantic_owner)
Write-Host ('  stranded-input contract: '+[string]$transaction.selected_contract.name)
Write-Host ('  open transaction blocker: '+[string]$transaction.open_defect)
Write-Host '  fixed Entry Reachability scenario count: prohibited'
Write-Host '  recursive legacy version scripts: still freeze-blocking'
exit 0
