[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RepositoryRoot,
    [Parameter(Mandatory=$true)][string]$ExpectedBase,
    [Parameter(Mandatory=$true)][string]$MaterializationRunId
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$utf8=New-Object Text.UTF8Encoding($false)

function Write-Utf8([string]$Path,[string]$Text){[IO.File]::WriteAllText($Path,$Text,$utf8)}
function Write-Json([string]$Path,$Object){Write-Utf8 $Path ((($Object|ConvertTo-Json -Depth 50).Replace("`r`n","`n"))+"`n")}
function Replace-ExactlyOnce([string]$Text,[string]$Old,[string]$New,[string]$Label){
    $first=$Text.IndexOf($Old,[StringComparison]::Ordinal)
    if($first-lt0){throw "${Label}: source token not found"}
    if($Text.IndexOf($Old,$first+$Old.Length,[StringComparison]::Ordinal)-ge0){throw "${Label}: source token occurs more than once"}
    return $Text.Substring(0,$first)+$New+$Text.Substring($first+$Old.Length)
}
function Invoke-Checked([string]$Script,[string[]]$Arguments){
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Script @Arguments
    if($LASTEXITCODE-ne0){throw ('Command failed: '+$Script+' '+($Arguments-join' '))}
}

$actual=(git -C $RepositoryRoot rev-parse HEAD).Trim().ToLowerInvariant()
if($actual-cne$ExpectedBase.ToLowerInvariant()){throw "Target branch moved unexpectedly. expected=$ExpectedBase actual=$actual"}
if(git -C $RepositoryRoot status --porcelain){throw 'Target worktree is not clean before materialization.'}

git -C $RepositoryRoot config user.name 'Aleksei Efremov'
git -C $RepositoryRoot config user.email 'efremov.aleksei.96@gmail.com'

# Runtime: version + explicit policy for whether old-active compatibility-shadow reconciliation is semantically required.
$runtimePath=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1'
$runtime=[IO.File]::ReadAllText($runtimePath,[Text.Encoding]::UTF8)
$runtime=Replace-ExactlyOnce $runtime '$ManagerVersion = "4.17.12"' '$ManagerVersion = "4.17.13"' 'runtime version'
$oldAllow='$allowRegistryUnresolved=$Doctor-or$SelfTest-or$BuildDistribution-or$BuildRelease-or$BuildAIContext-or$UpdateManager-or$InitializeInstanceRegistry-or$ListInstances-or$SwitchInstanceId-or$BindInstancePath-or$FinalizeFilesystemLayout'
$newAllow='$allowRegistryUnresolved=$Doctor-or$SelfTest-or$BuildDistribution-or$BuildRelease-or$BuildAIContext-or$UpdateManager-or$InitializeInstanceRegistry-or$ListInstances-or$SwitchInstanceId-or$BindInstancePath-or$FinalizeFilesystemLayout-or$InitializePresentation-or$PrepareTests'
$runtime=Replace-ExactlyOnce $runtime $oldAllow $newAllow 'registry unresolved action policy'
$nl=if($runtime.Contains("`r`n")){"`r`n"}else{"`n"}
$oldGuard=[string]::Join($nl,@(
    'if($script:InstanceRegistryActive -and -not$Doctor){',
    '    Acquire-ManagerLock',
    '    try{$null=Invoke-ReconcileActiveCompatibilityShadow}',
    '    finally{Release-ManagerLock}',
    '}'
))
$newGuard=[string]::Join($nl,@(
    'function Test-ActiveCompatibilityShadowReconciliationRequired {',
    '    if(-not$script:InstanceRegistryActive){return $false}',
    '    # Diagnostic, target-driven recovery, and Manager-global actions must not depend on',
    '    # or mutate the previously active Hub compatibility shadow before their own dispatch.',
    '    if($Doctor-or$ListInstances-or$SwitchInstanceId-or$BindInstancePath-or$UpdateManager-or$BuildDistribution-or$BuildRelease-or$BuildAIContext-or$FinalizeFilesystemLayout-or$InitializePresentation-or$PrepareTests){return $false}',
    '    return $true',
    '}',
    '',
    'if(Test-ActiveCompatibilityShadowReconciliationRequired){',
    '    Acquire-ManagerLock',
    '    try{$null=Invoke-ReconcileActiveCompatibilityShadow}',
    '    finally{Release-ManagerLock}',
    '}'
))
$runtime=Replace-ExactlyOnce $runtime $oldGuard $newGuard 'pre-dispatch compatibility reconciliation guard'
Write-Utf8 $runtimePath $runtime

# Canonical Manager version markers.
foreach($relative in @('manager\product\install\INSTALLATION.json','manager\product\manager_release.json')){
    $path=Join-Path $RepositoryRoot $relative
    $doc=Get-Content -LiteralPath $path -Raw -Encoding UTF8|ConvertFrom-Json
    if([string]$doc.manager_version-cne'4.17.12'){throw "$relative manager_version is not 4.17.12"}
    $doc.manager_version='4.17.13'
    Write-Json $path $doc
}

# Managed README: preserve historical 4.17.12 text, add current corrective context, and bind transition sections exactly.
$readmePath=Join-Path $RepositoryRoot 'manager\README_FIRST.md'
$readme=[IO.File]::ReadAllText($readmePath,[Text.Encoding]::UTF8)
$introPattern='(?s)\A# Keelaryn Manager 4\.17\.12\r?\n(?<old>Manager 4\.17\.12[^\r\n]*)\r?\n\r?\n## 4\.17\.11 context'
$m=[regex]::Match($readme,$introPattern)
if(-not$m.Success){throw 'README 4.17.12 intro contract not found.'}
$intro="# Keelaryn Manager 4.17.13${nl}Manager 4.17.13 is the corrective successor to the production-installed but public-release-rejected Manager 4.17.12. It keeps target-driven Switch/Bind recovery and registry diagnostics reachable even when the previously active compatibility CURRENT shadow is missing or unusable, and prevents Manager-global build/setup/update actions from depending on that Hub shadow. Hub-bound operations still reconcile or fail closed against captured active context. Production multi-Hub remains disabled until this successor completes qualification, installation, public release, and separate activation approval.${nl}${nl}## 4.17.12 context${nl}$($m.Groups['old'].Value)${nl}${nl}## 4.17.11 context"
$readme=$intro+$readme.Substring($m.Index+$m.Length)
$updateSection=[string]::Join($nl,@(
    '## Update compatibility','',
    'Manager 4.17.13 preserves the native update compatibility floor in `product/manager_release.json` and the established UPDATE transition envelope. The normal production qualification transition for this corrective candidate is production-installed Manager 4.17.12 -> 4.17.13.','',
    'Manager-only update commands continue to distinguish "no newer valid package" from failure and do not silently process Hub updates. Installing Manager 4.17.13 alone must not change canonical Hub content.',''
))
$readme=[regex]::Replace($readme,'(?ms)^## Update compatibility\s*\r?\n.*?(?=^## User interface compatibility)',$updateSection,1)
$releaseSection=[string]::Join($nl,@(
    '## Release gate','',
    'This source is not production-approved merely because it carries version 4.17.13. Production approval requires the applicable Windows PowerShell parser/static checks, inherited and 4.17.13 regressions, Manager/frontend SelfTests, deterministic SOURCE/DISTRIBUTION/UPDATE/AI_CONTEXT checks, disposable 4.17.12 -> 4.17.13 update and rollback/fault-injection coverage, Doctor/migration/UI/Genesis coverage, production Hub immutability, exact tested/public-source/release UPDATE identity, real CURRENT-backed Full Gate and gated publication. The consolidated gate uses qualified Gate Framework r24.',''
))
$readme=[regex]::Replace($readme,'(?ms)^## Release gate\s*\r?\n.*\z',$releaseSection,1)
Write-Utf8 $readmePath $readme

# Permanent regression: inherit 4.17.12 coverage and test the pre-dispatch policy itself dynamically.
$regressionPath=Join-Path $RepositoryRoot 'tools\Invoke-Manager41713ReviewRegression.ps1'
$regression=@'
[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
function Fail([string]$Message){throw $Message}
function Parse-OneFunction([string]$Path,[string]$Name){
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){Fail('Parser failed: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
    $rows=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]},$true)|Where-Object{$_.Name-ceq$Name})
    if($rows.Count-ne1){Fail('Function '+$Name+' count='+$rows.Count)}
    return [string]$rows[0].Extent.Text
}
$previous=Join-Path $RepositoryRoot 'tools\Invoke-Manager41712ReviewRegression.ps1'
& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $previous -RepositoryRoot $RepositoryRoot
if($LASTEXITCODE-ne0){Fail 'Inherited Manager 4.17.12 review regression failed.'}
$install=Get-Content -LiteralPath (Join-Path $RepositoryRoot 'manager\product\install\INSTALLATION.json') -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$install.manager_version-cne'4.17.13'){Fail('Expected Manager 4.17.13; actual='+[string]$install.manager_version)}
$runtimePath=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1'
$runtime=[IO.File]::ReadAllText($runtimePath,[Text.Encoding]::UTF8)
$helperText=Parse-OneFunction $runtimePath 'Test-ActiveCompatibilityShadowReconciliationRequired'
Invoke-Expression $helperText
$names=@('Doctor','ListInstances','SwitchInstanceId','BindInstancePath','UpdateManager','BuildDistribution','BuildRelease','BuildAIContext','FinalizeFilesystemLayout','InitializePresentation','PrepareTests','UpdateHub','UpdateAll','RepairCurrentTransport','BuildCandidateTransport','RestoreCandidateTransport')
function Reset-Flags {
    foreach($name in $names){Set-Variable -Name $name -Value $false -Scope Script}
    $script:SwitchInstanceId=$null;$script:BindInstancePath=$null
    $script:InstanceRegistryActive=$true
}
foreach($name in @('Doctor','ListInstances','UpdateManager','BuildDistribution','BuildRelease','BuildAIContext','FinalizeFilesystemLayout','InitializePresentation','PrepareTests')){
    Reset-Flags;Set-Variable -Name $name -Value $true -Scope Script
    if(Test-ActiveCompatibilityShadowReconciliationRequired){Fail('Manager-global/diagnostic action still requires compatibility reconciliation: '+$name)}
}
Reset-Flags;$script:SwitchInstanceId='11111111-1111-1111-1111-111111111111'
if(Test-ActiveCompatibilityShadowReconciliationRequired){Fail 'SwitchInstanceId recovery is still blocked by old-active compatibility reconciliation.'}
Reset-Flags;$script:BindInstancePath='C:\healthy-target'
if(Test-ActiveCompatibilityShadowReconciliationRequired){Fail 'BindInstancePath recovery is still blocked by old-active compatibility reconciliation.'}
foreach($name in @('UpdateHub','UpdateAll','RepairCurrentTransport','BuildCandidateTransport','RestoreCandidateTransport')){
    Reset-Flags;Set-Variable -Name $name -Value $true -Scope Script
    if(-not(Test-ActiveCompatibilityShadowReconciliationRequired)){Fail('Hub-bound action unexpectedly bypasses compatibility reconciliation: '+$name)}
}
Reset-Flags
if(-not(Test-ActiveCompatibilityShadowReconciliationRequired)){Fail 'Default active-context operation unexpectedly bypasses reconciliation.'}
$script:InstanceRegistryActive=$false
if(Test-ActiveCompatibilityShadowReconciliationRequired){Fail 'Single-instance mode unexpectedly requests registry compatibility reconciliation.'}
if($runtime.Contains('if($script:InstanceRegistryActive -and -not$Doctor)')){Fail 'Legacy unconditional pre-dispatch reconciliation guard remains.'}
if(-not$runtime.Contains('if(Test-ActiveCompatibilityShadowReconciliationRequired)')){Fail 'Runtime does not use the centralized reconciliation policy helper.'}
$allowLine=[regex]::Match($runtime,'(?m)^\s*\$allowRegistryUnresolved=.*$').Value
foreach($token in @('$ListInstances','$SwitchInstanceId','$BindInstancePath','$UpdateManager','$BuildDistribution','$BuildRelease','$BuildAIContext','$FinalizeFilesystemLayout','$InitializePresentation','$PrepareTests')){
    if(-not$allowLine.Contains($token)){Fail('Unresolved-registry policy omits Manager-global/recovery action: '+$token)}
}
Write-Host 'MANAGER 4.17.13 REVIEW REGRESSION: PASS' -ForegroundColor Green
'@
Write-Utf8 $regressionPath (($regression.TrimEnd())+"`n")

