[CmdletBinding()]
param(
    [string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'),
    [Parameter(Mandatory=$true)][string]$BaseCommit,
    [string]$HeadCommit='HEAD',
    [string]$OutputDirectory=(Join-Path $env:TEMP 'keelaryn-manager-risk-defect-gate'),
    [string]$RiskContextPath='',
    [Parameter(Mandatory=$true)][string]$ExecutionReceiptPath
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$OutputDirectory=[IO.Path]::GetFullPath($OutputDirectory).TrimEnd('\')
$ExecutionReceiptPath=[IO.Path]::GetFullPath($ExecutionReceiptPath)
$Utf8NoBom=New-Object Text.UTF8Encoding($false)

function Write-Json([string]$Path,$Object){
    $parent=[IO.Path]::GetDirectoryName($Path)
    if($parent -and -not(Test-Path -LiteralPath $parent -PathType Container)){
        [void][IO.Directory]::CreateDirectory($parent)
    }
    $text=(($Object|ConvertTo-Json -Depth 60).Replace("`r`n","`n"))+"`n"
    [IO.File]::WriteAllText($Path,$text,$Utf8NoBom)
}
function Sha([string]$Path){
    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){throw('Hash target missing: '+$Path)}
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Invoke-Child([string]$Script,[string[]]$Arguments){
    if($null-eq$Arguments){$Arguments=@()}
    $powershell=Join-Path $PSHOME 'powershell.exe'
    $old=$ErrorActionPreference
    try{
        $ErrorActionPreference='Continue'
        $output=@(& $powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Script @Arguments 2>&1)
        $code=[int]$LASTEXITCODE
    }finally{
        $ErrorActionPreference=$old
    }
    foreach($line in @($output)){Write-Host ([string]$line)}
    return [pscustomobject]@{ExitCode=$code;Output=@($output|ForEach-Object{[string]$_})}
}
function Invoke-GitOne([string[]]$Arguments){
    $old=$ErrorActionPreference
    try{
        $ErrorActionPreference='Continue'
        $out=@(& git.exe -C $RepositoryRoot @Arguments 2>&1)
        $code=[int]$LASTEXITCODE
    }finally{
        $ErrorActionPreference=$old
    }
    if($code-ne0-or$out.Count-ne1){throw('git '+($Arguments-join' ')+' failed: '+([string]::Join(' | ',@($out))))}
    return ([string]$out[0]).Trim().ToLowerInvariant()
}
function Add-Failure($List,[string]$Kind,[string]$Id,[string]$Message){
    [void]$List.Add([ordered]@{kind=$Kind;id=$Id;message=$Message})
}
function Get-RowId($Value){
    if($null-eq$Value){return ''}
    if($Value-is[string]){return [string]$Value}
    if($null-ne$Value.PSObject.Properties['id']){return [string]$Value.id}
    return [string]$Value
}
function New-OrdinalSet(){
    return New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
}

if(Test-Path -LiteralPath $OutputDirectory){Remove-Item -LiteralPath $OutputDirectory -Recurse -Force}
[void][IO.Directory]::CreateDirectory($OutputDirectory)

$failures=New-Object System.Collections.ArrayList
$knowledgePass=$false
$contextBuilt=$false
$receiptVerified=$false
$context=$null
$receipt=$null

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
}else{
    $knowledgePass=$true
    Write-Host 'Knowledge integrity: PASS' -ForegroundColor Green
}

if($knowledgePass){
    Write-Host '[2/4] Load/build exact task risk context...'
    if(-not[string]::IsNullOrWhiteSpace($RiskContextPath)){
        $RiskContextPath=[IO.Path]::GetFullPath($RiskContextPath)
        if(-not(Test-Path -LiteralPath $RiskContextPath -PathType Leaf)){
            Add-Failure $failures 'risk_context' 'CONTEXT' ('Provided risk context is missing: '+$RiskContextPath)
        }else{
            try{
                $context=Get-Content -LiteralPath $RiskContextPath -Raw -Encoding UTF8|ConvertFrom-Json
                $contextBuilt=$true
            }catch{
                Add-Failure $failures 'risk_context' 'CONTEXT' ('Provided risk context JSON is unreadable: '+$_.Exception.Message)
            }
        }
    }else{
        $riskRun=Invoke-Child $riskTool @('-RepositoryRoot',$RepositoryRoot,'-BaseCommit',$BaseCommit,'-HeadCommit',$HeadCommit,'-OutputPath',$riskMd)
        if($riskRun.ExitCode-ne0){
            Add-Failure $failures 'risk_context' 'CONTEXT' ('Risk context generation failed with exit '+$riskRun.ExitCode+'.')
        }elseif(-not(Test-Path -LiteralPath $riskJson -PathType Leaf)){
            Add-Failure $failures 'risk_context' 'CONTEXT' 'Risk context JSON was not produced.'
        }else{
            try{
                $context=Get-Content -LiteralPath $riskJson -Raw -Encoding UTF8|ConvertFrom-Json
                $RiskContextPath=$riskJson
                $contextBuilt=$true
            }catch{
                Add-Failure $failures 'risk_context' 'CONTEXT' ('Risk context JSON is unreadable: '+$_.Exception.Message)
            }
        }
    }
}

Write-Host '[3/4] Enforce blockers/invariant coverage and verify exact execution receipt...'
if($contextBuilt){
    $resolvedBase=Invoke-GitOne @('rev-parse','--verify',($BaseCommit+'^{commit}'))
    $resolvedHead=Invoke-GitOne @('rev-parse','--verify',($HeadCommit+'^{commit}'))
    if([string]$context.base_commit-cne$resolvedBase){
        Add-Failure $failures 'risk_context' 'BASE_IDENTITY' 'Risk context base commit does not match requested gate base.'
    }
    if([string]$context.head_commit-cne$resolvedHead){
        Add-Failure $failures 'risk_context' 'HEAD_IDENTITY' 'Risk context head commit does not match requested gate head.'
    }

    foreach($blocker in @($context.global_open_release_blockers)){
        Add-Failure $failures 'open_release_blocker' ([string]$blocker.id) ([string]$blocker.title)
    }
    foreach($inv in @($context.invariants)){
        $coverage=@($inv.coverage|ForEach-Object{[string]$_})
        $implemented=($coverage -contains 'executable') -or ($coverage -contains 'static')
        if(-not$implemented){
            Add-Failure $failures 'invariant_coverage' ([string]$inv.id) 'Touched invariant has no implemented executable/static coverage.'
        }
    }

    if(-not(Test-Path -LiteralPath $ExecutionReceiptPath -PathType Leaf)){
        Add-Failure $failures 'execution_receipt' 'RECEIPT_MISSING' ('Qualification scheduler receipt is missing: '+$ExecutionReceiptPath)
    }else{
        try{
            $receipt=Get-Content -LiteralPath $ExecutionReceiptPath -Raw -Encoding UTF8|ConvertFrom-Json
        }catch{
            Add-Failure $failures 'execution_receipt' 'RECEIPT_JSON' ('Qualification scheduler receipt is unreadable: '+$_.Exception.Message)
        }
    }

    if($null-ne$receipt){
        if([string]$receipt.schema-cne'keelaryn.manager-qualification-execution-receipt.v1'){
            Add-Failure $failures 'execution_receipt' 'RECEIPT_SCHEMA' ('Unexpected scheduler receipt schema: '+[string]$receipt.schema)
        }
        if([string]$receipt.exact_source_commit-cne[string]$context.head_commit){
            Add-Failure $failures 'execution_receipt' 'RECEIPT_COMMIT' 'Scheduler receipt is not bound to risk-context head.'
        }
        $expectedTree=Invoke-GitOne @('rev-parse','--verify',([string]$context.head_commit+'^{tree}'))
        if([string]$receipt.exact_source_tree-cne$expectedTree){
            Add-Failure $failures 'execution_receipt' 'RECEIPT_TREE' 'Scheduler receipt source tree does not match exact risk-context head tree.'
        }
        $riskSha=Sha $RiskContextPath
        if([string]$receipt.risk_context_identity.sha256-cne$riskSha){
            Add-Failure $failures 'execution_receipt' 'RECEIPT_RISK_CONTEXT' 'Scheduler receipt risk-context digest mismatch.'
        }
        $rangeMismatch=([string]$receipt.risk_context_identity.base_commit-cne[string]$context.base_commit) -or ([string]$receipt.risk_context_identity.head_commit-cne[string]$context.head_commit)
        if($rangeMismatch){
            Add-Failure $failures 'execution_receipt' 'RECEIPT_RANGE' 'Scheduler receipt risk range does not match the gate context.'
        }
        if([int]$receipt.duplicate_execution_count-ne0){
            Add-Failure $failures 'execution_receipt' 'RECEIPT_DUPLICATE' 'Scheduler receipt reports duplicate proof execution.'
        }

        $selected=New-OrdinalSet
        foreach($path0 in @($receipt.selected_proof_paths|ForEach-Object{[string]$_})){
            $path=$path0.Replace('\','/')
            if(-not$selected.Add($path)){
                Add-Failure $failures 'execution_receipt' 'RECEIPT_SELECTED_DUPLICATE' ('Duplicate selected proof path: '+$path)
            }
        }

        $executed=New-OrdinalSet
        foreach($proof in @($receipt.executed_proofs)){
            $path=([string]$proof.path).Replace('\','/')
            if(-not$executed.Add($path)){
                Add-Failure $failures 'execution_receipt' 'RECEIPT_EXECUTED_DUPLICATE' ('Proof executed more than once in receipt: '+$path)
            }
            if([string]$proof.result-cne'pass'){
                Add-Failure $failures 'regression_failed' $path ('Scheduler proof result is '+[string]$proof.result+'.')
            }
        }

        foreach($relative0 in @($context.applicable_regressions|ForEach-Object{[string]$_}|Sort-Object -Unique)){
            if([string]::IsNullOrWhiteSpace($relative0)){continue}
            $relative=$relative0.Replace('\','/')
            if(-not$selected.Contains($relative)){
                Add-Failure $failures 'execution_receipt' $relative 'Risk-selected regression is absent from scheduler selection.'
            }
            if(-not$executed.Contains($relative)){
                Add-Failure $failures 'execution_receipt' $relative 'Risk-selected regression is absent from scheduler execution.'
            }
        }

        $requiredIds=New-OrdinalSet
        foreach($surface in @($context.matched_surfaces)){
            $id=Get-RowId $surface
            if(-not[string]::IsNullOrWhiteSpace($id)){[void]$requiredIds.Add('SURFACE:'+$id)}
        }
        foreach($inv in @($context.invariants)){
            $id=Get-RowId $inv
            if(-not[string]::IsNullOrWhiteSpace($id)){[void]$requiredIds.Add('INVARIANT:'+$id)}
        }
        foreach($blocker in @($context.global_open_release_blockers)){
            $id=Get-RowId $blocker
            if(-not[string]::IsNullOrWhiteSpace($id)){[void]$requiredIds.Add('BLOCKER:'+$id)}
        }
        foreach($relative in @($context.applicable_regressions|ForEach-Object{[string]$_}|Sort-Object -Unique)){
            if(-not[string]::IsNullOrWhiteSpace($relative)){[void]$requiredIds.Add('REGRESSION:'+$relative.Replace('\','/'))}
        }

        $receiptIds=New-OrdinalSet
        foreach($id0 in @($receipt.selected_requirement_ids|ForEach-Object{[string]$_})){
            [void]$receiptIds.Add($id0)
        }
        foreach($id in @($requiredIds)){
            if(-not$receiptIds.Contains($id)){
                Add-Failure $failures 'execution_receipt' $id 'Scheduler receipt omitted a gate-selected requirement id.'
            }
        }
        if(-not[bool]$receipt.pass){
            Add-Failure $failures 'execution_receipt' 'RECEIPT_FAIL' 'Qualification scheduler did not report PASS.'
        }

        $receiptFailures=@($failures|Where-Object{
            ([string]$_.kind-ceq'execution_receipt') -or ([string]$_.kind-ceq'regression_failed')
        })
        if($receiptFailures.Count-eq0){
            $receiptVerified=$true
            Write-Host 'Qualification execution receipt: PASS' -ForegroundColor Green
        }
    }
}

Write-Host '[4/4] Write compact gate evidence...'
if($contextBuilt){
    $reportBase=[string]$context.base_commit
    $reportHead=[string]$context.head_commit
    $matchedSurfaces=@($context.matched_surfaces)
    $applicableInvariants=@($context.invariants|ForEach-Object{[string]$_.id})
    $openBlockers=@($context.global_open_release_blockers)
    $applicableRegressions=@($context.applicable_regressions)
}else{
    $reportBase=$BaseCommit
    $reportHead=$HeadCommit
    $matchedSurfaces=@()
    $applicableInvariants=@()
    $openBlockers=@()
    $applicableRegressions=@()
}
if($null-ne$receipt){$executedRegressions=@($receipt.executed_proofs)}else{$executedRegressions=@()}

$report=[ordered]@{
    schema='keelaryn.manager-risk-defect-gate.v2'
    classification='pre_freeze_only'
    base_commit=$reportBase
    head_commit=$reportHead
    engineering_knowledge_pass=$knowledgePass
    risk_context_built=$contextBuilt
    execution_receipt_verified=$receiptVerified
    execution_receipt_path=$ExecutionReceiptPath
    matched_surfaces=$matchedSurfaces
    applicable_invariants=$applicableInvariants
    global_open_release_blockers=$openBlockers
    applicable_regressions=$applicableRegressions
    executed_regressions=$executedRegressions
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
    foreach($failure in @($failures)){
        Write-Host ('  ['+[string]$failure.kind+'] '+[string]$failure.id+': '+[string]$failure.message) -ForegroundColor Red
    }
    Write-Host ('Evidence: '+$reportPath)
    exit 1
}

Write-Host ''
Write-Host 'MANAGER RISK / DEFECT GATE: PASS' -ForegroundColor Green
Write-Host 'Candidate freeze permitted by risk/defect gate only; normal Source/Full/production qualification remains required.'
Write-Host ('Evidence: '+$reportPath)
exit 0
