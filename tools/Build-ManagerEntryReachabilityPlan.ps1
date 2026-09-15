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
function Read-Json([string]$RelativePath){
    $path=Join-Path $RepositoryRoot ($RelativePath.Replace('/','\'))
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){Fail('Entry plan dependency missing: '+$RelativePath)}
    try{return Get-Content -LiteralPath $path -Raw -Encoding UTF8|ConvertFrom-Json}
    catch{Fail('Invalid JSON '+$RelativePath+': '+$_.Exception.Message)}
}
function Sha([string]$RelativePath){
    $path=Join-Path $RepositoryRoot ($RelativePath.Replace('/','\'))
    return (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Write-Json([string]$Path,$Object){
    $parent=Split-Path -Parent $Path
    if($parent-and-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
    $text=(($Object|ConvertTo-Json -Depth 40).Replace("`r`n","`n"))+"`n"
    [IO.File]::WriteAllText($Path,$text,$Utf8NoBom)
}
function New-Set(){return New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)}
function Add-Unique($Set,[string]$Value,[string]$Kind){
    if([string]::IsNullOrWhiteSpace($Value)){Fail($Kind+' is empty.')}
    if(-not$Set.Add($Value)){Fail('Duplicate '+$Kind+': '+$Value)}
}
function Resolve-Winner($Machine,[string]$State,[string]$Operation){
    $matches=@($Machine.rules|Where-Object{
        [string]$_.operation-ceq$Operation -and (@($_.states)-contains'*' -or @($_.states)-contains$State)
    })
    if($matches.Count-eq0){Fail('State machine has no rule for '+$State+' x '+$Operation)}
    $max=($matches|Measure-Object -Property priority -Maximum).Maximum
    $winners=@($matches|Where-Object{[int]$_.priority-eq[int]$max})
    if($winners.Count-ne1){Fail('State machine winning rule is ambiguous for '+$State+' x '+$Operation+'; rules='+([string]::Join(',',@($winners|ForEach-Object{[string]$_.id}))))}
    return $winners[0]
}

$controlPath='tests/knowledge/entry-reachability-control-flow.json'
$machinePath='tests/knowledge/state-machines/multi-hub.json'
$legacyPath='tests/knowledge/entry-reachability.json'
$control=Read-Json $controlPath
$machine=Read-Json $machinePath
$legacy=Read-Json $legacyPath

if([string]$control.schema-cne'keelaryn.manager-entry-control-flow.v1'){Fail 'Unsupported entry control-flow schema.'}
if([string]$control.state_machine-cne$machinePath){Fail 'Entry control-flow model must point at the canonical multi-Hub state machine.'}
if([string]$machine.schema-cne'keelaryn.manager-state-machine.v1'){Fail 'Unsupported state-machine schema.'}

$machineStates=New-Set
foreach($row in @($machine.states)){Add-Unique $machineStates ([string]$row.id) 'state-machine state'}
$machineOperations=New-Set
foreach($op in @($machine.operations)){Add-Unique $machineOperations ([string]$op) 'state-machine operation'}

$fixtureIds=New-Set
$fixtureByState=@{}
foreach($row in @($control.fixture_states)){
    $sid=[string]$row.id
    Add-Unique $fixtureIds $sid 'entry fixture state'
    if(-not$machineStates.Contains($sid)){Fail('Entry fixture state is absent from canonical state machine: '+$sid)}
    if([string]::IsNullOrWhiteSpace([string]$row.fixture)){Fail('Entry fixture name is empty for '+$sid)}
    $fixtureByState[$sid]=[string]$row.fixture
}
if($fixtureIds.Count-eq0){Fail 'Entry control-flow model has no fixture states.'}

# During migration, fixture identity and action reachability remain cross-checked against
# the existing executable harness model. The old model does not own semantic outcomes.
$legacyStateById=@{}
foreach($row in @($legacy.states)){$legacyStateById[[string]$row.id]=$row}
foreach($sid in @($fixtureIds)){
    if(-not$legacyStateById.ContainsKey($sid)){Fail('Executable harness lacks control-flow fixture state: '+$sid)}
    if([string]$legacyStateById[$sid].fixture-cne[string]$fixtureByState[$sid]){Fail('Fixture identity drift for '+$sid)}
}
$legacyActions=New-Set
foreach($row in @($legacy.actions)){Add-Unique $legacyActions ([string]$row.id) 'legacy entry action'}

$actionIds=New-Set
$edges=New-Object System.Collections.ArrayList
$ordinal=0
foreach($action in @($control.actions)){
    $aid=[string]$action.id
    Add-Unique $actionIds $aid 'entry action'
    if(-not$legacyActions.Contains($aid)){Fail('Executable harness lacks declared process-entry action: '+$aid)}
    $coverage=[string]$action.coverage
    if($coverage-ceq'winning_rule_edges'){
        $op=[string]$action.state_machine_operation
        if(-not$machineOperations.Contains($op)){Fail($aid+' references unknown state-machine operation: '+$op)}
        $representatives=[ordered]@{}
        foreach($fixtureState in @($control.fixture_states)){
            $sid=[string]$fixtureState.id
            $winner=Resolve-Winner $machine $sid $op
            $rid=[string]$winner.id
            if(-not$representatives.Contains($rid)){
                $representatives[$rid]=[pscustomobject]@{State=$sid;Rule=$winner}
            }
        }
        foreach($rid in @($representatives.Keys|Sort-Object)){
            $rep=$representatives[$rid]
            $ordinal++
            [void]$edges.Add([pscustomobject][ordered]@{
                id=('EDGE-{0:D3}' -f $ordinal)
                kind='winning_rule_edge'
                action=$aid
                state=[string]$rep.State
                fixture=[string]$fixtureByState[[string]$rep.State]
                state_machine_operation=$op
                winning_rule=$rid
                outcome=[string]$rep.Rule.outcome
                priority=[int]$rep.Rule.priority
                control_flow_class='state_machine_rule'
            })
        }
    }elseif($coverage-ceq'dispatch_once'){
        $anchor=[string]$action.semantic_anchor_operation
        $state=[string]$action.representative_state
        if(-not$machineOperations.Contains($anchor)){Fail($aid+' references unknown semantic anchor operation: '+$anchor)}
        if(-not$fixtureIds.Contains($state)){Fail($aid+' representative state is not an entry fixture: '+$state)}
        $winner=Resolve-Winner $machine $state $anchor
        $ordinal++
        [void]$edges.Add([pscustomobject][ordered]@{
            id=('EDGE-{0:D3}' -f $ordinal)
            kind='dispatch_once'
            action=$aid
            state=$state
            fixture=[string]$fixtureByState[$state]
            state_machine_operation=$anchor
            winning_rule=[string]$winner.id
            outcome=[string]$winner.outcome
            priority=[int]$winner.priority
            control_flow_class=[string]$action.control_flow_class
        })
    }else{
        Fail($aid+' has unsupported coverage mode: '+$coverage)
    }
}

# Every action known to the legacy executable entry harness must be owned by the
# control-flow model. This prevents bounded coverage from becoming accidental omission.
if($legacyActions.Count-ne$actionIds.Count){
    $missing=@($legacyActions|Where-Object{-not$actionIds.Contains([string]$_)}|Sort-Object)
    $extra=@($actionIds|Where-Object{-not$legacyActions.Contains([string]$_)}|Sort-Object)
    Fail('Entry action ownership mismatch. missing='+([string]::Join(',',$missing))+' extra='+([string]::Join(',',$extra)))
}

# Prove that each winning-rule action has exactly one representative for every distinct
# winning rule reachable from the declared fixture states.
foreach($action in @($control.actions|Where-Object{[string]$_.coverage-ceq'winning_rule_edges'})){
    $aid=[string]$action.id;$op=[string]$action.state_machine_operation
    $required=New-Set
    foreach($row in @($control.fixture_states)){[void]$required.Add([string](Resolve-Winner $machine ([string]$row.id) $op).id)}
    $actual=New-Set
    foreach($edge in @($edges|Where-Object{[string]$_.action-ceq$aid})){[void]$actual.Add([string]$edge.winning_rule)}
    if($required.Count-ne$actual.Count){Fail($aid+' winning-rule edge cover is incomplete.')}
    foreach($rid in @($required)){if(-not$actual.Contains($rid)){Fail($aid+' omitted winning rule '+$rid)}}
}

$report=[ordered]@{
    schema='keelaryn.manager-entry-plan.v1'
    control_flow_sha256=Sha $controlPath
    state_machine_sha256=Sha $machinePath
    executable_harness_model_sha256=Sha $legacyPath
    fixture_state_count=$fixtureIds.Count
    action_count=$actionIds.Count
    derived_edge_count=$edges.Count
    fixed_scenario_count_requirement=$false
    transaction_fault_injection_included=$false
    generation='one representative per distinct winning state-machine rule for semantic actions; one degraded-state real-dispatch representative for manager-global aliases'
    edges=@($edges)
}

if(-not[string]::IsNullOrWhiteSpace($OutputPath)){
    $OutputPath=[IO.Path]::GetFullPath($OutputPath)
    Write-Json $OutputPath $report
    Write-Host ('Entry plan: '+$OutputPath)
}
Write-Host ('MANAGER ENTRY REACHABILITY PLAN: PASS; states='+$fixtureIds.Count+' actions='+$actionIds.Count+' derived_edges='+$edges.Count) -ForegroundColor Green
Write-Host '  coverage basis: canonical winning rules + explicit real-dispatch aliases'
Write-Host '  fixed scenario count: none'
Write-Host '  transaction fault injection: separate suite'
exit 0
