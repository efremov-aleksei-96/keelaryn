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

$architecture=Read-Json 'tests/knowledge/architecture/qualification-consolidation-4.17.13.json'
$machine=Read-Json 'tests/knowledge/state-machines/multi-hub.json'
$invariants=Read-Json 'tests/knowledge/invariants/multi-hub.json'
$developmentState=Read-Json 'MANAGER_DEVELOPMENT_STATE.json'
$proofManifest=Read-Json 'tests/knowledge/qualification/capability-proofs.json'
$strandedDesign=Read-Json 'tests/knowledge/architecture/stranded-input-reconciliation-4.17.13.json'
$transactionModel=Read-Json 'tests/knowledge/stranded-input-transaction-properties.json'

if([string]$architecture.schema-cne'keelaryn.manager-qualification-architecture.v1'){Fail 'Unexpected qualification architecture schema.'}
if([string]$architecture.work_item_id-cne'MQA-41713-001'){Fail 'Unexpected qualification architecture work-item id.'}
if([string]$architecture.status-cne'in_progress'){Fail '4.17.13 qualification architecture must remain in_progress until its full acceptance sequence is complete.'}
Require-True ([bool]$architecture.product_bytes_changed_by_work_item) 'Qualification architecture must record the materialized 4.17.13 product-byte change.'
Require-False ([bool]$architecture.production_hub_mutation_permitted) 'Manager Development must not permit production Hub mutation.'
Require-False ([bool]$architecture.candidate_freeze_permitted) 'Candidate freeze must remain blocked during qualification/transaction work.'

$entry=$architecture.qualification_contract.entry_reachability
if([string]$entry.semantic_owner-cne'tests/knowledge/state-machines/multi-hub.json'){Fail 'State machine must be the semantic owner of Entry Reachability.'}
if([string]$entry.coverage_basis-cne'winning_rule_and_control_flow_edge_cover'){Fail 'Entry Reachability coverage must be a winning-rule/control-flow edge cover.'}
Require-False ([bool]$entry.fixed_scenario_count_is_requirement) 'Entry Reachability must not use a fixed scenario count as a qualification requirement.'
Require-False ([bool]$entry.supplemental_fault_scenarios_are_entry_reachability) 'Transaction fault scenarios must not be modeled as Entry Reachability supplementals.'
Require-True ([bool]$entry.must_preserve_state_dependent_behavior) 'Entry Reachability must preserve real state-dependent behavior.'
Require-True ([bool]$entry.bounded_planner_implemented) 'Bounded Entry Reachability planner must remain implemented.'
Require-True ([bool]$entry.bounded_executor_implemented) 'Bounded Entry Reachability executor must remain implemented.'
if([string]$entry.behavioral_owner-cne'tools/Invoke-ManagerBoundedEntryReachability.ps1'){Fail 'Unexpected bounded Entry behavioral owner.'}
Require-False ([bool]$entry.legacy_count_based_executor_pending_replacement) 'Legacy count-based Entry behavioral ownership must already be replaced.'
if([string]$entry.legacy_count_based_artifacts_role-cne'static_migration_provenance_only'){Fail 'Legacy count-based Entry artifacts must remain static migration provenance only.'}

$transactionProperties=$architecture.qualification_contract.transaction_fault_properties
Require-True ([bool]$transactionProperties.separate_from_entry_reachability) 'Transaction fault/property tests must be separate from Entry Reachability.'
if([string]$transactionProperties.implementation_status-cne'pending'){Fail 'Transaction property execution must remain marked pending until its runner and product implementation are proven.'}

