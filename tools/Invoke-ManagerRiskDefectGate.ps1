[CmdletBinding()]
param(
    [string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'),
    [Parameter(Mandatory=$true)][string]$BaseCommit,
    [string]$HeadCommit='HEAD',
    [string]$OutputDirectory=(Join-Path $env:TEMP 'keelaryn-manager-risk-defect-gate')
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$OutputDirectory=[IO.Path]::GetFullPath($OutputDirectory).TrimEnd('\')
$Utf8NoBom=New-Object Text.UTF8Encoding($false)

function Write-Json([string]$Path,$Object){
    $parent=[IO.Path]::GetDirectoryName($Path)
    if($parent -and -not(Test-Path -LiteralPath $parent -PathType Container)){[void][IO.Directory]::CreateDirectory($parent)}
    [IO.File]::WriteAllText($Path,(($Object|ConvertTo-Json -Depth 60).Replace("`r`n","`n"))+"`n",$Utf8NoBom)
}
function Invoke-Child([string]$Script,[string[]]$Arguments){
    if($null-eq$Arguments){$Arguments=@()}
    $powershell=Join-Path $PSHOME 'powershell.exe'
    $old=$ErrorActionPreference
    try{
        $ErrorActionPreference='Continue'
        $output=@(& $powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Script @Arguments 2>&1)
        $code=[int]$LASTEXITCODE
    }finally{$ErrorActionPreference=$old}
    foreach($line in @($output)){Write-Host ([string]$line)}
    return [pscustomobject]@{ExitCode=$code;Output=@($output|ForEach-Object{[string]$_})}
}
function Add-Failure($List,[string]$Kind,[string]$Id,[string]$Message){
    [void]$List.Add([ordered]@{kind=$Kind;id=$Id;message=$Message})
}

if(Test-Path -LiteralPath $OutputDirectory){Remove-Item -LiteralPath $OutputDirectory -Recurse -Force}
[void][IO.Directory]::CreateDirectory($OutputDirectory)
$failures=New-Object System.Collections.ArrayList
$executed=New-Object System.Collections.ArrayList
$knowledgePass=$false
$contextBuilt=$false
$context=$null

$knowledgeTool=Join-Path $RepositoryRoot 'tools\Test-ManagerEngineeringKnowledge.ps1'
$riskTool=Join-Path $RepositoryRoot 'tools\Build-ManagerRiskContext.ps1'
$riskMd=Join-Path $OutputDirectory 'MANAGER_RISK_CONTEXT.md'
$riskJson=Join-Path $OutputDirectory 'MANAGER_RISK_CONTEXT.json'
$reportPath=Join-Path $OutputDirectory 'RISK_DEFECT_GATE.json'

Write-Host '=== MANAGER RISK / DEFECT GATE ==='
Write-Host ('Base: '+$BaseCommit)
Write-Host ('Head: '+$HeadCommit)
Write-Host ''
Write-Host '[1/4] Validate engineering knowledge...'
$knowledgeRun=Invoke-Child $knowledgeTool @('-RepositoryRoot',$RepositoryRoot)
if($knowledgeRun.ExitCode-ne0){
    Add-Failure $failures 'knowledge_integrity' 'KNOWLEDGE' ('Engineering knowledge validation failed with exit '+$knowledgeRun.ExitCode+'.')
}else{$knowledgePass=$true;Write-Host 'Knowledge integrity: PASS' -ForegroundColor Green}

if($knowledgePass){
    Write-Host '[2/4] Build exact task risk context...'
    $riskRun=Invoke-Child $riskTool @('-RepositoryRoot',$RepositoryRoot,'-BaseCommit',$BaseCommit,'-HeadCommit',$HeadCommit,'-OutputPath',$riskMd)
    if($riskRun.ExitCode-ne0){
        Add-Failure $failures 'risk_context' 'CONTEXT' ('Risk context generation failed with exit '+$riskRun.ExitCode+'.')
    }elseif(-not(Test-Path -LiteralPath $riskJson -PathType Leaf)){
        Add-Failure $failures 'risk_context' 'CONTEXT' 'Risk context JSON was not produced.'
    }else{
        try{$context=Get-Content -LiteralPath $riskJson -Raw -Encoding UTF8|ConvertFrom-Json;$contextBuilt=$true}catch{Add-Failure $failures 'risk_context' 'CONTEXT' ('Risk context JSON is unreadable: '+$_.Exception.Message)}
    }
}

Write-Host '[3/4] Enforce blockers, invariant coverage, and applicable regressions...'
if($contextBuilt){
    foreach($blocker in @($context.global_open_release_blockers)){
        Add-Failure $failures 'open_release_blocker' ([string]$blocker.id) ([string]$blocker.title)
    }
    foreach($inv in @($context.invariants)){
        $coverage=@($inv.coverage|ForEach-Object{[string]$_})
        $implemented=($coverage -contains 'executable') -or ($coverage -contains 'static')
        if(-not$implemented){Add-Failure $failures 'invariant_coverage' ([string]$inv.id) 'Touched invariant has no implemented executable/static coverage.'}
    }
    foreach($relative in @($context.applicable_regressions|ForEach-Object{[string]$_}|Sort-Object -Unique)){
        if([string]::IsNullOrWhiteSpace($relative)){continue}
        $path=Join-Path $RepositoryRoot ($relative.Replace('/','\'))
        if(-not(Test-Path -LiteralPath $path -PathType Leaf)){
            Add-Failure $failures 'regression_missing' $relative 'Applicable permanent regression path is missing.'
            continue
        }
        if([IO.Path]::GetExtension($path)-ine'.ps1'){
            [void]$executed.Add([ordered]@{path=$relative;kind='static';result='present'})
            continue
        }
        $run=Invoke-Child $path @('-RepositoryRoot',$RepositoryRoot)
        [void]$executed.Add([ordered]@{path=$relative;kind='executable';exit_code=$run.ExitCode;result=$(if($run.ExitCode-eq0){'pass'}else{'fail'})})
        if($run.ExitCode-ne0){Add-Failure $failures 'regression_failed' $relative ('Applicable regression failed with exit '+$run.ExitCode+'.')}
    }
}

Write-Host '[4/4] Write compact gate evidence...'
$report=[ordered]@{
    schema='keelaryn.manager-risk-defect-gate.v1'
    classification='pre_freeze_only'
    base_commit=$(if($contextBuilt){[string]$context.base_commit}else{$BaseCommit})
    head_commit=$(if($contextBuilt){[string]$context.head_commit}else{$HeadCommit})
    engineering_knowledge_pass=$knowledgePass
    risk_context_built=$contextBuilt
    matched_surfaces=$(if($contextBuilt){@($context.matched_surfaces)}else{@()})
    applicable_invariants=$(if($contextBuilt){@($context.invariants|ForEach-Object{[string]$_.id})}else{@()})
    global_open_release_blockers=$(if($contextBuilt){@($context.global_open_release_blockers)}else{@()})
    applicable_regressions=$(if($contextBuilt){@($context.applicable_regressions)}else{@()})
    executed_regressions=@($executed)
    failures=@($failures)
    pass=($failures.Count-eq0)
    candidate_freeze_permitted=($failures.Count-eq0)
    production_qualified=$false
    production_hub_used=$false
    completed_utc=[DateTime]::UtcNow.ToString('o')
}
Write-Json $reportPath $report

if($failures.Count-ne0){
    Write-Host ''
    Write-Host 'MANAGER RISK / DEFECT GATE: FAIL' -ForegroundColor Red
    foreach($failure in @($failures)){Write-Host ('  ['+[string]$failure.kind+'] '+[string]$failure.id+': '+[string]$failure.message) -ForegroundColor Red}
    Write-Host ('Evidence: '+$reportPath)
    exit 1
}

Write-Host ''
Write-Host 'MANAGER RISK / DEFECT GATE: PASS' -ForegroundColor Green
Write-Host 'Candidate freeze permitted by risk/defect gate only; normal Source/Full/production qualification remains required.'
Write-Host ('Evidence: '+$reportPath)
exit 0