# Development CI must parse and execute the new regression.
$devValidationPath=Join-Path $RepositoryRoot 'tools\Invoke-DevelopmentValidation.ps1'
$dev=[IO.File]::ReadAllText($devValidationPath,[Text.Encoding]::UTF8)
$dev=Replace-ExactlyOnce $dev "    'tools\Invoke-Manager41712ReviewRegression.ps1'" "    'tools\Invoke-Manager41712ReviewRegression.ps1',${nl}    'tools\Invoke-Manager41713ReviewRegression.ps1'" 'development parser regression list'
$oldLoop="foreach(`$regressionName in @('Invoke-Manager41710ReviewRegression.ps1','Invoke-Manager41711ReviewRegression.ps1','Invoke-Manager41712ReviewRegression.ps1'))"
$newLoop="foreach(`$regressionName in @('Invoke-Manager41710ReviewRegression.ps1','Invoke-Manager41711ReviewRegression.ps1','Invoke-Manager41712ReviewRegression.ps1','Invoke-Manager41713ReviewRegression.ps1'))"
$dev=Replace-ExactlyOnce $dev $oldLoop $newLoop 'development review regression loop'
$dev=Replace-ExactlyOnce $dev 'Manager 4.17.10 + 4.17.11 + 4.17.12 review regression and release-instruction chain: PASS' 'Manager 4.17.10 + 4.17.11 + 4.17.12 + 4.17.13 review regression and release-instruction chain: PASS' 'development review regression status text'
Write-Utf8 $devValidationPath $dev

