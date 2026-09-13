[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$Utf8NoBom=New-Object Text.UTF8Encoding($false)

function Fail([string]$Message){throw $Message}
function Repo([string]$Relative){return Join-Path $RepositoryRoot ($Relative.Replace('/','\'))}
function Read-Json([string]$Relative){return Get-Content -LiteralPath (Repo $Relative) -Raw -Encoding UTF8|ConvertFrom-Json}
function Write-Json([string]$Relative,$Object){
    $text=(($Object|ConvertTo-Json -Depth 80).Replace("`r`n","`n"))+"`n"
    [IO.File]::WriteAllText((Repo $Relative),$text,$Utf8NoBom)
}
function Set-Prop($Object,[string]$Name,$Value){
    if($Object.PSObject.Properties.Name -contains $Name){$Object.$Name=$Value}
    else{$Object|Add-Member -NotePropertyName $Name -NotePropertyValue $Value}
}
function Add-UniqueStrings($Existing,[string[]]$Values){
    $all=@($Existing|ForEach-Object{[string]$_})+@($Values)
    return @($all|Where-Object{-not[string]::IsNullOrWhiteSpace($_)}|Sort-Object -Unique)
}
function Replace-LiteralOnce([string]$Text,[string]$Old,[string]$New,[string]$Label){
    $first=$Text.IndexOf($Old,[StringComparison]::Ordinal)
    if($first-lt0){Fail($Label+' anchor missing.')}
    if($Text.IndexOf($Old,$first+$Old.Length,[StringComparison]::Ordinal)-ge0){Fail($Label+' anchor is ambiguous.')}
    return $Text.Substring(0,$first)+$New+$Text.Substring($first+$Old.Length)
}
function Invoke-Checked([string]$Relative,[string[]]$Arguments=@()){
    $powershell=Join-Path $PSHOME 'powershell.exe'
    & $powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Repo $Relative) @Arguments
    if($LASTEXITCODE-ne0){Fail($Relative+' failed with exit '+$LASTEXITCODE)}
}

$manifest=Read-Json 'PUBLIC_FILE_MANIFEST.json'
if([string]$manifest.manager.version-cne'4.17.12'){Fail 'Expected Manager 4.17.12 public manifest.'}
if([string]$manifest.manager.installation_sha256-cne'f66f83aba661868c6ff5007e77f96b3be8be34536000c060cdd0017dcf553b5d'){Fail 'Unexpected 4.17.12 INSTALLATION identity.'}
if([string]$manifest.manager.gate_managed_content_sha256-cne'64c6cc7bd71742c7dcb50dfc93761d5155095b0604fae2cd4bf20ca16f014b6b'){Fail 'Unexpected 4.17.12 managed-content identity.'}

# Close the post-freeze 4.17.11 findings only with named permanent regressions.
$defects=Read-Json 'tests/knowledge/defects/manager-4.17.11-postfreeze.json'
foreach($d in @($defects.defects)){
    switch([string]$d.id){
        'MGR-DEF-0026' {
            $d.status='fixed';$d.fixed_in='4.17.12'
            $d.permanent_regressions=@('tools/Invoke-Manager41712ReviewRegression.ps1')
            $d.planned_regressions=@()
        }
        'MGR-DEF-0027' {
            $d.status='fixed';$d.fixed_in='4.17.12'
            $d.permanent_regressions=@('tools/Invoke-ManagerRiskContextRegression.ps1')
            $d.planned_regressions=@()
        }
    }
}
Write-Json 'tests/knowledge/defects/manager-4.17.11-postfreeze.json' $defects

# Promote planned regression coverage and map the risk-workflow layer explicitly.
$risk=Read-Json 'tests/knowledge/risk-map.json'
foreach($surface in @($risk.surfaces)){
    if([string]$surface.id-ceq'S-FRONTEND-INSTANCE-CONTEXT'){
        $surface.regressions=Add-UniqueStrings $surface.regressions @('tools/Invoke-Manager41712ReviewRegression.ps1')
        $surface.planned_regressions=@($surface.planned_regressions|Where-Object{[string]$_-cne'tools/Invoke-Manager41712ReviewRegression.ps1'})
        $surface.symbols=Add-UniqueStrings $surface.symbols @('Get-FrontendRegistryRows','Show-HubManagementMenu')
        $surface.state_machine_rules=Add-UniqueStrings $surface.state_machine_rules @('R-ACTIVE-METADATA-INVALID-SWITCH','R-BROKEN-ACTIVE-SWITCH-MISSING','R-BROKEN-ACTIVE-SWITCH-CORRUPT')
    }elseif([string]$surface.id-ceq'S-CI-DEVELOPMENT'){
        $surface.paths=Add-UniqueStrings $surface.paths @('.github/workflows/manager-risk-defect-gate.yml')
        $surface.regressions=Add-UniqueStrings $surface.regressions @('tools/Invoke-ManagerRiskContextRegression.ps1')
        $surface.planned_regressions=@($surface.planned_regressions|Where-Object{[string]$_-cne'tools/Invoke-ManagerRiskContextRegression.ps1'})
    }
}
Write-Json 'tests/knowledge/risk-map.json' $risk

# Harden the dispatch workflow itself. Build-ManagerRiskContext remains the second fail-closed layer.
$riskWorkflowPath=Repo '.github/workflows/manager-risk-defect-gate.yml'
$riskWorkflow=[IO.File]::ReadAllText($riskWorkflowPath,[Text.Encoding]::UTF8)
if(-not$riskWorkflow.Contains('Dispatched checkout identity mismatch')){Fail 'Risk workflow exact-head identity guard is missing.'}
if(-not$riskWorkflow.Contains('Risk qualification range must be non-empty')){
    $outAnchor="          `$out = Join-Path `$env:RUNNER_TEMP ('keelaryn-manager-risk-' + `$env:GITHUB_RUN_ID + '-' + `$env:GITHUB_RUN_ATTEMPT)"
    $guard=@'
          if ($baseResolved -ceq $headResolved) {
            throw 'Risk qualification range must be non-empty: base_commit equals head_commit.'
          }
          & git merge-base --is-ancestor $baseResolved $headResolved
          $ancestorExit = [int]$LASTEXITCODE
          if ($ancestorExit -eq 1) {
            throw "Risk qualification base must be a proper ancestor of head: base=$baseResolved head=$headResolved"
          }
          if ($ancestorExit -ne 0) {
            throw "git merge-base --is-ancestor failed with exit $ancestorExit for base=$baseResolved head=$headResolved"
          }
          $countText = (& git rev-list --count "$baseResolved..$headResolved").Trim()
          if ($LASTEXITCODE -ne 0) { throw 'git rev-list --count failed while validating the risk qualification range.' }
          $count = 0
          if (-not [int]::TryParse($countText,[ref]$count) -or $count -lt 1) {
            throw "Risk qualification range must contain at least one commit: base=$baseResolved head=$headResolved count=$countText"
          }
'@
    $riskWorkflow=Replace-LiteralOnce $riskWorkflow $outAnchor ($guard.TrimEnd()+"`n"+$outAnchor) 'risk workflow range guard'
}
[IO.File]::WriteAllText($riskWorkflowPath,$riskWorkflow,$Utf8NoBom)

# Ensure standalone edits to the 4.17.12 regression trigger Development Validation.
$devWorkflowPath=Repo '.github/workflows/development-validation.yml'
$devWorkflow=[IO.File]::ReadAllText($devWorkflowPath,[Text.Encoding]::UTF8)
$path41712="      - 'tools/Invoke-Manager41712ReviewRegression.ps1'"
if(-not$devWorkflow.Contains($path41712)){
    $anchor="      - 'tools/Invoke-Manager41711ReviewRegression.ps1'"
    if(-not$devWorkflow.Contains($anchor)){Fail 'Development Validation 4.17.11 trigger anchor missing.'}
    $devWorkflow=$devWorkflow.Replace($anchor,$anchor+"`n"+$path41712)
}
$devWorkflow=$devWorkflow.Replace('permanent Manager 4.17.10 + 4.17.11 regression chain','permanent Manager 4.17.10 + 4.17.11 + 4.17.12 regression chain')
[IO.File]::WriteAllText($devWorkflowPath,$devWorkflow,$Utf8NoBom)

# Pin workflow-level range wiring inside the executable permanent risk regression.
$riskRegressionPath=Repo 'tools/Invoke-ManagerRiskContextRegression.ps1'
$riskRegression=[IO.File]::ReadAllText($riskRegressionPath,[Text.Encoding]::UTF8)
if(-not$riskRegression.Contains('workflow exact-head and proper-ancestor range guards are wired')){
    $anchor='$knowledgeSource=Join-Path $RepositoryRoot ''tests\knowledge'''
    $pos=$riskRegression.IndexOf($anchor,[StringComparison]::Ordinal)
    if($pos-lt0){Fail 'Risk regression knowledge-source anchor missing.'}
    $lineEnd=$riskRegression.IndexOf("`n",$pos,[StringComparison]::Ordinal)
    if($lineEnd-lt0){Fail 'Risk regression anchor line ending missing.'}
    $insert=@'
$riskWorkflow=Join-Path $RepositoryRoot '.github\workflows\manager-risk-defect-gate.yml'
if(-not(Test-Path -LiteralPath $riskWorkflow -PathType Leaf)){Fail 'manager-risk-defect-gate.yml is missing.'}
$riskWorkflowText=[IO.File]::ReadAllText($riskWorkflow,[Text.Encoding]::UTF8)
foreach($token in @('Dispatched checkout identity mismatch','Risk qualification range must be non-empty','git merge-base --is-ancestor','git rev-list --count')){
    if(-not$riskWorkflowText.Contains($token)){Fail('Risk workflow lost fail-closed range guard token: '+$token)}
}
if(-not$riskWorkflowText.Contains('Invoke-ManagerRiskDefectGate.ps1')){Fail 'Risk workflow no longer delegates to the strict gate implementation.'}
Write-Host '  PASS workflow exact-head and proper-ancestor range guards are wired' -ForegroundColor Green
'@
    $riskRegression=$riskRegression.Substring(0,$lineEnd+1)+$insert.Trim()+"`n"+$riskRegression.Substring($lineEnd+1)
}
[IO.File]::WriteAllText($riskRegressionPath,$riskRegression,$Utf8NoBom)

# Move durable repository state to unqualified 4.17.12 successor development.
$state=Read-Json 'MANAGER_DEVELOPMENT_STATE.json'
$state.lifecycle_state='unqualified_development'
$state.authoritative_branch='dev/manager-4.17.12'
$state.head_resolution.mode='resolve_branch_ref_live'
$state.head_resolution.note='Resolve dev/manager-4.17.12 live. No 4.17.12 candidate has been issued. Product materialization commit 5e9adce7d210f067dc45729bbbd569b4d8813ad2 is development-only; frozen Manager 4.17.11 g1 remains immutable historical production-installed/public-release-rejected evidence.'
$state.lineage.production_manager_version='4.17.11'
$state.lineage.previous_production_manager_version='4.17.10'
$state.lineage.production_candidate_commit='88e3dcba0af75264c4b53e8ec24d770c215677a0'
$state.lineage.production_candidate_tree='7d23ab245699d63c264958f9132d29fe85d43de7'
$state.lineage.production_managed_digest='a683573f8d0d4f22e58548352ee6219bb2cca482368db43161474881aec6747b'
$state.lineage.production_installation_sha256='cd531baa24836a518afdf582e5313006cdc503fcc212b8b1bcffbb7c55ae2bfc'
$state.lineage.framework_revision='r24'
$state.lineage.successor_manager_version='4.17.12'
$state.materialization=[pscustomobject][ordered]@{
    manager_version='4.17.12'
    product_commit='5e9adce7d210f067dc45729bbbd569b4d8813ad2'
    product_tree='d10953b8f0e643c0ea22a4bcb13b4f4c21d5fafe'
    materialization_run_id='34776567506'
    source_manifest_refresh_commit='9844ff5281da898fa7f77a33f837561e445c0aad'
    installation_sha256='f66f83aba661868c6ff5007e77f96b3be8be34536000c060cdd0017dcf553b5d'
    managed_content_sha256='64c6cc7bd71742c7dcb50dfc93761d5155095b0604fae2cd4bf20ca16f014b6b'
    status='development_materialized_permanent_regressions_pass'
    candidate_issued=$false
}
$state.qualification.risk_defect_gate=[pscustomobject][ordered]@{
    status='required_pass_before_freeze'
    observed_status='not_yet_run_for_exact_4_17_12_converged_head'
    validated_development_head=$null
    candidate_freeze_permitted=$false
    open_release_blockers=@()
}
Set-Prop $state.qualification 'successor_4_17_12_development' ([pscustomobject][ordered]@{
    manager_version='4.17.12'
    lifecycle='unqualified_development'
    candidate_issued=$false
    product_commit='5e9adce7d210f067dc45729bbbd569b4d8813ad2'
    materialization_run_id='34776567506'
    manager_41712_review_regression='pass_during_materialization'
    risk_context_regression='must_pass_in_convergence_validation'
    pre_freeze_adversarial_review='pending'
    production_qualified=$false
})
$state.open_release_blockers=@()
Set-Prop $state.knowledge 'manager_4_17_12_review_regression' 'tools/Invoke-Manager41712ReviewRegression.ps1'
$state.next_exact_goal=[pscustomobject][ordered]@{
    id='MANAGER-41712-PREFREEZE-CONVERGENCE-001'
    description='Require exact-head Development Validation PASS and strict proper-ancestor Risk/Defect Gate PASS, then perform a full PR-equivalent adversarial review of the exact 4.17.12 development head and full successor diff. Fix every finding within unqualified 4.17.12 and repeat until clean before any candidate freeze.'
    candidate_freeze_before_clean_adversarial_review=$false
    product_changes_permitted_on_frozen_4_17_11_g1=$false
}
$state.bootstrap.ordinary_new_chat_instruction='Continue unqualified Manager 4.17.12 convergence development; do not issue a candidate until exact-head validation, strict risk gate and pre-freeze adversarial review are all clean.'
$state.bootstrap.required_first_actions=@(
    'Preserve Manager 4.17.11 g1 commit 88e3dcba0af75264c4b53e8ec24d770c215677a0 / tree 7d23ab245699d63c264958f9132d29fe85d43de7 as immutable production-installed rejected evidence.',
    'Treat Manager 4.17.12 as unqualified development; product materialization and permanent regression PASS do not issue or qualify a candidate.',
    'Require a non-empty proper-ancestor risk range and exact-head identity before any freeze permission.',
    'Perform PR-equivalent adversarial review before freeze, including recovery reachability, routing, update handoff, commit outcomes, release identity and regression reachability.',
    'Do not activate multi-Hub before a successor is fully qualified, installed, publicly released, and activation is separately approved.'
)
Write-Json 'MANAGER_DEVELOPMENT_STATE.json' $state

# Bind public provenance to 4.17.12 development bytes without inheriting 4.17.11 qualification claims.
$prov=Read-Json 'PUBLIC_PROVENANCE.json'
$prov.source_manager_version='4.17.12'
$prov.source_gate_baseline_manager_version='4.17.11'
$prov.source_manager_installation_sha256=[string]$manifest.manager.installation_sha256
$prov.source_manager_gate_managed_content_sha256=[string]$manifest.manager.gate_managed_content_sha256
$prov.production_validation.full_gate_pass=$false
$prov.production_validation.gate_revision=$null
$prov.production_validation.framework_revision=24
$prov.production_validation.tested_update_sha256=$null
$prov.production_validation.production_doctor_pass=$false
$prov.production_validation.production_ux_smoke_pass=$false
$prov.production_validation.production_managed_content_prefix=$null
$prov.gate_framework.frozen_for_manager_candidate=$false
Set-Prop $prov 'development_status' 'unqualified_manager_4_17_12_no_candidate_issued'
Set-Prop $prov 'public_candidate_revision_note' 'Revision 20 is inherited repository metadata; no 4.17.12 candidate revision is assigned until candidate issue/freeze.'
Write-Json 'PUBLIC_PROVENANCE.json' $prov

# Validate every durable relationship before the caller is allowed to commit.
Invoke-Checked 'tools/Test-ManagerEngineeringKnowledge.ps1' @('-RepositoryRoot',$RepositoryRoot)
Invoke-Checked 'tools/Verify-ManagerReleaseInstructions.ps1' @('-RepositoryRoot',$RepositoryRoot)
Invoke-Checked 'tools/Verify-PublicCandidateMetadata.ps1' @('-RepositoryRoot',$RepositoryRoot)
Invoke-Checked 'tools/Verify-PublicRepository.ps1' @('-RepositoryRoot',$RepositoryRoot)
Invoke-Checked 'tools/Invoke-ManagerRiskContextRegression.ps1' @('-RepositoryRoot',$RepositoryRoot)
Invoke-Checked 'tools/Invoke-Manager41712ReviewRegression.ps1' @('-RepositoryRoot',$RepositoryRoot)
Invoke-Checked 'tools/Build-PublicFileManifest.ps1' @('-RepositoryRoot',$RepositoryRoot,'-Check')

Write-Host 'MANAGER 4.17.12 DEVELOPMENT STATE CONVERGENCE: PASS' -ForegroundColor Green
