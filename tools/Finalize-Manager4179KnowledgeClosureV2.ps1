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

function Resolve-Path([string]$Relative){return (Join-Path $RepositoryRoot ($Relative.Replace('/','\')))}
function Read-Text([string]$Relative){return [IO.File]::ReadAllText((Resolve-Path $Relative),[Text.Encoding]::UTF8)}
function Write-Text([string]$Relative,[string]$Text){[IO.File]::WriteAllText((Resolve-Path $Relative),$Text,$Utf8NoBom)}
function Read-Json([string]$Relative){return (Read-Text $Relative|ConvertFrom-Json)}
function Write-Json([string]$Relative,$Object){Write-Text $Relative ((($Object|ConvertTo-Json -Depth 60).Replace("`r`n","`n"))+"`n")}
function Add-PropertyIfMissing($Object,[string]$Name,$Value){
    if($Object.PSObject.Properties.Name -contains $Name){$Object.$Name=$Value}else{$Object|Add-Member -NotePropertyName $Name -NotePropertyValue $Value}
}
function Close-Defects([string]$Relative,[string[]]$Ids){
    $doc=Read-Json $Relative
    foreach($id in $Ids){
        $rows=@($doc.defects|Where-Object{[string]$_.id-ceq$id})
        if($rows.Count-ne1){throw($Relative+' expected one '+$id+'; actual='+$rows.Count)}
        $d=$rows[0]
        if([string]$d.status-cne'open' -or -not[bool]$d.release_blocker){throw($id+' is not an open release blocker before closure.')}
        if(-not(@($d.planned_regressions)-contains$Regression) -and -not(@($d.permanent_regressions)-contains$Regression)){throw($id+' lacks the 4.17.9 convergence regression binding.')}
        $d.status='fixed'
        $d.fixed_in=$Version
        $d.permanent_regressions=@(@($d.permanent_regressions|ForEach-Object{[string]$_})+$Regression|Sort-Object -Unique)
        $d.planned_regressions=@($d.planned_regressions|ForEach-Object{[string]$_}|Where-Object{$_-cne$Regression}|Sort-Object -Unique)
        $evidence=New-Object System.Collections.ArrayList
        foreach($row in @($d.evidence)){[void]$evidence.Add($row)}
        [void]$evidence.Add([pscustomobject]@{type='product_commit';id=$ProductCommit})
        [void]$evidence.Add([pscustomobject]@{type='development_validation';id=$PreClosureValidationRun;head=$PreClosureValidationHead})
        [void]$evidence.Add([pscustomobject]@{type='permanent_regression';id=$Regression})
        $d.evidence=@($evidence)
    }
    Write-Json $Relative $doc
}

Close-Defects 'tests/knowledge/defects/manager-4.17.x.json' @('MGR-DEF-0017','MGR-DEF-0018')
Close-Defects 'tests/knowledge/defects/manager-4.17.9-audit.json' @('MGR-DEF-0019','MGR-DEF-0020','MGR-DEF-0021','MGR-DEF-0022')

$auditPath='tests/knowledge/audits/pre-4.17.9-multi-hub.json'
$audit=Read-Json $auditPath
if([string]$audit.audit_id-cne'MHA-4179-001'){throw 'Unexpected convergence audit identity.'}
$audit.confirmed_open_defects=@()
Add-PropertyIfMissing $audit 'resolved_defects' $TargetIds
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
Add-PropertyIfMissing $audit 'resolution' $resolution
Write-Json $auditPath $audit

# Lifecycle-aware audit validation: an audit may be open or historically resolved.
$validatorPath='tools/Test-ManagerEngineeringKnowledge.ps1'
$validator=(Read-Text $validatorPath).Replace("`r`n","`n")
$startMarker="    if(@(`$audit.confirmed_open_defects).Count-eq0){Fail(`$aid+' has no confirmed open defects.')}`n"
$endMarker='    $clusterIds=New-IdSet'
$start=$validator.IndexOf($startMarker,[StringComparison]::Ordinal)
$end=$validator.IndexOf($endMarker,[StringComparison]::Ordinal)
if($start-lt0 -or $end-le$start){throw 'Expected audit validation section was not found.'}
$replacement=@'
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
        if(@($confirmedOpen) -contains ([string]$did)){Fail($aid+' defect cannot be both open and resolved: '+[string]$did)}
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
$replacement=$replacement.Replace("`r`n","`n")
$validator=$validator.Substring(0,$start)+$replacement+$validator.Substring($end)
Write-Text $validatorPath ($validator.TrimEnd()+"`n")

# Promote the 4.17.9 suite from planned to permanent on every surface that planned it.
$riskPath='tests/knowledge/risk-map.json'
$risk=Read-Json $riskPath
$promoted=0
foreach($surface in @($risk.surfaces)){
    if(@($surface.planned_regressions)-contains$Regression){
        $surface.regressions=@(@($surface.regressions|ForEach-Object{[string]$_})+$Regression|Sort-Object -Unique)
        $surface.planned_regressions=@($surface.planned_regressions|ForEach-Object{[string]$_}|Where-Object{$_-cne$Regression}|Sort-Object -Unique)
        $promoted++
    }
}
if($promoted-lt1){throw 'No risk surfaces promoted the 4.17.9 regression.'}
Write-Json $riskPath $risk

$statePath='MANAGER_DEVELOPMENT_STATE.json'
$state=Read-Json $statePath
$state.open_release_blockers=@()
$state.qualification.development_validation.status='pass_required_on_closure_head'
$state.qualification.development_validation.last_known_pass_run_id=[string]$QualificationRunId
$state.qualification.development_validation.note='Published only if the one-shot closure workflow validates the exact local closure commit on hosted Windows; authoritative branch HEAD is resolved live.'
$state.qualification.risk_defect_gate.status='required_pass_before_freeze'
Add-PropertyIfMissing $state.qualification.risk_defect_gate 'last_pass_run_id' ([string]$QualificationRunId)
Add-PropertyIfMissing $state.qualification.risk_defect_gate 'base_commit' $RiskGateBase
$state.qualification.risk_defect_gate.note='Closure may publish only after strict Risk/Defect Gate PASS from the production-provenance base with zero open release blockers.'
$state.next_exact_goal.id='MANAGER-4179-CANDIDATE-FREEZE-001'
$state.next_exact_goal.description='Freeze immutable Manager 4.17.9 candidate g1 only after the exact closure commit passes hosted Development Validation and strict Risk/Defect Gate; then run Source/Full Gate and production-specific acceptance. Production multi-Hub remains inactive until qualification completes.'
Write-Json $statePath $state

# Reparse all mutated JSON before returning success.
foreach($relative in @(
    'tests/knowledge/defects/manager-4.17.x.json',
    'tests/knowledge/defects/manager-4.17.9-audit.json',
    'tests/knowledge/audits/pre-4.17.9-multi-hub.json',
    'tests/knowledge/risk-map.json',
    'MANAGER_DEVELOPMENT_STATE.json'
)){[void](Read-Json $relative)}

Write-Host ('Manager '+$Version+' knowledge closure V2: PASS. targets='+$TargetIds.Count+' promoted_surfaces='+$promoted) -ForegroundColor Green