# Risk map + canonical defect history.
$riskPath=Join-Path $RepositoryRoot 'tests\knowledge\risk-map.json'
$risk=Get-Content -LiteralPath $riskPath -Raw -Encoding UTF8|ConvertFrom-Json
$surface=@($risk.surfaces|Where-Object{[string]$_.id-ceq'S-RUNTIME-REGISTRY-RESOLUTION'})
if($surface.Count-ne1){throw 'Registry-resolution risk surface missing or ambiguous.'}
if(@($surface[0].regressions)-notcontains'tools/Invoke-Manager41713ReviewRegression.ps1'){$surface[0].regressions=@($surface[0].regressions)+@('tools/Invoke-Manager41713ReviewRegression.ps1')}
Write-Json $riskPath $risk
$defectPath=Join-Path $RepositoryRoot 'tests\knowledge\defects\manager-4.17.12-postfreeze.json'
$defect=[ordered]@{
    schema='keelaryn.manager-defects.v1'
    scope='Post-freeze public-release review findings for Manager 4.17.12'
    defects=@(
        [ordered]@{
            id='MGR-DEF-0030'
            title='Pre-dispatch compatibility-shadow reconciliation blocks target-driven recovery before action dispatch'
            severity='P1'
            status='fixed'
            release_blocker=$true
            detected_in='4.17.12'
            detected_stage='public_release_pr_review'
            defect_class='recovery reachability / startup action ordering'
            affected_surfaces=@('S-RUNTIME-REGISTRY-RESOLUTION')
            preconditions='The multi-Hub registry and active selection resolve to a structurally valid active Hub identity, but both the active per-instance CURRENT and legacy compatibility CURRENT are missing, damaged, or otherwise invalid; a healthy registered target is available for SwitchInstanceId or BindInstancePath recovery.'
            bad_behavior='Top-level startup marks the registry active, then invokes compatibility-shadow reconciliation before dispatch. Reconciliation throws when neither CURRENT can be trusted, so target-driven SwitchInstanceId/BindInstancePath never reaches requested-target validation/commit. The same unconditional startup dependency blocks registry listing and Manager-global actions that do not require active Hub CURRENT.'
            root_cause='Compatibility-shadow reconciliation was keyed only to InstanceRegistryActive and Doctor, rather than to whether the requested action actually depends on the previously active Hub compatibility shadow. This placed old-active repair ahead of target-driven recovery and Manager-global/diagnostic dispatch.'
            root_cause_classes=@('RC-RECOVERY-001')
            violated_invariants=@('MH-RECOVERY-001')
            related_defects=@('MGR-DEF-0026')
            permanent_regressions=@('tools/Invoke-Manager41713ReviewRegression.ps1')
            planned_regressions=@()
            fixed_in='4.17.13'
            evidence=@(
                [ordered]@{type='public_release_pr';id='61'},
                [ordered]@{type='pr_review_thread';id='4002869913'},
                [ordered]@{type='windows_confirmation_run';id='34816733121'},
                [ordered]@{type='runtime_source_symbol';id='Resolve-RegisteredInstanceContextEarly'},
                [ordered]@{type='runtime_source_symbol';id='Invoke-ReconcileActiveCompatibilityShadow'}
            )
        }
    )
}
Write-Json $defectPath $defect

