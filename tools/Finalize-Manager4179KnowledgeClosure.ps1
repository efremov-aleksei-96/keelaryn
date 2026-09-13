[CmdletBinding()]
param(
    [string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'),
    [string]$QualificationRunId=$env:GITHUB_RUN_ID
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$Utf8NoBom=New-Object Text.UTF8Encoding($false)
$Version='4.17.9'
$ProductCommit='bdcf5372dda6ed0e3216b41b9568574b998ec460'
$PreClosureValidationHead='659a81a858bed6265be9fa547804920a79b2d923'
$PreClosureValidationRun='34751238912'
$RiskGateBase='7183f563e644b85f7131db2707816730b5dffb6b'
$Regression='tools/Invoke-Manager4179ConvergenceRegression.ps1'
$TargetIds=@('MGR-DEF-0017','MGR-DEF-0018','MGR-DEF-0019','MGR-DEF-0020','MGR-DEF-0021','MGR-DEF-0022')
if([string]::IsNullOrWhiteSpace($QualificationRunId)){throw 'QualificationRunId/GITHUB_RUN_ID is required.'}

function Read-Text([string]$Relative){return [IO.File]::ReadAllText((Join-Path $RepositoryRoot ($Relative.Replace('/','\'))),[Text.Encoding]::UTF8)}
function Write-Text([string]$Relative,[string]$Text){[IO.File]::WriteAllText((Join-Path $RepositoryRoot ($Relative.Replace('/','\'))),$Text,$Utf8NoBom)}
function Write-Json([string]$Relative,$Object){Write-Text $Relative ((($Object|ConvertTo-Json -Depth 60).Replace("`r`n","`n"))+"`n")}
function Read-Json([string]$Relative){return (Read-Text $Relative|ConvertFrom-Json)}
function Get-ObjectSpanContainingMarker([string]$Text,[string]$Marker){
    $markerIndex=$Text.IndexOf($Marker,[StringComparison]::Ordinal)
    if($markerIndex-lt0){throw('Marker not found: '+$Marker)}
    $start=$Text.LastIndexOf('{',$markerIndex)
    if($start-lt0){throw('Object start not found for marker: '+$Marker)}
    $depth=0;$inString=$false;$escaped=$false
    for($i=$start;$i-lt$Text.Length;$i++){
        $c=$Text[$i]
        if($inString){
            if($escaped){$escaped=$false;continue}
            if($c-eq'\'){$escaped=$true;continue}
            if($c-eq'"'){$inString=$false}
            continue
        }
        if($c-eq'"'){$inString=$true;continue}
        if($c-eq'{'){$depth++;continue}
        if($c-eq'}'){$depth--;if($depth-eq0){return [pscustomobject]@{Start=$start;Length=($i-$start+1)}}}
    }
    throw('Object end not found for marker: '+$Marker)
}
function Close-DefectsInFile([string]$Relative,[string[]]$Ids){
    $text=Read-Text $Relative
    foreach($id in $Ids){
        $marker='"id"'
        $searchVariants=@('"id": "'+$id+'"','"id":"'+$id+'"')
        $selected=$null
        foreach($variant in $searchVariants){if($text.IndexOf($variant,[StringComparison]::Ordinal)-ge0){$selected=$variant;break}}
        if(-not$selected){throw($id+' not found in '+$Relative)}
        $span=Get-ObjectSpanContainingMarker $text $selected
        $block=$text.Substring($span.Start,$span.Length)
        $obj=$block|ConvertFrom-Json
        if([string]$obj.id-cne$id){throw('Object identity mismatch for '+$id)}
        if([string]$obj.status-cne'open' -or -not[bool]$obj.release_blocker){throw($id+' is not an open release blocker before closure.')}
        if(-not(@($obj.planned_regressions)-contains$Regression) -and -not(@($obj.permanent_regressions)-contains$Regression)){throw($id+' is not bound to the 4.17.9 regression before closure.')}
        $obj.status='fixed'
        $obj.fixed_in=$Version
        $permanent=@(@($obj.permanent_regressions|ForEach-Object{[string]$_})+$Regression|Sort-Object -Unique)
        $planned=@($obj.planned_regressions|ForEach-Object{[string]$_}|Where-Object{$_-cne$Regression}|Sort-Object -Unique)
        $obj.permanent_regressions=$permanent
        $obj.planned_regressions=$planned
        $evidence=New-Object System.Collections.ArrayList
        foreach($row in @($obj.evidence)){[void]$evidence.Add($row)}
        [void]$evidence.Add([pscustomobject]@{type='product_commit';id=$ProductCommit})
        [void]$evidence.Add([pscustomobject]@{type='development_validation';id=$PreClosureValidationRun;head=$PreClosureValidationHead})
        [void]$evidence.Add([pscustomobject]@{type='permanent_regression';id=$Regression})
        $obj.evidence=@($evidence)
        $newBlock=($obj|ConvertTo-Json -Depth 40).Replace("`r`n","`n")
        $text=$text.Remove($span.Start,$span.Length).Insert($span.Start,$newBlock)
    }
    # Parse the entire document after focused object replacements.
    $doc=$text|ConvertFrom-Json
    foreach($id in $Ids){
        $rows=@($doc.defects|Where-Object{[string]$_.id-ceq$id})
        if($rows.Count-ne1 -or [string]$rows[0].status-cne'fixed' -or [string]$rows[0].fixed_in-cne$Version){throw('Post-closure defect validation failed: '+$id)}
    }
    Write-Text $Relative ($text.Replace("`r`n","`n").TrimEnd()+"`n")
}

Close-DefectsInFile 'tests/knowledge/defects/manager-4.17.x.json' @('MGR-DEF-0017','MGR-DEF-0018')
Close-DefectsInFile 'tests/knowledge/defects/manager-4.17.9-audit.json' @('MGR-DEF-0019','MGR-DEF-0020','MGR-DEF-0021','MGR-DEF-0022')

# Preserve the audit as historical evidence after all originally-open findings are resolved.
$auditPath='tests/knowledge/audits/pre-4.17.9-multi-hub.json'
$audit=Read-Json $auditPath
if([string]$audit.audit_id-cne'MHA-4179-001'){throw 'Unexpected convergence audit identity.'}
$audit.confirmed_open_defects=@()
if($audit.PSObject.Properties.Name -contains 'resolved_defects'){$audit.resolved_defects=$TargetIds}else{$audit|Add-Member -NotePropertyName resolved_defects -NotePropertyValue $TargetIds}
$resolution=[ordered]@{
    status='resolved'
    manager_version=$Version
    product_commit=$ProductCommit
    pre_closure_development_validation_head=$PreClosureValidationHead
    pre_closure_development_validation_run_id=$PreClosureValidationRun
    closure_qualification_run_id=[string]$QualificationRunId
    permanent_regression=$Regression
    strict_gate_base_commit=$RiskGateBase
}
if($audit.PSObject.Properties.Name -contains 'resolution'){$audit.resolution=$resolution}else{$audit|Add-Member -NotePropertyName resolution -NotePropertyValue $resolution}
Write-Json $auditPath $audit

# Make audit validation lifecycle-aware: historical audits remain valid after their blockers are fixed.
$validatorPath='tools/Test-ManagerEngineeringKnowledge.ps1'
$validator=Read-Text $validatorPath
$old=@'
    if(@($audit.confirmed_open_defects).Count-eq0){Fail($aid+' has no confirmed open defects.')}
    foreach($did in @($audit.confirmed_open_defects)){
        Assert-Ref $defectIds ([string]$did) 'defect' $aid
        $defect=$defectById[[string]$did]
        if([string]$defect.status-cne'open' -or -not[bool]$defect.release_blocker){Fail($aid+' confirmed_open_defects must reference an open release blocker: '+[string]$did)}
        [void]$auditedOpenBlockers.Add([string]$did)
    }
'@
$new=@'
    $confirmedOpen=@($audit.confirmed_open_defects)
    $resolvedDefects=@()
    if($audit.PSObject.Properties.Name -contains 'resolved_defects'){$resolvedDefects=@($audit.resolved_defects)}
    if($confirmedOpen.Count-eq0 -and $resolvedDefects.Count-eq0){Fail($aid+' has neither confirmed open nor resolved defects.')}
    foreach($did in @($confirmedOpen)){
        Assert-Ref $defectIds ([string]$did) 'defect' $aid
        $defect=$defectById[[string]$did]
        if([string]$defect.status-cne'open' -or -not[bool]$defect.release_blocker){Fail($aid+' confirmed_open_defects must reference an open release blocker: '+[string]$did)}
        [void]$auditedOpenBlockers.Add([string]$did)
    }
    foreach($did in @($resolvedDefects)){
        Assert-Ref $defectIds ([string]$did) 'defect' $aid
        $defect=$defectById[[string]$did]
        if([string]$defect.status-cne'fixed' -or -not[bool]$defect.release_blocker){Fail($aid+' resolved_defects must reference a fixed release blocker: '+[string]$did)}
        if(@($confirmedOpen)-contains[string]$did){Fail($aid+' defect cannot be both open and resolved: '+[string]$did)}
    }
    if($audit.PSObject.Properties.Name -contains 'resolution'){
        $resolutionStatus=[string]$audit.resolution.status
        if($resolutionStatus-ceq'resolved'){
            if($confirmedOpen.Count-ne0){Fail($aid+' is resolved but still has confirmed_open_defects.')}
            if($resolvedDefects.Count-eq0){Fail($aid+' is resolved but has no resolved_defects.')}
            if([string]::IsNullOrWhiteSpace([string]$audit.resolution.manager_version)){Fail($aid+' resolved audit lacks manager_version.')}
            if([string]::IsNullOrWhiteSpace([string]$audit.resolution.permanent_regression)){Fail($aid+' resolved audit lacks permanent_regression.')}
            Assert-ExistingCoveragePath ([string]$audit.resolution.permanent_regression) $aid
        }elseif(-not[string]::IsNullOrWhiteSpace($resolutionStatus) -and $resolutionStatus-cne'open'){
            Fail($aid+' has unsupported resolution status: '+$resolutionStatus)
        }
    }
'@
$oldNormalized=$old.Replace("`r`n","`n")
$validatorNormalized=$validator.Replace("`r`n","`n")
if(-not$validatorNormalized.Contains($oldNormalized)){throw 'Expected audit-validator block not found.'}
$validatorNormalized=$validatorNormalized.Replace($oldNormalized,$new.Replace("`r`n","`n"))
Write-Text $validatorPath ($validatorNormalized.TrimEnd()+"`n")

# Promote the convergence suite from planned to permanent risk-surface coverage.
$riskPath='tests/knowledge/risk-map.json'
$riskText=(Read-Text $riskPath).Replace("`r`n","`n")
$pattern='"regressions":\[(?<items>[^\]]*)\],"planned_regressions":\["tools/Invoke-Manager4179ConvergenceRegression\.ps1"\]'
$matches=[regex]::Matches($riskText,$pattern)
if($matches.Count-lt1){throw 'No planned 4.17.9 risk-surface coverage found to promote.'}
$riskText=[regex]::Replace($riskText,$pattern,{param($m)
    $items=[string]$m.Groups['items'].Value
    if($items.Contains('"tools/Invoke-Manager4179ConvergenceRegression.ps1"')){return '"regressions":['+$items+'],"planned_regressions":[]'}
    if([string]::IsNullOrWhiteSpace($items)){return '"regressions":["tools/Invoke-Manager4179ConvergenceRegression.ps1"],"planned_regressions":[]'}
    return '"regressions":['+$items+',"tools/Invoke-Manager4179ConvergenceRegression.ps1"],"planned_regressions":[]'
})
Write-Text $riskPath ($riskText.TrimEnd()+"`n")

# Development state becomes blocker-free but still unqualified until freeze/Source/Full/production gates.
$statePath='MANAGER_DEVELOPMENT_STATE.json'
$state=Read-Json $statePath
$state.open_release_blockers=@()
$state.qualification.development_validation.status='pass_required_on_closure_head'
$state.qualification.development_validation.last_known_pass_run_id=[string]$QualificationRunId
$state.qualification.development_validation.note='This state is published only if the one-shot closure workflow validates the exact local closure commit on hosted Windows; branch HEAD remains live-resolved.'
$state.qualification.risk_defect_gate.status='required_pass_before_freeze'
if($state.qualification.risk_defect_gate.PSObject.Properties.Name -contains 'last_pass_run_id'){$state.qualification.risk_defect_gate.last_pass_run_id=[string]$QualificationRunId}else{$state.qualification.risk_defect_gate|Add-Member -NotePropertyName last_pass_run_id -NotePropertyValue ([string]$QualificationRunId)}
if($state.qualification.risk_defect_gate.PSObject.Properties.Name -contains 'base_commit'){$state.qualification.risk_defect_gate.base_commit=$RiskGateBase}else{$state.qualification.risk_defect_gate|Add-Member -NotePropertyName base_commit -NotePropertyValue $RiskGateBase}
$state.qualification.risk_defect_gate.note='All 4.17.9 convergence blockers are recorded fixed with permanent coverage; the closure commit may publish only after the strict gate passes from the production-provenance base.'
$state.next_exact_goal.id='MANAGER-4179-CANDIDATE-FREEZE-001'
$state.next_exact_goal.description='After the exact closure commit passes hosted Development Validation and strict Risk/Defect Gate from the production-provenance base, freeze immutable Manager 4.17.9 candidate g1 and run Source/Full Gate; keep production multi-Hub inactive until production acceptance.'
Write-Json $statePath $state

# Keep the roadmap aligned with lessons from this closure, not only the current release.
$roadmapPath='MANAGER_ENGINEERING_ROADMAP.md'
$roadmap=(Read-Text $roadmapPath).Replace("`r`n","`n")
$roadmap=$roadmap.Replace("### R-003 — Multi-Hub convergence and recovery completeness`n`n- **Priority:** P0`n- **Status:** NEXT","### R-003 — Multi-Hub convergence and recovery completeness`n`n- **Priority:** P0`n- **Status:** ACTIVE")
if(-not$roadmap.Contains('### R-013 — Evidence-driven defect and audit lifecycle')){
$insert=@'
### R-013 — Evidence-driven defect and audit lifecycle

- **Priority:** P1
- **Status:** ACTIVE
- **Goal:** make defect knowledge progress safely from discovery -> open blocker -> implemented fix -> permanent regression -> resolved audit without manual contradictions or loss of historical evidence.
- **Required properties:** resolved audits remain valid historical records; fixed blockers require permanent coverage; planned coverage is promoted to risk-map regressions; development-state blocker lists cannot become stale; policy gates adapt from expected-fail to required-pass without being weakened.
- **Dependency:** R-002.
- **Exit:** reusable lifecycle tooling performs evidence-backed closure generically and CI validates both open and resolved audit states.

### R-014 — Durable compact CI / qualification evidence receipts

- **Priority:** P1
- **Status:** PLANNED
- **Goal:** preserve small machine-readable conclusions and identities after short-lived Actions artifacts expire, without committing large logs, build trees or generated release archives.
- **Required properties:** bind source commit/tree, Manager version, managed digest, framework/gate revision, relevant workflow run, result and artifact hashes; immutable candidate/release evidence remains distinct from development evidence.
- **Dependency:** repository-resident development state and qualification provenance contracts.
- **Exit:** a new session can prove the latest relevant PASS/FAIL from durable compact receipts even after disposable CI artifacts expire.

### R-015 — Automatic systemic-learning and roadmap intake

- **Priority:** P2
- **Status:** PLANNED
- **Goal:** use repeated defect classes, invariant violations, audit findings and CI failure classification to propose or update systemic roadmap work automatically instead of relying on a maintainer to notice recurrence manually.
- **Rule:** automation may recommend/reprioritize roadmap items but may not silently weaken release blockers or qualification requirements.
- **Dependency:** R-002 and R-013.
- **Exit:** repeated-defect detection produces deterministic machine-readable learning signals that can be consumed by roadmap/context generation.

'@
    $marker='## Intake rule for new ideas'
    if(-not$roadmap.Contains($marker)){throw 'Roadmap intake marker missing.'}
    $roadmap=$roadmap.Replace($marker,$insert.Replace("`r`n","`n")+$marker)
}
Write-Text $roadmapPath ($roadmap.TrimEnd()+"`n")

# Final internal consistency before the workflow commits anything.
foreach($relative in @(
    'tests/knowledge/defects/manager-4.17.x.json',
    'tests/knowledge/defects/manager-4.17.9-audit.json',
    'tests/knowledge/audits/pre-4.17.9-multi-hub.json',
    'tests/knowledge/risk-map.json',
    'MANAGER_DEVELOPMENT_STATE.json'
)){[void](Read-Json $relative)}

Write-Host ('Manager '+$Version+' knowledge closure transformer: PASS. targets='+$TargetIds.Count+' promoted_surfaces='+$matches.Count) -ForegroundColor Green