Require-False ([bool]$architecture.qualification_contract.risk_gate.direct_child_execution_target) 'Risk Gate target architecture must verify receipts rather than directly execute child proofs.'
Require-True ([bool]$architecture.qualification_contract.risk_gate.receipt_verifier_implemented) 'Risk Gate receipt verifier must be implemented.'
$schedulerContract=$architecture.qualification_contract.execution_scheduler
Require-True ([bool]$schedulerContract.implemented) 'Single qualification scheduler must be implemented.'
if([string]$schedulerContract.implementation-cne'tools/Invoke-ManagerQualificationScheduler.ps1'){Fail 'Unexpected qualification scheduler implementation path.'}
if([string]$schedulerContract.proof_manifest-cne'tests/knowledge/qualification/capability-proofs.json'){Fail 'Unexpected qualification proof manifest path.'}
if([string]$schedulerContract.entry_behavior_owner-cne'entry_bounded'){Fail 'Scheduler Entry behavioral owner must be entry_bounded.'}
Require-False ([bool]$schedulerContract.same_sha_same_boundary_duplicate_execution_permitted) 'Same-SHA proof duplication within one trust boundary must remain prohibited.'
foreach($token in @('exact_source_commit','exact_source_tree','risk_context_identity','selected_requirement_ids','selected_capability_suite_ids','executed_proof_ids','result')){Require-Contains $schedulerContract.receipt_must_bind $token 'scheduler receipt contract'}
Require-True ([bool]$architecture.qualification_contract.fresh_validation_at_new_boundary_required) 'Fresh validation must remain required at new trust boundaries.'
Require-False ([bool]$architecture.qualification_contract.source_gate_full_gate_production_acceptance_deduplication_permitted) 'Development deduplication must not weaken Source/Full Gate or production acceptance.'

Require-False ([bool]$architecture.capability_suite_direction.recursive_suite_invocation_permitted) 'Capability suites must not recursively invoke another suite.'
if([int]$architecture.capability_suite_direction.orchestrator_count-ne1){Fail 'Exactly one proof orchestrator must own suite selection/execution per trust boundary.'}
$legacyScripts=$architecture.capability_suite_direction.legacy_version_scripts
Require-False ([bool]$legacyScripts.freeze_blocker) 'Historical recursive source adapters must not remain a freeze blocker after active behavioral flattening.'
Require-True ([bool]$legacyScripts.source_recursion_retained_for_provenance) 'Architecture must distinguish retained historical source recursion from active execution.'
if([string]$legacyScripts.active_behavior_owner-cne'historical_flat_lineage'){Fail 'Historical active behavioral owner must remain historical_flat_lineage.'}
if([string]$legacyScripts.status-cne'static_provenance_active_behavior_flattened'){Fail 'Historical source status must record static provenance plus flat active behavior.'}

if([string]$proofManifest.schema-cne'keelaryn.manager-qualification-proofs.v1'){Fail 'Unexpected qualification proof manifest schema.'}
if([int]$proofManifest.execution_contract.same_path_same_boundary_max_execution_count-ne1){Fail 'Proof manifest must allow each path at most once per boundary.'}
Require-False ([bool]$proofManifest.execution_contract.risk_gate_executes_child_proofs) 'Proof manifest must prohibit Risk Gate child-proof execution.'
Require-True ([bool]$proofManifest.execution_contract.scheduler_receipt_required) 'Proof manifest must require scheduler receipt.'
Require-False ([bool]$proofManifest.execution_contract.fresh_boundary_receipt_reuse_permitted) 'Proof receipt must not cross trust boundaries.'
if([string]$proofManifest.execution_contract.entry_behavior_owner-cne'entry_bounded'){Fail 'Proof manifest must assign Entry behavior to entry_bounded.'}
Require-False ([bool]$proofManifest.execution_contract.legacy_count_based_entry_proofs_execute_in_scheduler) 'Legacy count-based Entry proofs must not execute in scheduler.'
$entryBounded=@($proofManifest.proofs|Where-Object{[string]$_.id-ceq'entry_bounded'})
if($entryBounded.Count-ne1){Fail 'Proof manifest must declare entry_bounded exactly once.'}
if([string]$entryBounded[0].path-cne'tools/Invoke-ManagerBoundedEntryReachability.ps1'){Fail 'entry_bounded proof path drifted.'}
if(@($proofManifest.mandatory_development_proofs|ForEach-Object{[string]$_}) -cnotcontains 'entry_bounded'){Fail 'entry_bounded must be mandatory development coverage.'}
foreach($legacyId in @('entry_model_legacy_static','entry_matrix_legacy_static')){
    $legacy=@($proofManifest.proofs|Where-Object{[string]$_.id-ceq$legacyId})
    if($legacy.Count-ne1-or[string]$legacy[0].execution-cne'static'-or-not[bool]$legacy[0].migration_only){Fail($legacyId+' must be one static migration-only proof.')}
    if(@($legacy[0].capability_suites).Count-ne0){Fail($legacyId+' must not claim behavioral capabilities.')}
    if(@($proofManifest.mandatory_development_proofs|ForEach-Object{[string]$_}) -ccontains $legacyId){Fail($legacyId+' must not be mandatory behavioral ownership.')}
}