# Refresh managed-source identities after product changes.
Invoke-Checked (Join-Path $RepositoryRoot 'tools\Build-PublicFileManifest.ps1') @('-RepositoryRoot',$RepositoryRoot,'-Write')

# Product sanity before any commit.
Invoke-Checked $regressionPath @('-RepositoryRoot',$RepositoryRoot)
Invoke-Checked $runtimePath @('-SelfTest')

$productPaths=@(
    'manager/product/runtime/Keelaryn__Manager.ps1',
    'manager/product/install/INSTALLATION.json',
    'manager/product/manager_release.json',
    'manager/README_FIRST.md',
    'PUBLIC_FILE_MANIFEST.json',
    'tools/Invoke-Manager41713ReviewRegression.ps1',
    'tools/Invoke-DevelopmentValidation.ps1',
    'tests/knowledge/risk-map.json',
    'tests/knowledge/defects/manager-4.17.12-postfreeze.json'
)
git -C $RepositoryRoot add -- $productPaths
git -C $RepositoryRoot commit -m 'Manager 4.17.13: preserve target-driven recovery before shadow reconciliation'
$productCommit=(git -C $RepositoryRoot rev-parse HEAD).Trim().ToLowerInvariant()
$productTree=(git -C $RepositoryRoot rev-parse 'HEAD^{tree}').Trim().ToLowerInvariant()
$manifest=Get-Content -LiteralPath (Join-Path $RepositoryRoot 'PUBLIC_FILE_MANIFEST.json') -Raw -Encoding UTF8|ConvertFrom-Json
$installSha=[string]$manifest.manager.installation_sha256
$managedSha=[string]$manifest.manager.gate_managed_content_sha256

