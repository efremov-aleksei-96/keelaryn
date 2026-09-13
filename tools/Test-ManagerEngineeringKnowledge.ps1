[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')

function Fail([string]$Message){throw $Message}
function Read-Json([string]$RelativePath){
    $path=Join-Path $RepositoryRoot ($RelativePath.Replace('/','\'))
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){Fail('Knowledge file missing: '+$RelativePath)}
    try{return (Get-Content -LiteralPath $path -Raw -Encoding UTF8|ConvertFrom-Json)}catch{Fail('Invalid JSON '+$RelativePath+': '+$_.Exception.Message)}
}
function New-IdSet(){return New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)}
function Add-Unique($Set,[string]$Id,[string]$Kind){if([string]::IsNullOrWhiteSpace($Id)){Fail($Kind+' id is empty.')}if(-not$Set.Add($Id)){Fail('Duplicate '+$Kind+' id: '+$Id)}}
function Assert-Ref($Set,[string]$Id,[string]$Kind,[string]$Owner){if(-not$Set.Contains($Id)){Fail($Owner+' references unknown '+$Kind+': '+$Id)}}
function Assert-ExistingCoveragePath([string]$RelativePath,[string]$Owner){
    $path=Join-Path $RepositoryRoot ($RelativePath.Replace('/','\'))
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){Fail($Owner+' references missing permanent coverage: '+$RelativePath)}
}
function Assert-ExistingFile([string]$RelativePath,[string]$Owner){
    $path=Join-Path $RepositoryRoot ($RelativePath.Replace('/','\'))
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){Fail($Owner+' references missing file: '+$RelativePath)}
}
function Read-AllDefectRecords {
    $dir=Join-Path $RepositoryRoot 'tests\knowledge\defects'
    if(-not(Test-Path -LiteralPath $dir -PathType Container)){Fail 'Knowledge defect directory is missing.'}
    $files=@(Get-ChildItem -LiteralPath $dir -File -Filter '*.json'|Sort-Object Name)
    if($files.Count-eq0){Fail 'Knowledge defect directory contains no canonical defect files.'}
    $records=New-Object System.Collections.ArrayList
    foreach($file in $files){
        try{$doc=Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8|ConvertFrom-Json}catch{Fail('Invalid JSON '+$file.FullName+': '+$_.Exception.Message)}
        if([string]$doc.schema-cne'keelaryn.manager-defects.v1'){Fail('Unexpected defect schema in '+$file.Name+'.')}
        foreach($row in @($doc.defects)){[void]$records.Add($row)}
    }
    return [pscustomobject]@{Files=@($files);Records=@($records)}
}
function Read-AllRiskAudits {
    $dir=Join-Path $RepositoryRoot 'tests\knowledge\audits'
    if(-not(Test-Path -LiteralPath $dir -PathType Container)){Fail 'Knowledge audit directory is missing.'}
    $files=@(Get-ChildItem -LiteralPath $dir -File -Filter '*.json'|Sort-Object Name)
    if($files.Count-eq0){Fail 'Knowledge audit directory contains no risk-audit files.'}
    $docs=New-Object System.Collections.ArrayList
    foreach($file in $files){
        try{$doc=Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8|ConvertFrom-Json}catch{Fail('Invalid JSON '+$file.FullName+': '+$_.Exception.Message)}
        if([string]$doc.schema-cne'keelaryn.manager-risk-audit.v1'){Fail('Unexpected risk-audit schema in '+$file.Name+'.')}
        [void]$docs.Add([pscustomobject]@{File=$file;Document=$doc})
    }
    return [pscustomobject]@{Files=@($files);Documents=@($docs)}
}

$roots=Read-Json 'tests/knowledge/root-causes.json'
$invariantsDoc=Read-Json 'tests/knowledge/invariants/multi-hub.json'
$defectSet=Read-AllDefectRecords
$allDefects=@($defectSet.Records)
$machine=Read-Json 'tests/knowledge/state-machines/multi-hub.json'
$risk=Read-Json 'tests/knowledge/risk-map.json'
$auditSet=Read-AllRiskAudits
$developmentState=Read-Json 'MANAGER_DEVELOPMENT_STATE.json'

if([string]$roots.schema-cne'keelaryn.manager-engineering-root-causes.v1'){Fail 'Unexpected root-cause schema.'}
if([string]$invariantsDoc.schema-cne'keelaryn.manager-invariants.v1'){Fail 'Unexpected invariant schema.'}
if([string]$machine.schema-cne'keelaryn.manager-state-machine.v1'){Fail 'Unexpected state-machine schema.'}
if([string]$risk.schema-cne'keelaryn.manager-risk-map.v1'){Fail 'Unexpected risk-map schema.'}
if([string]$developmentState.schema-cne'keelaryn.manager-development-state.v1'){Fail 'Unexpected Manager development-state schema.'}

$rootIds=New-IdSet
foreach($row in @($roots.classes)){Add-Unique $rootIds ([string]$row.id) 'root-cause'}

$invariantIds=New-IdSet
$invariantById=@{}
foreach($row in @($invariantsDoc.invariants)){
    $id=[string]$row.id
    Add-Unique $invariantIds $id 'invariant'
    if($id-notmatch'^MH-[A-Z0-9-]+-\d{3}$'){Fail('Invariant id is not canonical: '+$id)}
    if([string]::IsNullOrWhiteSpace([string]$row.rule)){Fail('Invariant rule is empty: '+$id)}
    if(@($row.coverage).Count-eq0){Fail('Invariant coverage declaration missing: '+$id)}
    $invariantById[$id]=$row
}

$stateIds=New-IdSet
foreach($row in @($machine.states)){Add-Unique $stateIds ([string]$row.id) 'state'}
$operationIds=New-IdSet
foreach($op in @($machine.operations)){Add-Unique $operationIds ([string]$op) 'operation'}
$ruleIds=New-IdSet
$ruleById=@{}
foreach($rule in @($machine.rules)){
    $rid=[string]$rule.id
    Add-Unique $ruleIds $rid 'state-machine rule'
    Assert-Ref $operationIds ([string]$rule.operation) 'operation' $rid
    if(@($rule.states).Count-eq0){Fail($rid+' has no state selector.')}
    foreach($sid in @($rule.states)){if([string]$sid-cne'*'){Assert-Ref $stateIds ([string]$sid) 'state' $rid}}
    foreach($iid in @($rule.invariants)){Assert-Ref $invariantIds ([string]$iid) 'invariant' $rid}
    if($null-eq$rule.priority){Fail($rid+' has no priority.')}
    if([string]::IsNullOrWhiteSpace([string]$rule.outcome)){Fail($rid+' has no expected outcome.')}
    $ruleById[$rid]=$rule
}

foreach($state in @($machine.states)){
    $sid=[string]$state.id
    foreach($op in @($machine.operations)){
        $matches=@($machine.rules|Where-Object{[string]$_.operation-ceq[string]$op -and (@($_.states)-contains'*' -or @($_.states)-contains$sid)})
        if($matches.Count-eq0){Fail('State machine uncovered pair: '+$sid+' x '+[string]$op)}
        $max=($matches|Measure-Object -Property priority -Maximum).Maximum
        $winners=@($matches|Where-Object{[int]$_.priority-eq[int]$max})
        if($winners.Count-ne1){Fail('State machine ambiguous pair: '+$sid+' x '+[string]$op+'; priority='+$max+'; rules='+([string]::Join(',',@($winners|ForEach-Object{$_.id}))))}
    }
}

$surfaceIds=New-IdSet
$surfaceById=@{}
$coveredInvariantIds=New-IdSet
foreach($surface in @($risk.surfaces)){
    $sid=[string]$surface.id
    Add-Unique $surfaceIds $sid 'risk-surface'
    if(@($surface.paths).Count-eq0){Fail($sid+' has no path mapping.')}
    foreach($iid in @($surface.invariants)){Assert-Ref $invariantIds ([string]$iid) 'invariant' $sid;[void]$coveredInvariantIds.Add([string]$iid)}
    foreach($rc in @($surface.root_cause_classes)){Assert-Ref $rootIds ([string]$rc) 'root-cause' $sid}
    foreach($rid in @($surface.state_machine_rules)){Assert-Ref $ruleIds ([string]$rid) 'state-machine rule' $sid}
    foreach($reg in @($surface.regressions)){Assert-ExistingCoveragePath ([string]$reg) $sid}
    $surfaceById[$sid]=$surface
}
foreach($iid in @($invariantIds)){if(-not$coveredInvariantIds.Contains($iid)){Fail('Invariant has no risk-surface mapping: '+$iid)}}

$defectIds=New-IdSet
$defectById=@{}
foreach($d in $allDefects){
    $id=[string]$d.id
    Add-Unique $defectIds $id 'defect'
    if($id-notmatch'^MGR-DEF-\d{4}$'){Fail('Defect id is not canonical: '+$id)}
    if(@('fixed','open')-cnotcontains[string]$d.status){Fail($id+' has unsupported status: '+[string]$d.status)}
    if(@('P1','P2','P3')-cnotcontains[string]$d.severity){Fail($id+' has unsupported severity: '+[string]$d.severity)}
    if(@($d.affected_surfaces).Count-eq0){Fail($id+' has no affected surface.')}
    foreach($sid in @($d.affected_surfaces)){Assert-Ref $surfaceIds ([string]$sid) 'risk-surface' $id}
    if(@($d.root_cause_classes).Count-eq0){Fail($id+' has no root-cause class.')}
    foreach($rc in @($d.root_cause_classes)){Assert-Ref $rootIds ([string]$rc) 'root-cause' $id}
    if(@($d.violated_invariants).Count-eq0){Fail($id+' has no violated invariant.')}
    foreach($iid in @($d.violated_invariants)){Assert-Ref $invariantIds ([string]$iid) 'invariant' $id}
    if([string]$d.status-ceq'fixed'){
        if([string]::IsNullOrWhiteSpace([string]$d.fixed_in)){Fail($id+' is fixed but fixed_in is empty.')}
        if(@($d.permanent_regressions).Count-eq0){Fail($id+' is fixed but has no permanent coverage.')}
        foreach($reg in @($d.permanent_regressions)){Assert-ExistingCoveragePath ([string]$reg) $id}
    }else{
        if(-not[string]::IsNullOrWhiteSpace([string]$d.fixed_in)){Fail($id+' is open but fixed_in is populated.')}
        if(@($d.permanent_regressions).Count-eq0 -and @($d.planned_regressions).Count-eq0){Fail($id+' is open but has neither permanent nor planned coverage.')}
    }
    $defectById[$id]=$d
}
foreach($d in $allDefects){foreach($other in @($d.related_defects)){Assert-Ref $defectIds ([string]$other) 'defect' ([string]$d.id)}}

$auditIds=New-IdSet
$auditedOpenBlockers=New-IdSet
foreach($entry in @($auditSet.Documents)){
    $audit=$entry.Document
    $aid=[string]$audit.audit_id
    Add-Unique $auditIds $aid 'risk-audit'
    if($aid-notmatch'^MHA-[A-Z0-9-]+$'){Fail('Risk-audit id is not canonical: '+$aid)}
    if([string]::IsNullOrWhiteSpace([string]$audit.title)){Fail($aid+' has no title.')}
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
    }    $clusterIds=New-IdSet
    foreach($cluster in @($audit.convergence_clusters)){
        $cid=[string]$cluster.id
        Add-Unique $clusterIds $cid ($aid+' cluster')
        if(@($cluster.invariants).Count-eq0){Fail($aid+'/'+$cid+' has no invariants.')}
        foreach($iid in @($cluster.invariants)){Assert-Ref $invariantIds ([string]$iid) 'invariant' ($aid+'/'+$cid)}
        foreach($did in @($cluster.defects)){Assert-Ref $defectIds ([string]$did) 'defect' ($aid+'/'+$cid)}
    }
    $testIds=New-IdSet
    if(@($audit.required_pre_product_tests).Count-eq0){Fail($aid+' has no required pre-product tests.')}
    foreach($test in @($audit.required_pre_product_tests)){
        $tid=[string]$test.id
        Add-Unique $testIds $tid ($aid+' test')
        Assert-Ref $stateIds ([string]$test.state) 'state' ($aid+'/'+$tid)
        Assert-Ref $operationIds ([string]$test.operation) 'operation' ($aid+'/'+$tid)
        if([string]::IsNullOrWhiteSpace([string]$test.expected)){Fail($aid+'/'+$tid+' has no expected result.')}
    }
    if(@($audit.implementation_constraints).Count-eq0){Fail($aid+' has no implementation constraints.')}
    if(@($audit.freeze_criteria).Count-eq0){Fail($aid+' has no freeze criteria.')}
}

$openReleaseBlockers=@($allDefects|Where-Object{[string]$_.status-eq'open' -and [bool]$_.release_blocker})
foreach($d in $openReleaseBlockers){
    $id=[string]$d.id
    if(-not$auditedOpenBlockers.Contains($id) -and @($d.planned_regressions).Count-eq0){Fail($id+' is an open release blocker with neither audit coverage nor planned regression.')}
}

if([string]$developmentState.repository-cne'efremov-aleksei-96/keelaryn'){Fail 'Development state repository identity is unexpected.'}
if([string]::IsNullOrWhiteSpace([string]$developmentState.authoritative_branch)){Fail 'Development state authoritative_branch is empty.'}
if($developmentState.PSObject.Properties.Name -contains 'authoritative_head'){Fail 'Development state must not store self-referential authoritative_head; resolve the branch ref live.'}
if([string]$developmentState.head_resolution.mode-cne'resolve_branch_ref_live'){Fail 'Development state head_resolution.mode must be resolve_branch_ref_live.'}
if(@('unqualified_development','candidate_frozen','qualified_release')-cnotcontains[string]$developmentState.lifecycle_state){Fail('Unsupported development lifecycle_state: '+[string]$developmentState.lifecycle_state)}
Assert-ExistingFile ([string]$developmentState.knowledge.roadmap) 'development state'
Assert-ExistingFile ([string]$developmentState.knowledge.strict_pre_freeze_gate) 'development state'
if([string]::IsNullOrWhiteSpace([string]$developmentState.next_exact_goal.id) -or [string]::IsNullOrWhiteSpace([string]$developmentState.next_exact_goal.description)){Fail 'Development state next_exact_goal is incomplete.'}

$stateBlockers=New-IdSet
foreach($did in @($developmentState.open_release_blockers)){
    Add-Unique $stateBlockers ([string]$did) 'development-state blocker'
    Assert-Ref $defectIds ([string]$did) 'defect' 'development state'
    $defect=$defectById[[string]$did]
    if([string]$defect.status-cne'open' -or -not[bool]$defect.release_blocker){Fail('Development state blocker is not an open release blocker: '+[string]$did)}
}
foreach($d in $openReleaseBlockers){if(-not$stateBlockers.Contains([string]$d.id)){Fail('Development state omits open release blocker: '+[string]$d.id)}}
foreach($did in @($stateBlockers)){if(-not(@($openReleaseBlockers|ForEach-Object{[string]$_.id})-contains$did)){Fail('Development state contains stale blocker: '+$did)}}
foreach($aid in @($developmentState.knowledge.current_risk_audits)){Assert-Ref $auditIds ([string]$aid) 'risk-audit' 'development state'}

Write-Host 'Manager Engineering Knowledge: structural validation PASS' -ForegroundColor Green
Write-Host ('  root-cause classes: '+@($roots.classes).Count)
Write-Host ('  invariants: '+@($invariantsDoc.invariants).Count)
Write-Host ('  defect files: '+@($defectSet.Files).Count)
Write-Host ('  defects: '+$allDefects.Count+' (open='+@($allDefects|Where-Object{$_.status-eq'open'}).Count+')')
Write-Host ('  risk surfaces: '+@($risk.surfaces).Count)
Write-Host ('  state scenarios: '+@($machine.states).Count+'; operations='+@($machine.operations).Count+'; rules='+@($machine.rules).Count)
Write-Host ('  risk audits: '+@($auditSet.Files).Count)
Write-Host ('  development-state blockers: '+@($developmentState.open_release_blockers).Count)

$repeated=New-Object System.Collections.ArrayList
foreach($inv in @($invariantsDoc.invariants)){
    $iid=[string]$inv.id
    $violations=@($allDefects|Where-Object{@($_.violated_invariants)-contains$iid})
    if($violations.Count-ge2){
        [void]$repeated.Add([pscustomobject]@{Invariant=$iid;Defects=@($violations|ForEach-Object{[string]$_.id})})
    }
}
foreach($row in @($repeated)){
    Write-Host ''
    Write-Host 'REPEATED DEFECT CLASS' -ForegroundColor Yellow
    Write-Host ('Invariant: '+$row.Invariant)
    Write-Host ('Violations: '+([string]::Join(', ',@($row.Defects))))
}

Write-Host ''
Write-Host 'MANAGER ENGINEERING KNOWLEDGE: PASS' -ForegroundColor Green