$requiredSafety=@(
    'immutable_canonical_instance_id','registry_authority_once_active','exact_artifact_instance_binding','cross_instance_fail_closed',
    'captured_invocation_context','fresh_commit_boundary_validation','deterministic_atomic_publication_semantics','destination_collision_detection',
    'durable_commit_vs_post_commit_failure_distinction','downgrade_compatibility_isolation','Doctor','actual_update_install_rollback_qualification',
    'exact_source_and_artifact_identity','fresh_qualification_at_freeze_and_production_boundaries'
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
Require-True ([bool]$transaction.selected_contract.implementation_pending) 'Stranded-input product transaction implementation must remain pending until MGR-DEF-0034 bytes and property coverage land.'

if([string]$strandedDesign.schema-cne'keelaryn.stranded-input-reconciliation-design.v1'-or[string]$strandedDesign.design_id-cne'SIR-41713-001'){Fail 'Unexpected stranded-input design identity.'}
if([string]$strandedDesign.status-cne'semantic_review_complete_implementation_pending'){Fail 'Stranded-input design must remain implementation-pending.'}
if([string]$strandedDesign.selected_semantics-cne'per-artifact claim_validate_publish'){Fail 'Stranded-input design selected semantics drifted.'}
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
$handoffInvariant=@($invariants.invariants|Where-Object{[string]$_.id-ceq'MH-HANDOFF-001'})
if($handoffInvariant.Count-ne1){Fail 'MH-HANDOFF-001 must exist exactly once.'}
foreach($coverage in @('static','executable','transaction_property')){Require-Contains $handoffInvariant[0].coverage $coverage 'MH-HANDOFF-001 coverage'}

if([string]$transactionModel.schema-cne'keelaryn.manager-stranded-input-transaction-properties.v1'){Fail 'Unexpected stranded-input transaction-property schema.'}
if([string]$transactionModel.work_item-cne'MANAGER-41713-TRANSACTION-001'){Fail 'Unexpected transaction-property work item.'}
if([string]$transactionModel.defect-cne'MGR-DEF-0034'){Fail 'Transaction-property model must bind MGR-DEF-0034.'}
if([string]$transactionModel.semantic_owner-cne'tests/knowledge/state-machines/multi-hub.json'){Fail 'Transaction properties must remain state-machine governed.'}
if([string]$transactionModel.primary_invariant-cne'MH-HANDOFF-001'){Fail 'Transaction properties must bind MH-HANDOFF-001.'}
Require-False ([bool]$transactionModel.entry_reachability_owned) 'Transaction properties must remain outside Entry Reachability.'
Require-False ([bool]$transactionModel.fixed_property_count_is_release_invariant) 'Transaction properties must not create a magic fixed-count release invariant.'
if([string]$transactionModel.transaction_contract-cne'per_artifact_claim_validate_publish'){Fail 'Transaction-property contract drifted.'}
if([string]$transactionModel.claim_contract.root-cne'manager/state/reconciliation/hub-inputs'){Fail 'Unexpected durable reconciliation claim root.'}
Require-True ([bool]$transactionModel.claim_contract.payload_is_durable_transaction_state) 'Claim payload must be durable transaction state.'
Require-True ([bool]$transactionModel.claim_contract.claim_metadata_survives_payload_publication_until_final_destination_verification) 'Claim metadata must survive until final destination verification.'
Require-False ([bool]$transactionModel.claim_contract.target_selection_before_post_claim_identity_validation_permitted) 'Target selection before claim identity validation must remain prohibited.'
Require-False ([bool]$transactionModel.claim_contract.silent_claim_cleanup_permitted) 'Silent claim cleanup must remain prohibited.'
Require-True ([bool]$transactionModel.claim_contract.ordinary_hub_bound_operations_blocked_while_unresolved) 'Unresolved claims must block ordinary Hub-bound operations.'
Require-True ([bool]$transactionModel.claim_contract.doctor_visibility_required) 'Doctor visibility of unresolved claims must remain mandatory.'
$propertyIds=@($transactionModel.properties|ForEach-Object{[string]$_.id})
if($propertyIds.Count-ne@($propertyIds|Sort-Object -Unique).Count){Fail 'Transaction-property ids must be unique.'}
foreach($requiredId in @('SITP-001','SITP-002','SITP-003','SITP-004','SITP-005','SITP-006','SITP-007','SITP-008','SITP-009','SITP-010','SITP-011')){Require-Contains $propertyIds $requiredId 'transaction property model'}
Require-True ([bool]$transactionModel.acceptance.pre_fix_red_required) 'Transaction model must require a pre-fix RED.'
Require-True ([bool]$transactionModel.acceptance.post_fix_green_required) 'Transaction model must require a post-fix GREEN.'
Require-True ([bool]$transactionModel.acceptance.windows_disposable_execution_required) 'Transaction properties must execute on disposable Windows.'
Require-False ([bool]$transactionModel.acceptance.production_hub_use_permitted) 'Transaction properties must never use production Hub state.'
Require-False ([bool]$transactionModel.acceptance.candidate_freeze_permitted) 'Transaction property model must not permit candidate freeze.'

$defectFiles=@(Get-ChildItem -LiteralPath (Join-Path $RepositoryRoot 'tests\knowledge\defects') -File -Filter '*.json'|Sort-Object Name)
$allDefects=New-Object System.Collections.ArrayList
foreach($file in $defectFiles){$doc=Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8|ConvertFrom-Json;foreach($defect in @($doc.defects)){[void]$allDefects.Add($defect)}}
$stageLoss=@($allDefects|Where-Object{[string]$_.id-ceq'MGR-DEF-0034'})
if($stageLoss.Count-ne1){Fail 'MGR-DEF-0034 must exist exactly once.'}
if([string]$stageLoss[0].status-cne'open'-or[string]$stageLoss[0].severity-cne'P1'-or-not[bool]$stageLoss[0].release_blocker){Fail 'MGR-DEF-0034 must remain an open P1 release blocker until the transaction implementation is corrected and proven.'}
$splitPhase=@($allDefects|Where-Object{[string]$_.id-ceq'MGR-DEF-0035'})
if($splitPhase.Count-ne1-or[string]$splitPhase[0].status-cne'closed'-or[bool]$splitPhase[0].release_blocker){Fail 'MGR-DEF-0035 must remain closed and non-blocking after its exact-head 55/55 proof.'}

$schedulerText=Read-Text 'tools/Invoke-ManagerQualificationScheduler.ps1'
$riskGateText=Read-Text 'tools/Invoke-ManagerRiskDefectGate.ps1'
$developmentText=Read-Text 'tools/Invoke-DevelopmentValidation.ps1'
$developmentWorkflowText=Read-Text '.github/workflows/development-validation.yml'
$entryWorkflowText=Read-Text '.github/workflows/entry-reachability-validation.yml'
if(-not$schedulerText.Contains('keelaryn.manager-qualification-execution-receipt.v1')){Fail 'Qualification scheduler does not emit the required receipt schema.'}
if(-not$schedulerText.Contains('duplicate_execution_count=0')){Fail 'Qualification scheduler does not explicitly bind zero duplicate execution.'}
if(-not$riskGateText.Contains('ExecutionReceiptPath')){Fail 'Risk Gate does not require an execution receipt.'}
if($riskGateText.Contains('Invoke-Child $path')){Fail 'Risk Gate still directly executes risk-selected regression scripts.'}
if(-not$developmentText.Contains('Invoke-ManagerQualificationScheduler.ps1')){Fail 'Development Validation does not invoke the single qualification scheduler.'}
if($developmentText.Contains('foreach($regressionName')){Fail 'Development Validation still independently owns review-regression execution.'}
if($developmentWorkflowText.Contains('Derive bounded process-entry plan')){Fail 'Development workflow still duplicates bounded plan derivation outside scheduler ownership.'}
if($entryWorkflowText.Contains('Invoke-ManagerBoundedEntryReachability.ps1')){Fail 'Dedicated Entry workflow must remain model-only and must not execute bounded Manager behavior.'}
if($entryWorkflowText.Contains('Apply-Manager41713UpdateAllSplitPhaseProofPatch.ps1')){Fail 'Dedicated Entry workflow still depends on superseded disposable product-patch proof.'}
foreach($required in @('Build-ManagerEntryReachabilityPlan.ps1','Test-ManagerEntryOracleContract.ps1','Test-ManagerEntryOracleMigration.ps1')){if(-not$entryWorkflowText.Contains($required)){Fail('Dedicated Entry model workflow omits '+$required)}}

$blockers=@($developmentState.open_release_blockers|ForEach-Object{[string]$_})
if($blockers.Count-ne1-or$blockers[0]-cne'MGR-DEF-0034'){Fail 'Development state must expose MGR-DEF-0034 as the sole current release blocker.'}
if([string]$developmentState.next_exact_goal.id-cne'MANAGER-41713-TRANSACTION-001'){Fail 'Development state must point at the stranded-input transaction implementation goal.'}
if([bool]$developmentState.next_exact_goal.product_fix_may_start_only_after_state_machine_review){Fail 'Completed state-machine review must no longer block transaction product implementation.'}
if([bool]$developmentState.next_exact_goal.candidate_freeze_permitted){Fail 'Development state must keep candidate freeze blocked.'}
if([bool]$developmentState.next_exact_goal.multi_hub_activation_permitted){Fail 'Development state must keep multi-Hub activation blocked.'}
if(([string]$developmentState.next_exact_goal.description)-match'(?<!\d)10[234](?!\d)'){Fail 'Development next goal must not preserve a magic Entry Reachability scenario count.'}

Write-Host 'MANAGER QUALIFICATION ARCHITECTURE: PASS' -ForegroundColor Green
Write-Host ('  work item: '+[string]$architecture.work_item_id)
Write-Host ('  active transaction goal: '+[string]$developmentState.next_exact_goal.id)
Write-Host ('  scheduler: '+[string]$schedulerContract.implementation)
Write-Host '  Risk Gate: receipt verification only'
Write-Host ('  Entry behavior owner: '+[string]$entry.behavioral_owner)
Write-Host ('  stranded-input contract: '+[string]$transaction.selected_contract.name)
Write-Host ('  transaction properties modeled: '+$propertyIds.Count+' (count is not a release invariant)')
Write-Host ('  open transaction blocker: '+[string]$transaction.open_defect)
Write-Host '  fixed Entry Reachability scenario count: prohibited'
Write-Host '  historical recursive sources: static provenance; active behavior flattened'
exit 0