# Current development state: production remains 4.17.12, rejected only for public release; 4.17.13 is not qualified or issued.
$state=[ordered]@{
    schema='keelaryn.manager-development-state.v1'
    repository='efremov-aleksei-96/keelaryn'
    lifecycle_state='unqualified_development'
    authoritative_branch='dev/manager-4.17.13'
    head_resolution=[ordered]@{mode='resolve_branch_ref_live';note='Resolve dev/manager-4.17.13 live. Manager 4.17.12 g1 remains immutable at 3dde367f1bd83f661bd29c75912732e9f92efa02 and is production-installed/accepted but public-release rejected by confirmed MGR-DEF-0030. No 4.17.13 candidate has been issued.'}
    lineage=[ordered]@{
        production_manager_version='4.17.12';previous_production_manager_version='4.17.11';production_candidate_revision='g1';production_candidate_commit='3dde367f1bd83f661bd29c75912732e9f92efa02';production_candidate_tree='63e42a5bfdd6000ee273f5f927902f6ac29703b6';production_managed_digest='5118a866aa54ed916bb087fe41a4ac724bf527181b79b1c34e9b29311bf10fb8';production_installation_sha256='f66f83aba661868c6ff5007e77f96b3be8be34536000c060cdd0017dcf553b5d';framework_revision='r24';source_gate_baseline_manager_version='4.17.12';successor_manager_version='4.17.13'
    }
    materialization=[ordered]@{manager_version='4.17.13';product_commit=$productCommit;product_tree=$productTree;materialization_run_id=$MaterializationRunId;source_manifest_refresh_commit=$productCommit;installation_sha256=$installSha;managed_content_sha256=$managedSha;status='development_materialized_mgr_def_0030_fixed_regression_pass';candidate_issued=$false}
    qualification=[ordered]@{
        risk_defect_gate=[ordered]@{status='required_pass_before_freeze';observed_status='not_run_after_4_17_13_materialization';validated_development_head=$null;candidate_freeze_permitted=$false;open_release_blockers=@()}
        candidate_4_17_12_g1=[ordered]@{
            manager_version='4.17.12';candidate_revision='g1';status='frozen_production_qualified_public_release_rejected';commit='3dde367f1bd83f661bd29c75912732e9f92efa02';tree='63e42a5bfdd6000ee273f5f927902f6ac29703b6';parent='9c639cc954fef5e8a17966c43636c3d86b93a6a7';immutable=$true;product_bytes_changed_after_freeze=$false;installation_sha256='f66f83aba661868c6ff5007e77f96b3be8be34536000c060cdd0017dcf553b5d';managed_content_sha256='5118a866aa54ed916bb087fe41a4ac724bf527181b79b1c34e9b29311bf10fb8';framework_revision=24
            deterministic_tested_update=[ordered]@{sha256='1fb11a51f144e66142f14e48a9bf88c98c9655e0061c5199477b72fdaf4cedb5';bytes=240482}
            production_install=[ordered]@{status='pass';baseline_manager_version='4.17.11';installed_manager_version='4.17.12';doctor='clean_pass';multi_hub_registry_active=$false}
            production_post_install_acceptance=[ordered]@{status='pass';production_hub_immutability='pass';production_current_immutability='pass';multi_hub_registry_active=$false}
            final_public_review=[ordered]@{status='failed';pull_request=61;open_blockers=1;release_blockers=@('MGR-DEF-0030');review_thread_comment_id='4002869913';confirmation_run_id='34816733121';post_freeze_product_drift=$false;prior_publication_only_review='pass_before_pr_review_finding';decision='public_release_rejected'}
        }
        successor_4_17_13_development=[ordered]@{manager_version='4.17.13';lifecycle='unqualified_development';candidate_issued=$false;product_commit=$productCommit;materialization_run_id=$MaterializationRunId;manager_41713_review_regression='pass_at_materialization';production_qualified=$false}
    }
    production_policy=[ordered]@{production_manager='4.17.12_installed_and_accepted_public_release_rejected';production_rollback='not_required_while_multi_hub_inactive';multi_hub='disabled_until_Manager_4_17_13_is_fully_qualified_installed_public_released_and_activation_is_explicitly_requested';production_hub_mutation_from_manager_development='forbidden';candidate_4_17_12_g1='immutable_production_installed_public_release_rejected_do_not_modify'}
    open_release_blockers=@()
    knowledge=[ordered]@{
        roadmap='MANAGER_ENGINEERING_ROADMAP.md';hub_relay_research='HUB_RELAY_RESEARCH.md';knowledge_root='tests/knowledge';current_risk_audits=@('MHA-4179-001','MHA-41710-001');strict_pre_freeze_gate='tools/Invoke-ManagerRiskDefectGate.ps1';risk_context_regression='tools/Invoke-ManagerRiskContextRegression.ps1';manager_4_17_11_review_regression='tools/Invoke-Manager41711ReviewRegression.ps1';manager_4_17_12_review_regression='tools/Invoke-Manager41712ReviewRegression.ps1';manager_4_17_13_review_regression='tools/Invoke-Manager41713ReviewRegression.ps1';release_instruction_identity_guard='tools/Verify-ManagerReleaseInstructions.ps1';public_manifest_reproducibility='tools/Build-PublicFileManifest.ps1 -Check';public_candidate_metadata_verifier='tools/Verify-PublicCandidateMetadata.ps1';public_repository_verifier='tools/Verify-PublicRepository.ps1'
    }
    next_exact_goal=[ordered]@{id='MANAGER-41713-PREFREEZE-CONVERGENCE-001';description='Run exact-head Development Validation and full-successor Risk/Defect Gate over the complete 4.17.12 rejected baseline -> 4.17.13 head, then repeat PR-equivalent adversarial review of startup/recovery/global action ordering before any candidate freeze.';candidate_freeze_before_clean_adversarial_review=$false;product_changes_permitted_on_frozen_4_17_12_g1=$false}
    bootstrap=[ordered]@{ordinary_new_chat_instruction='Continue unqualified Manager 4.17.13 convergence development from the exact remote dev/manager-4.17.13 head; do not issue a candidate until exact-head validation, full-successor risk gate and pre-freeze adversarial review are all clean.';required_first_actions=@('Preserve Manager 4.17.12 g1 as immutable production-installed/public-release-rejected evidence.','Treat MGR-DEF-0030 as fixed only if the permanent 4.17.13 startup-boundary regression remains green.','Verify recovery actions bypass old-active shadow reconciliation while Hub-bound active-context actions remain fail-closed.','Do not activate multi-Hub before 4.17.13 is fully qualified, installed, publicly released, and activation is separately approved.')}
}
Write-Json (Join-Path $RepositoryRoot 'MANAGER_DEVELOPMENT_STATE.json') $state

