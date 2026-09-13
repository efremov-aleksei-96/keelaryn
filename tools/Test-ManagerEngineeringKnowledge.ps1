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

$roots=Read-Json 'tests/knowledge/root-causes.json'
$invariantsDoc=Read-Json 'tests/knowledge/invariants/multi-hub.json'
$defectsDoc=Read-Json 'tests/knowledge/defects/manager-4.17.x.json'
$machine=Read-Json 'tests/knowledge/state-machines/multi-hub.json'
$risk=Read-Json 'tests/knowledge/risk-map.json'

if([string]$roots.schema-cne'keelaryn.manager-engineering-root-causes.v1'){Fail 'Unexpected root-cause schema.'}
if([string]$invariantsDoc.schema-cne'keelaryn.manager-invariants.v1'){Fail 'Unexpected invariant schema.'}
if([string]$defectsDoc.schema-cne'keelaryn.manager-defects.v1'){Fail 'Unexpected defect schema.'}
if([string]$machine.schema-cne'keelaryn.manager-state-machine.v1'){Fail 'Unexpected state-machine schema.'}
if([string]$risk.schema-cne'keelaryn.manager-risk-map.v1'){Fail 'Unexpected risk-map schema.'}

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
foreach($d in @($defectsDoc.defects)){
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
foreach($d in @($defectsDoc.defects)){foreach($other in @($d.related_defects)){Assert-Ref $defectIds ([string]$other) 'defect' ([string]$d.id)}}

Write-Host 'Manager Engineering Knowledge: structural validation PASS' -ForegroundColor Green
Write-Host ('  root-cause classes: '+@($roots.classes).Count)
Write-Host ('  invariants: '+@($invariantsDoc.invariants).Count)
Write-Host ('  defects: '+@($defectsDoc.defects).Count+' (open='+@($defectsDoc.defects|Where-Object{$_.status-eq'open'}).Count+')')
Write-Host ('  risk surfaces: '+@($risk.surfaces).Count)
Write-Host ('  state scenarios: '+@($machine.states).Count+'; operations='+@($machine.operations).Count+'; rules='+@($machine.rules).Count)

$repeated=New-Object System.Collections.ArrayList
foreach($inv in @($invariantsDoc.invariants)){
    $iid=[string]$inv.id
    $violations=@($defectsDoc.defects|Where-Object{@($_.violated_invariants)-contains$iid})
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
