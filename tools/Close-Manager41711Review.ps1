[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$Utf8NoBom=New-Object Text.UTF8Encoding($false)

function Fail([string]$Message){throw $Message}
function Read-Json([string]$Relative){Get-Content -LiteralPath (Join-Path $RepositoryRoot $Relative) -Raw -Encoding UTF8|ConvertFrom-Json}
function Write-Json([string]$Relative,$Object){
    $text=(($Object|ConvertTo-Json -Depth 60).Replace("`r`n","`n"))+"`n"
    [IO.File]::WriteAllText((Join-Path $RepositoryRoot $Relative),$text,$Utf8NoBom)
}
function Add-UniqueString($Values,[string]$Value){
    $rows=@($Values|ForEach-Object{[string]$_})
    if($rows-cnotcontains$Value){$rows+=,$Value}
    return @($rows)
}
function Replace-Once([string]$Text,[string]$Old,[string]$New,[string]$Label){
    $first=$Text.IndexOf($Old,[StringComparison]::Ordinal)
    if($first-lt0){Fail($Label+' old text not found.')}
    if($Text.IndexOf($Old,$first+$Old.Length,[StringComparison]::Ordinal)-ge0){Fail($Label+' old text is not unique.')}
    return $Text.Substring(0,$first)+$New+$Text.Substring($first+$Old.Length)
}
function Parse-File([string]$Relative){
    $tokens=$null;$errors=$null
    [void][Management.Automation.Language.Parser]::ParseFile((Join-Path $RepositoryRoot $Relative),[ref]$tokens,[ref]$errors)
    if(@($errors).Count){Fail($Relative+': '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
}
function Invoke-Checked([string]$Relative,[string[]]$Arguments){
    $exe=Join-Path $PSHOME 'powershell.exe'
    & $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $RepositoryRoot $Relative) @Arguments
    if($LASTEXITCODE-ne0){Fail($Relative+' failed with exit '+$LASTEXITCODE)}
}

$expectedBase='89d593b261b4e432fef2f62484cfbf3293ecf4cc'
$head=(git -C $RepositoryRoot rev-parse HEAD).Trim()
$changedSinceBase=@(git -C $RepositoryRoot diff --name-only $expectedBase $head | Sort-Object)
$expectedBootstrap=@('.github/workflows/close-manager-4.17.11-review.yml','tools/Close-Manager41711Review.ps1')|Sort-Object
if([string]::Join("`n",$changedSinceBase)-cne[string]::Join("`n",$expectedBootstrap)){Fail('Unexpected closure bootstrap lineage: '+([string]::Join(', ',@($changedSinceBase))))}

Invoke-Checked 'tools\Verify-ManagerReleaseInstructions.ps1' @('-RepositoryRoot',$RepositoryRoot)
Invoke-Checked 'tools\Invoke-Manager41711ReviewRegression.ps1' @('-RepositoryRoot',$RepositoryRoot)

$defRel='tests\knowledge\defects\manager-4.17.10-postfreeze.json'
$def=Read-Json $defRel
foreach($id in @('MGR-DEF-0024','MGR-DEF-0025')){
    $row=@($def.defects|Where-Object{[string]$_.id-ceq$id})
    if($row.Count-ne1){Fail('Defect record count for '+$id+'='+$row.Count)}
    if([string]$row[0].status-cne'open'){Fail($id+' must still be open before closure.')}
    $row[0].status='fixed'
    $row[0].fixed_in='4.17.11'
    $row[0].planned_regressions=@()
    if($id-ceq'MGR-DEF-0024'){$row[0].permanent_regressions=@('tools/Invoke-Manager41711ReviewRegression.ps1')}
    else{$row[0].permanent_regressions=@('tools/Verify-ManagerReleaseInstructions.ps1')}
    $e=@($row[0].evidence)
    $e+=,[pscustomobject]@{type='review_closure_workflow';id='34769051128';head=$expectedBase}
    $row[0].evidence=@($e)
}
Write-Json $defRel $def

$auditRel='tests\knowledge\audits\post-4.17.10-public-review.json'
$audit=Read-Json $auditRel
if([string]$audit.audit_id-cne'MHA-41710-001'){Fail 'Unexpected 4.17.10 audit identity.'}
$audit.confirmed_open_defects=@()
if($audit.PSObject.Properties.Name-cnotcontains'resolved_defects'){$audit|Add-Member -NotePropertyName resolved_defects -NotePropertyValue @('MGR-DEF-0024')}else{$audit.resolved_defects=@('MGR-DEF-0024')}
$resolution=[pscustomobject]@{status='resolved';manager_version='4.17.11';permanent_regression='tools/Invoke-Manager41711ReviewRegression.ps1';evidence_run_id='34769051128';evidence_head=$expectedBase}
if($audit.PSObject.Properties.Name-cnotcontains'resolution'){$audit|Add-Member -NotePropertyName resolution -NotePropertyValue $resolution}else{$audit.resolution=$resolution}
Write-Json $auditRel $audit

$riskRel='tests\knowledge\risk-map.json'
$risk=Read-Json $riskRel
foreach($sid in @('S-RUNTIME-INBOX','S-RUNTIME-HUB-UPDATE')){
    $surface=@($risk.surfaces|Where-Object{[string]$_.id-ceq$sid})
    if($surface.Count-ne1){Fail('Risk surface count '+$sid+'='+$surface.Count)}
    $surface[0].regressions=Add-UniqueString $surface[0].regressions 'tools/Invoke-Manager41711ReviewRegression.ps1'
}
$ci=@($risk.surfaces|Where-Object{[string]$_.id-ceq'S-CI-DEVELOPMENT'})
if($ci.Count-ne1){Fail('S-CI-DEVELOPMENT count='+$ci.Count)}
$ci[0].paths=Add-UniqueString $ci[0].paths 'tools/Verify-ManagerReleaseInstructions.ps1'
$ci[0].regressions=Add-UniqueString $ci[0].regressions 'tools/Verify-ManagerReleaseInstructions.ps1'
Write-Json $riskRel $risk

$stateRel='MANAGER_DEVELOPMENT_STATE.json'
$state=Read-Json $stateRel
if([string]$state.lifecycle_state-cne'unqualified_development'-or[string]$state.authoritative_branch-cne'dev/manager-4.17.11'){Fail 'Development state is not the expected 4.17.11 successor state.'}
if([string]::Join('|',@($state.open_release_blockers))-cne'MGR-DEF-0024|MGR-DEF-0025'){Fail 'Unexpected pre-closure blocker set.'}
$state.open_release_blockers=@()
$state.qualification.risk_defect_gate.status='required_pass_before_freeze'
$state.qualification.risk_defect_gate.observed_status='pending_exact_head_development_validation_after_review_closure'
$state.qualification.manager_4_17_11.review_closure='pass'
if($state.qualification.manager_4_17_11.PSObject.Properties.Name-cnotcontains'review_closure_run_id'){$state.qualification.manager_4_17_11|Add-Member -NotePropertyName review_closure_run_id -NotePropertyValue '34769051128'}else{$state.qualification.manager_4_17_11.review_closure_run_id='34769051128'}
if($state.qualification.manager_4_17_11.PSObject.Properties.Name-cnotcontains'review_closure_head'){$state.qualification.manager_4_17_11|Add-Member -NotePropertyName review_closure_head -NotePropertyValue $expectedBase}else{$state.qualification.manager_4_17_11.review_closure_head=$expectedBase}
$state.qualification.manager_4_17_11.development_validation='pending'
$state.next_exact_goal.id='MANAGER-41711-DEVELOPMENT-VALIDATION-001'
$state.next_exact_goal.description='Require exact-head canonical Development Validation and strict Risk/Defect Gate PASS with the 4.17.11 review regression and release-instruction identity guard integrated. Do not freeze until both checks pass on the same authoritative development source identity.'
$state.bootstrap.required_first_actions=@(
    'Resolve dev/manager-4.17.11 live; remote branch is authoritative.',
    'Treat production Manager 4.17.10 as installed and accepted only in single-instance compatibility mode; do not activate multi-Hub.',
    'MGR-DEF-0024/MGR-DEF-0025 are fixed in 4.17.11 with permanent pre-freeze coverage; require canonical exact-head Development Validation and Risk/Defect Gate PASS.',
    'Do not freeze 4.17.11 until exact-head development evidence is green.'
)
Write-Json $stateRel $state

$devRel='tools\Invoke-DevelopmentValidation.ps1'
$devPath=Join-Path $RepositoryRoot $devRel
$dev=([IO.File]::ReadAllText($devPath)).Replace("`r`n","`n")
$old="$([char]36)knowledgeTools=@(`n    'tools\Test-ManagerEngineeringKnowledge.ps1',`n    'tools\Build-ManagerRiskContext.ps1',`n    'tools\Invoke-ManagerRiskDefectGate.ps1',`n    'tools\Invoke-ManagerRiskContextRegression.ps1'`n)"
$new="$([char]36)knowledgeTools=@(`n    'tools\Test-ManagerEngineeringKnowledge.ps1',`n    'tools\Build-ManagerRiskContext.ps1',`n    'tools\Invoke-ManagerRiskDefectGate.ps1',`n    'tools\Invoke-ManagerRiskContextRegression.ps1',`n    'tools\Verify-ManagerReleaseInstructions.ps1',`n    'tools\Invoke-Manager41711ReviewRegression.ps1'`n)"
$dev=Replace-Once $dev $old $new 'development parser tool list'
$old="Write-Host '[4/7] Run Manager 4.17.10 regression chain...'`nforeach(`$regressionName in @('Invoke-Manager41710ReviewRegression.ps1')){`n    `$regression=Join-Path `$RepositoryRoot ('tools\'+`$regressionName)`n    if(-not(Test-Path -LiteralPath `$regression -PathType Leaf)){Fail('Manager 4.17.10 regression tool is missing: '+`$regressionName)}`n    Parse-File `$regression`n    Invoke-Child `$regression @('-RepositoryRoot',`$RepositoryRoot)`n}`nWrite-Host 'Manager 4.17.10 regression chain: PASS' -ForegroundColor Green"
$new="Write-Host '[4/7] Run Manager review regression and release-identity chain...'`n`$releaseInstructionGuard=Join-Path `$RepositoryRoot 'tools\Verify-ManagerReleaseInstructions.ps1'`nInvoke-Child `$releaseInstructionGuard @('-RepositoryRoot',`$RepositoryRoot)`nforeach(`$regressionName in @('Invoke-Manager41710ReviewRegression.ps1','Invoke-Manager41711ReviewRegression.ps1')){`n    `$regression=Join-Path `$RepositoryRoot ('tools\'+`$regressionName)`n    if(-not(Test-Path -LiteralPath `$regression -PathType Leaf)){Fail('Manager review regression tool is missing: '+`$regressionName)}`n    Parse-File `$regression`n    Invoke-Child `$regression @('-RepositoryRoot',`$RepositoryRoot)`n}`nWrite-Host 'Manager 4.17.10 + 4.17.11 review regression and release-instruction chain: PASS' -ForegroundColor Green"
$dev=Replace-Once $dev $old $new 'canonical review regression chain'
[IO.File]::WriteAllText($devPath,$dev,$Utf8NoBom)

$wfRel='.github\workflows\development-validation.yml'
$wfPath=Join-Path $RepositoryRoot $wfRel
$wf=([IO.File]::ReadAllText($wfPath)).Replace("`r`n","`n")
$wf=Replace-Once $wf "      - 'tools/Invoke-Manager41710ReviewRegression.ps1'" "      - 'tools/Invoke-Manager41711ReviewRegression.ps1'`n      - 'tools/Verify-ManagerReleaseInstructions.ps1'`n      - 'tools/Invoke-Manager41710ReviewRegression.ps1'" 'Development Validation trigger paths'
$oldComment='# Invoke-DevelopmentValidation.ps1 owns the permanent Manager 4.17.10 regression chain, including real disposable Genesis -> registry activation -> Doctor execution. The workflow does not repeat that expensive chain.'
$newComment='# Invoke-DevelopmentValidation.ps1 owns the permanent Manager 4.17.10 + 4.17.11 regression chain, including real disposable registry-active Doctor and CANDIDATE-only UpdateHub execution plus the managed release-instruction identity guard. The workflow does not repeat that expensive chain.'
$wf=Replace-Once $wf $oldComment $newComment 'Development Validation ownership comment'
[IO.File]::WriteAllText($wfPath,$wf,$Utf8NoBom)

$roadRel='MANAGER_ENGINEERING_ROADMAP.md'
$roadPath=Join-Path $RepositoryRoot $roadRel
$road=([IO.File]::ReadAllText($roadPath)).Replace("`r`n","`n")
$r14="- **Required properties:** current/HEAD source remains fail-closed on parse errors; historical/base parse failure uses an explicit conservative path-level fallback; the fallback is visible in generated risk context; reusable tooling behaviors have permanent regressions; ``PUBLIC_FILE_MANIFEST.json`` is reproducible from the exact source tree; ``PUBLIC_PROVENANCE.json`` must identify the same Manager version, installation digest, managed-set digest, Framework revision and development baseline as the canonical source/state; an unqualified development line must not inherit a predecessor's Full Gate/production acceptance receipt; changes to either metadata file or its verifier trigger ordinary development CI."
$r14new="- **Required properties:** current/HEAD source remains fail-closed on parse errors; historical/base parse failure uses an explicit conservative path-level fallback; the fallback is visible in generated risk context; reusable tooling behaviors have permanent regressions; product materializers must preserve exact source bytes outside intended edits and enforce structural/size/minimal-diff guards before commit; ``PUBLIC_FILE_MANIFEST.json`` is reproducible from the exact source tree; ``PUBLIC_PROVENANCE.json`` must identify the same Manager version, installation digest, managed-set digest, Framework revision and development baseline as the canonical source/state; an unqualified development line must not inherit a predecessor's Full Gate/production acceptance receipt; changes to either metadata file or its verifier trigger ordinary development CI."
$road=Replace-Once $road $r14 $r14new 'R-014 materializer integrity lesson'
if($road.Contains('### R-017 — Runtime state-matrix outcome qualification')){Fail 'R-017 already exists unexpectedly.'}
$r17="### R-017 — Runtime state-matrix outcome qualification`n`n- **Priority:** P1`n- **Status:** ACTIVE`n- **Goal:** move state-dependent runtime defects from post-freeze review into pre-freeze executable qualification by exercising real Manager paths across the relevant state/outcome matrix rather than relying on static/AST reachability alone.`n- **Initial matrix:** single-instance compatibility; registry-active healthy; active metadata invalid; active Hub missing/corrupt; instance-owned pending CANDIDATE; stranded Manager-global Hub input; no-install outcome; Doctor diagnostics; UpdateHub completion reporting.`n- **Required properties:** each state executes the real command path in a disposable sanitized environment; assertions cover both durable mutation and user-visible/diagnostic outcome; static checks remain supplemental; state-specific collectors/routing variables must be initialized and resolved before their first reachable use.`n- **Trigger:** MGR-DEF-0023 escaped all green qualification because registry-active Doctor was not executed; MGR-DEF-0024 then escaped because the registry-active CANDIDATE-only no-install outcome was not executed. The 4.17.11 closure regression adds A21, but the general state matrix must become systematic rather than release-specific.`n- **Dependency:** R-002 executable knowledge, R-003 multi-Hub convergence, and R-014 tooling self-regression.`n- **Exit:** canonical Development Validation/qualification derives or maintains a bounded runtime state matrix and proves all required Doctor/SelfTest/update outcome cells before candidate freeze.`n`n"
$road=Replace-Once $road '## Roadmap maintenance policy' ($r17+'## Roadmap maintenance policy') 'R-017 insertion'
[IO.File]::WriteAllText($roadPath,$road,$Utf8NoBom)

foreach($rel in @(
    '.github\workflows\materialize-manager-4.17.11.yml',
    '.github\workflows\diagnose-manager-4.17.11-runtime.yml',
    '.github\workflows\repair-manager-4.17.11-runtime.yml',
    '.github\workflows\sync-manager-4.17.11-development-metadata.yml',
    '.github\workflows\validate-manager-4.17.11-review.yml',
    'tools\Apply-Manager41711ReleaseReviewFixes.ps1',
    '.github\workflows\close-manager-4.17.11-review.yml',
    'tools\Close-Manager41711Review.ps1'
)){
    $path=Join-Path $RepositoryRoot $rel
    if(Test-Path -LiteralPath $path -PathType Leaf){Remove-Item -LiteralPath $path -Force}
}

if(@(git -C $RepositoryRoot diff --name-only -- manager).Count-ne0){Fail 'Closure integration unexpectedly changes Manager product/source bytes.'}
foreach($rel in @('tools\Invoke-DevelopmentValidation.ps1','tools\Invoke-Manager41711ReviewRegression.ps1','tools\Verify-ManagerReleaseInstructions.ps1')){Parse-File $rel}
Invoke-Checked 'tools\Test-ManagerEngineeringKnowledge.ps1' @('-RepositoryRoot',$RepositoryRoot)
Invoke-Checked 'tools\Build-PublicFileManifest.ps1' @('-RepositoryRoot',$RepositoryRoot,'-Check')
Invoke-Checked 'tools\Verify-PublicCandidateMetadata.ps1' @('-RepositoryRoot',$RepositoryRoot)
Invoke-Checked 'tools\Verify-PublicRepository.ps1' @('-RepositoryRoot',$RepositoryRoot)
& git -C $RepositoryRoot diff --check
if($LASTEXITCODE-ne0){Fail 'git diff --check failed.'}

& git -C $RepositoryRoot add -A
$expected=@(
    '.github/workflows/close-manager-4.17.11-review.yml',
    '.github/workflows/development-validation.yml',
    '.github/workflows/diagnose-manager-4.17.11-runtime.yml',
    '.github/workflows/materialize-manager-4.17.11.yml',
    '.github/workflows/repair-manager-4.17.11-runtime.yml',
    '.github/workflows/sync-manager-4.17.11-development-metadata.yml',
    '.github/workflows/validate-manager-4.17.11-review.yml',
    'MANAGER_DEVELOPMENT_STATE.json',
    'MANAGER_ENGINEERING_ROADMAP.md',
    'tests/knowledge/audits/post-4.17.10-public-review.json',
    'tests/knowledge/defects/manager-4.17.10-postfreeze.json',
    'tests/knowledge/risk-map.json',
    'tools/Apply-Manager41711ReleaseReviewFixes.ps1',
    'tools/Close-Manager41711Review.ps1',
    'tools/Invoke-DevelopmentValidation.ps1'
)|Sort-Object
$actual=@(git -C $RepositoryRoot diff --cached --name-only)|Sort-Object
if([string]::Join("`n",$actual)-cne[string]::Join("`n",$expected)){Fail('Unexpected closure staged set: '+([string]::Join(', ',@($actual))))}

& git -C $RepositoryRoot config user.name 'github-actions[bot]'
& git -C $RepositoryRoot config user.email '41898282+github-actions[bot]@users.noreply.github.com'
& git -C $RepositoryRoot commit -m 'Manager 4.17.11: close post-freeze review blockers'
if($LASTEXITCODE-ne0){Fail 'Closure commit failed.'}
& git -C $RepositoryRoot push origin HEAD:dev/manager-4.17.11
if($LASTEXITCODE-ne0){Fail 'Closure push failed.'}
Write-Host 'Manager 4.17.11 coherent review closure committed and pushed: PASS' -ForegroundColor Green