$provenance=[ordered]@{
    schema='keelaryn.public-repository-provenance.v2'
    role='public_source_sync_candidate'
    source_manager_version='4.17.13'
    source_gate_baseline_manager_version='4.17.12'
    source_manager_installation_sha256=$installSha
    source_manager_gate_managed_content_sha256=$managedSha
    production_validation=[ordered]@{full_gate_pass=$false;gate_revision=$null;framework_revision=24;tested_update_sha256=$null;production_doctor_pass=$false;production_ux_smoke_pass=$false;production_managed_content_prefix=$null}
    publication_rejection=[ordered]@{manager_version='4.17.12';status='rejected_post_freeze_public_review';pull_request=61;frozen_candidate_commit='3dde367f1bd83f661bd29c75912732e9f92efa02';frozen_candidate_tree='63e42a5bfdd6000ee273f5f927902f6ac29703b6';frozen_candidate_changed=$false;release_blockers=@('MGR-DEF-0030');production_install_status='installed_and_post_install_accepted';rollback_required=$false;multi_hub_activated=$false;review_thread_comment_id='4002869913';confirmation_run_id='34816733121'}
    predecessor_publication_rejection=[ordered]@{manager_version='4.17.11';status='rejected_post_freeze_public_review';pull_request=60;frozen_candidate_commit='88e3dcba0af75264c4b53e8ec24d770c215677a0';frozen_candidate_tree='7d23ab245699d63c264958f9132d29fe85d43de7';frozen_candidate_changed=$false;release_blockers=@('MGR-DEF-0026','MGR-DEF-0027');production_install_status='installed_and_post_install_accepted';rollback_required=$false;multi_hub_activated=$false}
    personal_hub_included=$false
    manager_runtime_state_included=$false
    local_test_evidence_included=$false
    gate_framework=[ordered]@{version='2.0';revision=24;windows_qualified=$true;frozen_for_manager_candidate=$false}
    license=[ordered]@{spdx_id='MIT';file='LICENSE';copyright='Copyright (c) 2026 Keelaryn contributors'}
    public_candidate_revision=20
    git_checkout_contract=[ordered]@{manager_authoritative_tree_attribute='-text';framework_authoritative_tree_attribute='-text';core_autocrlf_true_roundtrip_required=$true}
    known_nonsecret_source_hygiene_notes=@('manager/product/docs/TESTING.md retains a maintainer-local D:\0\0__Core example for historical/maintainer qualification context; it is not a product installation default.')
    ci_policy=[ordered]@{github_actions='pull_request + main push + manual';hosted_scope='repository verification + Hub-blind SourceGate + hosted disposable Full Gate + Generic DISTRIBUTION smoke';full_gate='CURRENT-backed Windows Full Gate plus production Doctor, production UX smoke and Hub immutability before publication';update_identity='when full_gate_pass=true, PR and main BuildRelease UPDATE SHA-256 must equal production_validation.tested_update_sha256; publish consumes those gated bytes'}
    known_nonsecret_hygiene_notes=@('manager/product/docs/TESTING.md retains a maintainer-local D:\0\0__Core example; it is not a product default.')
    development_status='unqualified_manager_4_17_13_mgr_def_0030_fixed_validation_required'
    public_candidate_revision_note='Revision 20 is inherited repository metadata; no 4.17.13 candidate revision is assigned until candidate issue/freeze.'
}
Write-Json (Join-Path $RepositoryRoot 'PUBLIC_PROVENANCE.json') $provenance

