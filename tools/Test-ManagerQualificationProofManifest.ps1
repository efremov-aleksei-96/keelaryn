[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')

function Fail([string]$Message){throw $Message}
function Read-Json([string]$RelativePath){
    $path=Join-Path $RepositoryRoot ($RelativePath.Replace('/','\'))
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){Fail('Qualification proof dependency missing: '+$RelativePath)}
    try{return Get-Content -LiteralPath $path -Raw -Encoding UTF8|ConvertFrom-Json}
    catch{Fail('Invalid JSON '+$RelativePath+': '+$_.Exception.Message)}
}
function Get-Arguments($Proof){
    if($null-ne$Proof.PSObject.Properties['arguments']){return @($Proof.arguments|ForEach-Object{[string]$_})}
    return @()
}
function Get-Execution($Proof){
    if($null-eq$Proof.PSObject.Properties['execution']){return 'executable'}
    return ([string]$Proof.execution).Trim().ToLowerInvariant()
}
function Get-ScriptParameterNames([string]$RelativePath){
    $path=Join-Path $RepositoryRoot ($RelativePath.Replace('/','\'))
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){Fail('Qualification proof script missing: '+$RelativePath)}
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($path,[ref]$tokens,[ref]$errors)
    if(@($errors).Count-ne0){Fail('Qualification proof parser failed: '+$RelativePath+'; '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
    if($null-eq$ast.ParamBlock){return @()}
    return @($ast.ParamBlock.Parameters|ForEach-Object{[string]$_.Name.VariablePath.UserPath})
}
function Assert-SameSet($Expected,$Actual,[string]$Label){
    $expectedRows=@($Expected|ForEach-Object{([string]$_).Replace('\','/')}|Sort-Object -Unique)
    $actualRows=@($Actual|ForEach-Object{([string]$_).Replace('\','/')}|Sort-Object -Unique)
    if(([string]::Join('|',$expectedRows))-cne([string]::Join('|',$actualRows))){
        Fail($Label+' mismatch. expected='+([string]::Join(',',$expectedRows))+' actual='+([string]::Join(',',$actualRows)))
    }
}

$manifestPath='tests/knowledge/qualification/capability-proofs.json'
$manifest=Read-Json $manifestPath
if([string]$manifest.schema-cne'keelaryn.manager-qualification-proofs.v1'){Fail 'Unexpected qualification proof manifest schema.'}

$byId=@{}
$byPath=@{}
foreach($proof in @($manifest.proofs)){
    $id=([string]$proof.id).Trim()
    $path=([string]$proof.path).Replace('\','/').Trim()
    if([string]::IsNullOrWhiteSpace($id)-or[string]::IsNullOrWhiteSpace($path)){Fail 'Qualification proof id/path must not be empty.'}
    if($byId.ContainsKey($id)){Fail('Duplicate qualification proof id: '+$id)}
    if($byPath.ContainsKey($path)){Fail('Duplicate qualification proof path: '+$path)}
    $byId[$id]=$proof
    $byPath[$path]=$proof

    $execution=Get-Execution $proof
    if(@('executable','static')-cnotcontains$execution){Fail($id+' has unsupported execution mode: '+$execution)}
    $declaredArguments=@(Get-Arguments $proof)
    $capabilities=@($proof.capability_suites|ForEach-Object{[string]$_})

    if($execution-ceq'static'){
        if($declaredArguments.Count-ne0){Fail($id+' static proof must not declare invocation arguments.')}
        if($capabilities.Count-ne0){Fail($id+' static identity proof must not claim behavioral capabilities.')}
    }

    $isLeafId=$id.EndsWith('_leaf',[StringComparison]::Ordinal)
    $declaresLeaf=@($declaredArguments|Where-Object{$_-ceq'-LeafOnly'}).Count-eq1
    if($isLeafId-and-not$declaresLeaf){Fail($id+' must declare exactly one -LeafOnly scheduler argument.')}
    if($declaresLeaf){
        if($execution-cne'executable'){Fail($id+' declares -LeafOnly but is not executable.')}
        if([IO.Path]::GetExtension($path)-ine'.ps1'){Fail($id+' leaf proof is not a PowerShell script.')}
        $parameters=@(Get-ScriptParameterNames $path)
        if($parameters-cnotcontains'LeafOnly'){Fail($id+' declares -LeafOnly but target script has no LeafOnly parameter.')}
    }
}

$mandatory=@($manifest.mandatory_development_proofs|ForEach-Object{[string]$_})
if($mandatory.Count-ne@($mandatory|Sort-Object -Unique).Count){Fail 'mandatory_development_proofs contains duplicates.'}
foreach($id in $mandatory){if(-not$byId.ContainsKey($id)){Fail('Mandatory proof is undeclared: '+$id)}}

$contract=$manifest.execution_contract
if([int]$contract.same_path_same_boundary_max_execution_count-ne1){Fail 'Proof contract must permit each path at most once per boundary.'}
if([bool]$contract.risk_gate_executes_child_proofs){Fail 'Risk Gate child-proof execution must remain disabled.'}
if(-not[bool]$contract.scheduler_receipt_required){Fail 'Scheduler receipt must remain required.'}
if([bool]$contract.fresh_boundary_receipt_reuse_permitted){Fail 'Receipt reuse across fresh trust boundaries must remain prohibited.'}
if(-not[bool]$contract.scheduler_leaf_arguments_are_authoritative){Fail 'Scheduler leaf arguments must remain authoritative.'}
if(-not[bool]$contract.static_identity_proofs_do_not_claim_behavioral_capabilities){Fail 'Static identity proofs must not claim behavioral capabilities.'}
if(-not[bool]$contract.pre_scheduler_meta_validation_is_not_reexecuted_by_scheduler){Fail 'Pre-scheduler meta validation must not be re-executed by scheduler.'}
if([bool]$contract.historical_recursive_sources_execute_directly_in_scheduler){Fail 'Historical recursive source adapters must not execute directly in scheduler.'}
if([string]$contract.historical_behavior_owner-cne'historical_flat_lineage'){Fail 'Historical behavioral ownership must remain historical_flat_lineage.'}

$flat=$byId['historical_flat_lineage']
if($null-eq$flat){Fail 'historical_flat_lineage proof is missing.'}
if((Get-Execution $flat)-cne'executable'){Fail 'historical_flat_lineage must be executable.'}
if($mandatory-cnotcontains'historical_flat_lineage'){Fail 'historical_flat_lineage must be mandatory development coverage.'}
$flatSources=@($flat.source_paths|ForEach-Object{([string]$_).Replace('\','/')})
if($flatSources.Count-eq0){Fail 'historical_flat_lineage has no source_paths.'}
if($flatSources.Count-ne@($flatSources|Sort-Object -Unique).Count){Fail 'historical_flat_lineage source_paths contain duplicates.'}
$declaredHistoricalStatic=@($manifest.proofs|Where-Object{
    ([string]$_.id).StartsWith('historical_',[StringComparison]::Ordinal) -and
    ([string]$_.id)-cne'historical_flat_lineage' -and
    (Get-Execution $_)-ceq'static'
}|ForEach-Object{([string]$_.path).Replace('\','/')}|Where-Object{$_-notlike'*41712*'})
Assert-SameSet $flatSources $declaredHistoricalStatic 'Flat historical source/static-identity set'
foreach($path in $flatSources){
    if(-not$byPath.ContainsKey($path)){Fail('Flat historical source lacks declared static identity proof: '+$path)}
    if((Get-Execution $byPath[$path])-cne'static'){Fail('Flat historical source is not static in scheduler ownership: '+$path)}
    if($mandatory-ccontains[string]$byPath[$path].id){Fail('Recursive historical source adapter must not be a mandatory direct proof: '+$path)}
}
$flatRunnerPath=Join-Path $RepositoryRoot 'tools\Invoke-ManagerHistoricalFlatRegression.ps1'
$flatRunner=[IO.File]::ReadAllText($flatRunnerPath,[Text.Encoding]::UTF8)
foreach($path in $flatSources){
    $name=[IO.Path]::GetFileName($path)
    if(-not$flatRunner.Contains($name)){Fail('Flat runner omits declared historical source: '+$name)}
}
if(-not$flatRunner.Contains('New-LeafCopy')){Fail 'Flat runner does not materialize disposable leaf copies.'}
if(-not$flatRunner.Contains('unique_leaf_proofs')){Fail 'Flat runner does not report unique leaf execution count.'}

$riskMeta=$byId['risk_context_meta_identity']
if($null-eq$riskMeta){Fail 'risk_context_meta_identity proof is missing.'}
if((Get-Execution $riskMeta)-cne'static'){Fail 'risk_context_meta_identity must be static in scheduler ownership.'}
if([string]$riskMeta.meta_validation_owner-cne'tools/Invoke-DevelopmentValidation.ps1:phase2'){Fail 'Risk-context meta-validation owner drifted.'}
$developmentPath=Join-Path $RepositoryRoot 'tools\Invoke-DevelopmentValidation.ps1'
$development=[IO.File]::ReadAllText($developmentPath,[Text.Encoding]::UTF8)
$riskIndex=$development.IndexOf("Invoke-ManagerRiskContextRegression.ps1",[StringComparison]::Ordinal)
$schedulerIndex=$development.IndexOf("Invoke-ManagerQualificationScheduler.ps1",[StringComparison]::Ordinal)
if($riskIndex-lt0-or$schedulerIndex-lt0-or$riskIndex-ge$schedulerIndex){Fail 'Development Validation must execute risk-context meta regression exactly before scheduler ownership.'}

$historical=$byId['review_41712_historical_static']
if($null-eq$historical){Fail 'Version-bound 4.17.12 historical proof is missing.'}
if((Get-Execution $historical)-cne'static'){Fail '4.17.12 version-bound historical proof must be static on the 4.17.13 line.'}
if([string]$historical.historical_version-cne'4.17.12'){Fail '4.17.12 historical proof version identity drifted.'}

Write-Host ('MANAGER QUALIFICATION PROOF MANIFEST: PASS; proofs='+$byId.Count+' mandatory='+$mandatory.Count) -ForegroundColor Green
exit 0
