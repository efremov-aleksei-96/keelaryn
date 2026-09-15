[CmdletBinding()]
param(
    [string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'),
    [Parameter(Mandatory=$true)][string]$RiskContextPath,
    [string]$OutputPath=''
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$RiskContextPath=[IO.Path]::GetFullPath($RiskContextPath)
$Utf8NoBom=New-Object Text.UTF8Encoding($false)

function Fail([string]$Message){throw $Message}
function Write-Json([string]$Path,$Object){
    $parent=[IO.Path]::GetDirectoryName($Path)
    if($parent-and-not(Test-Path -LiteralPath $parent -PathType Container)){[void][IO.Directory]::CreateDirectory($parent)}
    [IO.File]::WriteAllText($Path,(($Object|ConvertTo-Json -Depth 60).Replace("`r`n","`n"))+"`n",$Utf8NoBom)
}
function Sha([string]$Path){
    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){Fail('Hash target missing: '+$Path)}
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Invoke-GitOne([string[]]$Arguments){
    $old=$ErrorActionPreference
    try{$ErrorActionPreference='Continue';$out=@(& git.exe -C $RepositoryRoot @Arguments 2>&1);$code=[int]$LASTEXITCODE}finally{$ErrorActionPreference=$old}
    if($code-ne0-or$out.Count-ne1){Fail('git '+($Arguments-join' ')+' failed: '+([string]::Join(' | ',@($out))))}
    return ([string]$out[0]).Trim().ToLowerInvariant()
}
function Invoke-Proof([string]$Script,[string[]]$Arguments){
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
function Add-Requirement($Set,[string]$Value){if(-not[string]::IsNullOrWhiteSpace($Value)){[void]$Set.Add($Value)}}
function Get-RowId($Value){
    if($null-eq$Value){return ''}
    if($Value-is[string]){return [string]$Value}
    if($null-ne$Value.PSObject.Properties['id']){return [string]$Value.id}
    return [string]$Value
}

$manifestPath=Join-Path $RepositoryRoot 'tests\knowledge\qualification\capability-proofs.json'
if(-not(Test-Path -LiteralPath $manifestPath -PathType Leaf)){Fail('Qualification proof manifest missing: '+$manifestPath)}
if(-not(Test-Path -LiteralPath $RiskContextPath -PathType Leaf)){Fail('Risk context missing: '+$RiskContextPath)}
$manifest=Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8|ConvertFrom-Json
$context=Get-Content -LiteralPath $RiskContextPath -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$manifest.schema-cne'keelaryn.manager-qualification-proofs.v1'){Fail('Unsupported qualification proof manifest schema: '+[string]$manifest.schema)}

$head=Invoke-GitOne @('rev-parse','--verify','HEAD^{commit}')
$tree=Invoke-GitOne @('rev-parse','--verify','HEAD^{tree}')
if([string]$context.head_commit-cne$head){Fail('Risk context head does not equal exact scheduler HEAD. context='+[string]$context.head_commit+' head='+$head)}
$riskSha=Sha $RiskContextPath

$proofById=@{}
$proofByPath=@{}
foreach($proof in @($manifest.proofs)){
    $id=[string]$proof.id;$path=([string]$proof.path).Replace('\','/')
    if([string]::IsNullOrWhiteSpace($id)-or[string]::IsNullOrWhiteSpace($path)){Fail 'Qualification proof manifest contains an empty id/path.'}
    if($proofById.ContainsKey($id)){Fail('Duplicate qualification proof id: '+$id)}
    if($proofByPath.ContainsKey($path)){Fail('Duplicate qualification proof path: '+$path)}
    $proofById[$id]=$proof;$proofByPath[$path]=$proof
}

$historicalCapabilities=@{}
foreach($property in @($manifest.historical_path_capabilities.PSObject.Properties)){
    $historicalCapabilities[[string]$property.Name]=@($property.Value|ForEach-Object{[string]$_})
}

$selected=New-Object System.Collections.Specialized.OrderedDictionary ([StringComparer]::OrdinalIgnoreCase)
function Select-Proof([string]$Id,[string]$Path,[string[]]$Suites,[string]$Reason){
    $canonical=$Path.Replace('\','/')
    if([string]::IsNullOrWhiteSpace($canonical)){Fail('Selected proof path is empty for '+$Id)}
    if($selected.Contains($canonical)){
        $existing=$selected[$canonical]
        foreach($suite in @($Suites)){if(@($existing.CapabilitySuites)-cnotcontains$suite){$existing.CapabilitySuites+=,$suite}}
        $existing.Reasons+=,$Reason
        return
    }
    $selected.Add($canonical,[pscustomobject]@{
        Id=$Id
        Path=$canonical
        CapabilitySuites=@($Suites|Sort-Object -Unique)
        Reasons=@($Reason)
    })
}

foreach($mandatoryId in @($manifest.mandatory_development_proofs|ForEach-Object{[string]$_})){
    if(-not$proofById.ContainsKey($mandatoryId)){Fail('Mandatory qualification proof id is not declared: '+$mandatoryId)}
    $p=$proofById[$mandatoryId]
    Select-Proof $mandatoryId ([string]$p.path) @($p.capability_suites|ForEach-Object{[string]$_}) 'mandatory_development'
}

foreach($relative0 in @($context.applicable_regressions|ForEach-Object{[string]$_}|Sort-Object -Unique)){
    if([string]::IsNullOrWhiteSpace($relative0)){continue}
    $relative=$relative0.Replace('\','/')
    if($proofByPath.ContainsKey($relative)){
        $p=$proofByPath[$relative]
        Select-Proof ([string]$p.id) $relative @($p.capability_suites|ForEach-Object{[string]$_}) 'risk_selected'
    }elseif($historicalCapabilities.ContainsKey($relative)){
        $dynamicId='risk::'+$relative
        Select-Proof $dynamicId $relative @($historicalCapabilities[$relative]) 'risk_selected'
    }else{
        $candidate=Join-Path $RepositoryRoot ($relative.Replace('/','\'))
        $isStatic=(Test-Path -LiteralPath $candidate -PathType Leaf)-and([IO.Path]::GetExtension($candidate)-ine'.ps1')
        if($isStatic){
            Select-Proof ('static::'+$relative) $relative @() 'risk_selected_static'
        }else{
            Fail('Risk-selected executable regression lacks qualification ownership mapping: '+$relative)
        }
    }
}

$requirements=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
foreach($surface in @($context.matched_surfaces)){Add-Requirement $requirements ('SURFACE:'+ (Get-RowId $surface))}
foreach($inv in @($context.invariants)){Add-Requirement $requirements ('INVARIANT:'+ (Get-RowId $inv))}
foreach($blocker in @($context.global_open_release_blockers)){Add-Requirement $requirements ('BLOCKER:'+ (Get-RowId $blocker))}
foreach($relative in @($context.applicable_regressions|ForEach-Object{[string]$_}|Sort-Object -Unique)){if(-not[string]::IsNullOrWhiteSpace($relative)){Add-Requirement $requirements ('REGRESSION:'+$relative.Replace('\','/'))}}

$capabilities=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
$executed=New-Object System.Collections.ArrayList
$failures=New-Object System.Collections.ArrayList
$seenExecution=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)

Write-Host '=== MANAGER QUALIFICATION SCHEDULER ==='
Write-Host ('HEAD: '+$head)
Write-Host ('Tree: '+$tree)
Write-Host ('Risk context: '+$riskSha)
Write-Host ('Unique selected proofs: '+$selected.Count)

foreach($key in @($selected.Keys)){
    $proof=$selected[$key]
    if(-not$seenExecution.Add([string]$proof.Path)){Fail('Scheduler duplicate execution attempt: '+[string]$proof.Path)}
    foreach($suite in @($proof.CapabilitySuites)){if(-not[string]::IsNullOrWhiteSpace([string]$suite)){[void]$capabilities.Add([string]$suite)}}
    $path=Join-Path $RepositoryRoot (([string]$proof.Path).Replace('/','\'))
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){
        [void]$failures.Add([ordered]@{id=[string]$proof.Id;path=[string]$proof.Path;kind='missing';message='Selected proof path is missing.'})
        [void]$executed.Add([ordered]@{id=[string]$proof.Id;path=[string]$proof.Path;capability_suites=@($proof.CapabilitySuites);reasons=@($proof.Reasons);kind='missing';result='fail';exit_code=$null})
        continue
    }
    if([IO.Path]::GetExtension($path)-ine'.ps1'){
        [void]$executed.Add([ordered]@{id=[string]$proof.Id;path=[string]$proof.Path;capability_suites=@($proof.CapabilitySuites);reasons=@($proof.Reasons);kind='static';result='pass';exit_code=$null;sha256=Sha $path})
        Write-Host ('  PASS '+[string]$proof.Id+' ['+[string]$proof.Path+']') -ForegroundColor Green
        continue
    }
    Write-Host ('--- '+[string]$proof.Id+' :: '+[string]$proof.Path+' ---')
    $run=Invoke-Proof $path @('-RepositoryRoot',$RepositoryRoot)
    $pass=($run.ExitCode-eq0)
    [void]$executed.Add([ordered]@{id=[string]$proof.Id;path=[string]$proof.Path;capability_suites=@($proof.CapabilitySuites);reasons=@($proof.Reasons);kind='executable';result=$(if($pass){'pass'}else{'fail'});exit_code=$run.ExitCode;sha256=Sha $path})
    if(-not$pass){[void]$failures.Add([ordered]@{id=[string]$proof.Id;path=[string]$proof.Path;kind='execution';message=('Proof exited '+$run.ExitCode+'.')})}
}

if([string]::IsNullOrWhiteSpace($OutputPath)){$OutputPath=Join-Path ([IO.Path]::GetTempPath()) ('MANAGER_QUALIFICATION_EXECUTION_RECEIPT_'+[guid]::NewGuid().ToString('N')+'.json')}
$OutputPath=[IO.Path]::GetFullPath($OutputPath)
$receipt=[ordered]@{
    schema='keelaryn.manager-qualification-execution-receipt.v1'
    classification='development_trust_boundary'
    exact_source_commit=$head
    exact_source_tree=$tree
    risk_context_identity=[ordered]@{
        sha256=$riskSha
        base_commit=[string]$context.base_commit
        head_commit=[string]$context.head_commit
    }
    proof_manifest_sha256=Sha $manifestPath
    selected_requirement_ids=@($requirements|Sort-Object)
    selected_capability_suite_ids=@($capabilities|Sort-Object)
    selected_proof_paths=@($selected.Keys|ForEach-Object{[string]$_})
    executed_proof_ids=@($executed|ForEach-Object{[string]$_.id})
    executed_proofs=@($executed)
    duplicate_execution_count=0
    failures=@($failures)
    pass=($failures.Count-eq0)
    production_qualified=$false
    production_hub_used=$false
    completed_utc=[DateTime]::UtcNow.ToString('o')
}
Write-Json $OutputPath $receipt
Write-Host ('Receipt: '+$OutputPath)
if($failures.Count-ne0){
    Write-Host ('MANAGER QUALIFICATION SCHEDULER: FAIL; failures='+$failures.Count) -ForegroundColor Red
    exit 1
}
Write-Host ('MANAGER QUALIFICATION SCHEDULER: PASS; unique_proofs='+$executed.Count+' capabilities='+$capabilities.Count) -ForegroundColor Green
exit 0