# Exact materialized metadata/source sanity before second commit.
foreach($relative in @('tools\Test-ManagerEngineeringKnowledge.ps1','tools\Verify-ManagerReleaseInstructions.ps1','tools\Verify-PublicCandidateMetadata.ps1','tools\Verify-PublicRepository.ps1')){
    Invoke-Checked (Join-Path $RepositoryRoot $relative) @('-RepositoryRoot',$RepositoryRoot)
}
Invoke-Checked (Join-Path $RepositoryRoot 'tools\Build-PublicFileManifest.ps1') @('-RepositoryRoot',$RepositoryRoot,'-Check')
Invoke-Checked $regressionPath @('-RepositoryRoot',$RepositoryRoot)

git -C $RepositoryRoot add -- MANAGER_DEVELOPMENT_STATE.json PUBLIC_PROVENANCE.json
git -C $RepositoryRoot commit -m 'Manager 4.17.13: record rejected 4.17.12 provenance and development state'
$final=(git -C $RepositoryRoot rev-parse HEAD).Trim().ToLowerInvariant()
if(git -C $RepositoryRoot status --porcelain){throw 'Materialization left a dirty worktree.'}
Write-Host ('PRODUCT_COMMIT='+$productCommit) -ForegroundColor Green
Write-Host ('PRODUCT_TREE='+$productTree) -ForegroundColor Green
Write-Host ('MATERIALIZED_HEAD='+$final) -ForegroundColor Green
Write-Host ('INSTALLATION_SHA256='+$installSha)
Write-Host ('MANAGED_CONTENT_SHA256='+$managedSha)
