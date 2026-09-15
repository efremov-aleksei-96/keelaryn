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
function Write-Json([string]$Path,$Object){
    $parent=Split-Path -Parent $Path
    if($parent-and-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
    [IO.File]::WriteAllText($Path,(($Object|ConvertTo-Json -Depth 40).Replace("`r`n","`n"))+"`n",$Utf8NoBom)
}
function Read-Json([string]$Relative){
    $path=Join-Path $RepositoryRoot ($Relative.Replace('/','\'))
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){Fail('Entry oracle migration dependency missing: '+$Relative)}
    try{return Get-Content -LiteralPath $path -Raw -Encoding UTF8|ConvertFrom-Json}catch{Fail('Invalid JSON '+$Relative+': '+$_.Exception.Message)}
}
function Invoke-Plan([string]$Path){
    $tool=Join-Path $RepositoryRoot 'tools\Build-ManagerEntryReachabilityPlan.ps1'
    $exe=Join-Path $PSHOME 'powershell.exe'
    & $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $tool -RepositoryRoot $RepositoryRoot -OutputPath $Path
    if($LASTEXITCODE-ne0){Fail('Bounded entry planner failed with exit '+$LASTEXITCODE)}
}

$tempPlan=Join-Path ([IO.Path]::GetTempPath()) ('MANAGER_ENTRY_PLAN_ORACLE_'+[guid]::NewGuid().ToString('N')+'.json')
try{
    Invoke-Plan $tempPlan
    $plan=Get-Content -LiteralPath $tempPlan -Raw -Encoding UTF8|ConvertFrom-Json
    if([string]$plan.schema-cne'keelaryn.manager-entry-plan.v1'){Fail 'Unexpected bounded entry plan schema.'}
    if([bool]$plan.fixed_scenario_count_requirement){Fail 'Bounded planner must not require a fixed scenario count.'}
    if([bool]$plan.transaction_fault_injection_included){Fail 'Bounded planner must exclude transaction fault injection.'}

    $legacy=Read-Json 'tests/knowledge/entry-reachability.json'
    if([string]$legacy.schema-cne'keelaryn.manager-entry-reachability.v2'){Fail 'Unexpected legacy entry model schema.'}
    $actionById=@{}
    foreach($action in @($legacy.actions)){$actionById[[string]$action.id]=$action}

    $rows=New-Object System.Collections.ArrayList
    foreach($edge in @($plan.edges)){
        $state=[string]$edge.state
        $action=[string]$edge.action
        if(-not$actionById.ContainsKey($action)){Fail('Legacy migration cross-check lacks action '+$action)}
        $matches=@($legacy.coverage_requirements|Where-Object{
            @($_.states|ForEach-Object{[string]$_})-ccontains$state -and
            @($_.actions|ForEach-Object{[string]$_})-ccontains$action
        })
        if($matches.Count-ne1){Fail('Legacy migration cross-check requires exactly one coverage row for '+$state+' x '+$action+'; actual='+$matches.Count)}
        $req=$matches[0]
        $mode=[string]$actionById[$action].expected_mode
        if($null-ne$req.PSObject.Properties['expected_mode']-and-not[string]::IsNullOrWhiteSpace([string]$req.expected_mode)){$mode=[string]$req.expected_mode}
        [void]$rows.Add([ordered]@{
            edge_id=[string]$edge.id
            kind=[string]$edge.kind
            action=$action
            state=$state
            fixture=[string]$edge.fixture
            state_machine_operation=[string]$edge.state_machine_operation
            winning_rule=[string]$edge.winning_rule
            canonical_outcome=[string]$edge.outcome
            legacy_observation_mode=$mode
            legacy_requirement=[string]$req.id
        })
    }

    $byRule=@{}
    foreach($row in @($rows)){
        $rule=[string]$row.winning_rule
        if(-not$byRule.ContainsKey($rule)){$byRule[$rule]=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)}
        [void]$byRule[$rule].Add([string]$row.legacy_observation_mode)
    }
    foreach($rule in @($byRule.Keys)){
        if($byRule[$rule].Count-ne1){Fail('Canonical winning rule maps to multiple legacy observation modes: '+$rule+' => '+([string]::Join(',',@($byRule[$rule]))))}
    }

    $outcomeGroups=New-Object System.Collections.ArrayList
    foreach($outcome in @($rows|ForEach-Object{[string]$_.canonical_outcome}|Sort-Object -Unique)){
        $modes=@($rows|Where-Object{[string]$_.canonical_outcome-ceq$outcome}|ForEach-Object{[string]$_.legacy_observation_mode}|Sort-Object -Unique)
        $actions=@($rows|Where-Object{[string]$_.canonical_outcome-ceq$outcome}|ForEach-Object{[string]$_.action}|Sort-Object -Unique)
        [void]$outcomeGroups.Add([ordered]@{canonical_outcome=$outcome;legacy_observation_modes=$modes;actions=$actions})
    }

    $report=[ordered]@{
        schema='keelaryn.manager-entry-oracle-migration-audit.v1'
        semantic_owner='tests/knowledge/state-machines/multi-hub.json'
        planner_owner='tools/Build-ManagerEntryReachabilityPlan.ps1'
        legacy_cross_check_only='tests/knowledge/entry-reachability.json'
        legacy_semantic_ownership=false
        derived_edge_count=@($rows).Count
        fixed_scenario_count_requirement=false
        transaction_fault_injection_included=false
        rows=@($rows)
        outcome_groups=@($outcomeGroups)
        pass=$true
    }
    if([string]::IsNullOrWhiteSpace($OutputPath)){$OutputPath=Join-Path ([IO.Path]::GetTempPath()) ('MANAGER_ENTRY_ORACLE_MIGRATION_'+[guid]::NewGuid().ToString('N')+'.json')}
    $OutputPath=[IO.Path]::GetFullPath($OutputPath)
    Write-Json $OutputPath $report
    Write-Host ('MANAGER ENTRY ORACLE MIGRATION AUDIT: PASS; edges='+@($rows).Count+' outcomes='+@($outcomeGroups).Count) -ForegroundColor Green
    foreach($g in @($outcomeGroups)){
        Write-Host ('  '+[string]$g.canonical_outcome+' => '+([string]::Join(',',@($g.legacy_observation_modes)))+' | actions='+([string]::Join(',',@($g.actions))))
    }
    Write-Host ('Evidence: '+$OutputPath)
}finally{
    if(Test-Path -LiteralPath $tempPlan){Remove-Item -LiteralPath $tempPlan -Force -ErrorAction SilentlyContinue}
}
exit 0
