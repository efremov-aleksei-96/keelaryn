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
    $unmapped=New-Object System.Collections.ArrayList
    foreach($edge in @($plan.edges)){
        $state=[string]$edge.state
        $action=[string]$edge.action
        if(-not$actionById.ContainsKey($action)){Fail('Legacy migration cross-check lacks action '+$action)}
        $matches=@($legacy.coverage_requirements|Where-Object{
            @($_.states|ForEach-Object{[string]$_})-ccontains$state -and
            @($_.actions|ForEach-Object{[string]$_})-ccontains$action
        })
        if($matches.Count-gt1){Fail('Legacy migration cross-check is ambiguous for '+$state+' x '+$action+'; coverage rows='+$matches.Count)}

        $mode=$null
        $requirement=$null
        $status='unmapped'
        if($matches.Count-eq1){
            $req=$matches[0]
            $mode=[string]$actionById[$action].expected_mode
            if($null-ne$req.PSObject.Properties['expected_mode']-and-not[string]::IsNullOrWhiteSpace([string]$req.expected_mode)){$mode=[string]$req.expected_mode}
            $requirement=[string]$req.id
            $status='mapped'
        }else{
            [void]$unmapped.Add([ordered]@{
                edge_id=[string]$edge.id
                action=$action
                state=$state
                winning_rule=[string]$edge.winning_rule
                canonical_outcome=[string]$edge.outcome
                reason='Legacy Cartesian model contains no coverage row for this canonical bounded edge. No fallback is permitted.'
            })
        }

        [void]$rows.Add([ordered]@{
            edge_id=[string]$edge.id
            kind=[string]$edge.kind
            action=$action
            state=$state
            fixture=[string]$edge.fixture
            state_machine_operation=[string]$edge.state_machine_operation
            winning_rule=[string]$edge.winning_rule
            canonical_outcome=[string]$edge.outcome
            legacy_mapping_status=$status
            legacy_observation_mode=$mode
            legacy_requirement=$requirement
        })
    }

    $mappedRows=@($rows|Where-Object{[string]$_.legacy_mapping_status-ceq'mapped'})
    $byRule=@{}
    foreach($row in $mappedRows){
        $rule=[string]$row.winning_rule
        if(-not$byRule.ContainsKey($rule)){$byRule[$rule]=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)}
        [void]$byRule[$rule].Add([string]$row.legacy_observation_mode)
    }
    foreach($rule in @($byRule.Keys)){
        if($byRule[$rule].Count-ne1){Fail('Mapped canonical winning rule has conflicting legacy observation modes: '+$rule+' => '+([string]::Join(',',@($byRule[$rule]))))}
    }

    $outcomeGroups=New-Object System.Collections.ArrayList
    foreach($outcome in @($rows|ForEach-Object{[string]$_.canonical_outcome}|Sort-Object -Unique)){
        $groupRows=@($rows|Where-Object{[string]$_.canonical_outcome-ceq$outcome})
        $modes=@($groupRows|Where-Object{[string]$_.legacy_mapping_status-ceq'mapped'}|ForEach-Object{[string]$_.legacy_observation_mode}|Sort-Object -Unique)
        $actions=@($groupRows|ForEach-Object{[string]$_.action}|Sort-Object -Unique)
        $missing=@($groupRows|Where-Object{[string]$_.legacy_mapping_status-ceq'unmapped'}).Count
        [void]$outcomeGroups.Add([ordered]@{
            canonical_outcome=$outcome
            legacy_observation_modes=$modes
            actions=$actions
            unmapped_edge_count=$missing
        })
    }

    $derivedCount=@($plan.edges).Count
    $mappedCount=$mappedRows.Count
    $unmappedCount=$unmapped.Count
    if($mappedCount+$unmappedCount-ne$derivedCount){Fail 'Entry oracle migration accounting is incomplete.'}

    $report=[ordered]@{
        schema='keelaryn.manager-entry-oracle-migration-audit.v1'
        semantic_owner='tests/knowledge/state-machines/multi-hub.json'
        planner_owner='tools/Build-ManagerEntryReachabilityPlan.ps1'
        legacy_cross_check_only='tests/knowledge/entry-reachability.json'
        legacy_semantic_ownership=false
        missing_legacy_mapping_is_not_failure=true
        missing_legacy_mapping_must_not_fallback=true
        derived_edge_count=$derivedCount
        mapped_edge_count=$mappedCount
        unmapped_edge_count=$unmappedCount
        migration_complete=($unmappedCount-eq0)
        fixed_scenario_count_requirement=false
        transaction_fault_injection_included=false
        rows=@($rows)
        unmapped_edges=@($unmapped)
        outcome_groups=@($outcomeGroups)
        audit_completed=true
        pass=$true
    }
    if([string]::IsNullOrWhiteSpace($OutputPath)){$OutputPath=Join-Path ([IO.Path]::GetTempPath()) ('MANAGER_ENTRY_ORACLE_MIGRATION_'+[guid]::NewGuid().ToString('N')+'.json')}
    $OutputPath=[IO.Path]::GetFullPath($OutputPath)
    Write-Json $OutputPath $report
    Write-Host ('MANAGER ENTRY ORACLE MIGRATION AUDIT: PASS; edges='+$derivedCount+' mapped='+$mappedCount+' unmapped='+$unmappedCount) -ForegroundColor Green
    foreach($g in @($outcomeGroups)){
        Write-Host ('  '+[string]$g.canonical_outcome+' => '+([string]::Join(',',@($g.legacy_observation_modes)))+' | actions='+([string]::Join(',',@($g.actions)))+' | unmapped='+[string]$g.unmapped_edge_count)
    }
    foreach($gap in @($unmapped)){
        Write-Host ('  UNMAPPED '+[string]$gap.edge_id+' '+[string]$gap.state+' x '+[string]$gap.action+' rule='+[string]$gap.winning_rule+' outcome='+[string]$gap.canonical_outcome) -ForegroundColor Yellow
    }
    Write-Host ('Migration complete: '+($unmappedCount-eq0))
    Write-Host ('Evidence: '+$OutputPath)
}finally{
    if(Test-Path -LiteralPath $tempPlan){Remove-Item -LiteralPath $tempPlan -Force -ErrorAction SilentlyContinue}
}
exit 0
