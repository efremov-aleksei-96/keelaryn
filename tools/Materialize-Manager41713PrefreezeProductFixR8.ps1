[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RepositoryRoot,
    [Parameter(Mandatory=$true)][string]$ExpectedBase,
    [string]$EvidenceRoot=''
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$ExpectedBase=$ExpectedBase.Trim().ToLowerInvariant()
$Utf8NoBom=New-Object Text.UTF8Encoding($false)
if([string]::IsNullOrWhiteSpace($EvidenceRoot)){$EvidenceRoot=Join-Path $env:RUNNER_TEMP 'manager-41713-prefreeze-product-r8'}
New-Item -ItemType Directory -Force -Path $EvidenceRoot|Out-Null

function Fail([string]$Message){throw $Message}
function Write-Utf8([string]$Path,[string]$Text){[IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)}
function Write-Json([string]$Path,$Object,[int]$Depth=50){Write-Utf8 $Path ((($Object|ConvertTo-Json -Depth $Depth).Replace("`r`n","`n"))+"`n")}
function Parse-Ast([string]$Path){
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors)
    if(@($errors).Count-ne0){Fail('Parser failed: '+$Path+' :: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
    return $ast
}
function Invoke-Child([string]$Script,[string[]]$Arguments,[string]$Purpose){
    $exe=Join-Path $PSHOME 'powershell.exe';$old=$ErrorActionPreference
    try{$ErrorActionPreference='Continue';$out=@(& $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Script @Arguments 2>&1|ForEach-Object{[string]$_});$code=[int]$LASTEXITCODE}finally{$ErrorActionPreference=$old}
    foreach($line in @($out)){Write-Host $line}
    if($code-ne0){Fail($Purpose+' failed; exit='+$code+'; output='+([string]::Join(' | ',@($out))))}
    return [pscustomobject]@{ExitCode=$code;Text=[string]::Join("`n",@($out))}
}
function Add-UniqueString($Object,[string]$Property,[string]$Value){
    $values=@($Object.$Property|ForEach-Object{[string]$_})
    if($values-cnotcontains$Value){$Object.$Property=@($values)+@($Value)}
}
function Add-PropertyIfMissing($Object,[string]$Name,$Value){
    if($null-eq$Object.PSObject.Properties[$Name]){$Object|Add-Member -NotePropertyName $Name -NotePropertyValue $Value}
    else{$Object.$Name=$Value}
}

$head=(& git.exe -C $RepositoryRoot rev-parse HEAD).Trim().ToLowerInvariant()
if($head-cne$ExpectedBase){Fail('Unexpected target HEAD: '+$head+' expected='+$ExpectedBase)}
if(@(& git.exe -C $RepositoryRoot status --porcelain).Count-ne0){Fail 'Target checkout is not clean before R8 product materialization.'}

$runtimePath=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1'
$defectPath=Join-Path $RepositoryRoot 'tests\knowledge\defects\manager-4.17.13-prefreeze.json'
$riskPath=Join-Path $RepositoryRoot 'tests\knowledge\risk-map.json'
$manifestBuilder=Join-Path $RepositoryRoot 'tools\Build-PublicFileManifest.ps1'
$manifestPath=Join-Path $RepositoryRoot 'PUBLIC_FILE_MANIFEST.json'
$provenancePath=Join-Path $RepositoryRoot 'PUBLIC_PROVENANCE.json'
$metadataVerifier=Join-Path $RepositoryRoot 'tools\Verify-PublicCandidateMetadata.ps1'
$engineeringVerifier=Join-Path $RepositoryRoot 'tools\Test-ManagerEngineeringKnowledge.ps1'
foreach($p in @($runtimePath,$riskPath,$manifestBuilder,$manifestPath,$provenancePath,$metadataVerifier,$engineeringVerifier)){if(-not(Test-Path -LiteralPath $p -PathType Leaf)){Fail('Required R8 path missing: '+$p)}}
if(Test-Path -LiteralPath $defectPath){Fail('R8 defect record already exists unexpectedly: '+$defectPath)}

# The RED proof showed that Windows PowerShell 5.1 overwrites a function parameter named
# $Input with the automatic $input enumerator. Prove that the runtime has exactly one such
# function parameter before correction and no such parameter after correction.
$ast=Parse-Ast $runtimePath
$inputParamFunctions=New-Object System.Collections.ArrayList
foreach($fn in @($ast.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]},$true))){
    foreach($param in @($fn.Parameters)){
        if([string]$param.Name.VariablePath.UserPath-ieq'Input'){[void]$inputParamFunctions.Add([string]$fn.Name)}
    }
}
if($inputParamFunctions.Count-ne1-or[string]$inputParamFunctions[0]-cne'Get-GlobalHubInputIdentity'){
    Fail('R8 expected exactly one runtime function parameter named $Input in Get-GlobalHubInputIdentity; observed='+([string]::Join(',',@($inputParamFunctions))))
}
$fnRows=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-ceq'Get-GlobalHubInputIdentity'},$true))
if($fnRows.Count-ne1){Fail('Get-GlobalHubInputIdentity function count='+$fnRows.Count)}
$fn=$fnRows[0];$runtime=[IO.File]::ReadAllText($runtimePath,[Text.Encoding]::UTF8);$fnText=[string]$fn.Extent.Text
$inputRefs=[regex]::Matches($fnText,'(?i)\$Input\b').Count
if($inputRefs-lt4){Fail('Unexpectedly small $Input reference count in Get-GlobalHubInputIdentity: '+$inputRefs)}
$newFn=[regex]::Replace($fnText,'(?i)\$Input\b','$Descriptor')
if($newFn-ceq$fnText){Fail 'R8 runtime rename produced no change.'}
$newRuntime=$runtime.Substring(0,$fn.Extent.StartOffset)+$newFn+$runtime.Substring($fn.Extent.EndOffset)
Write-Utf8 $runtimePath $newRuntime
$astAfter=Parse-Ast $runtimePath
$remaining=New-Object System.Collections.ArrayList
foreach($f in @($astAfter.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]},$true))){foreach($p in @($f.Parameters)){if([string]$p.Name.VariablePath.UserPath-ieq'Input'){[void]$remaining.Add([string]$f.Name)}}}
if($remaining.Count-ne0){Fail('Runtime still contains function parameter(s) named $Input after R8: '+([string]::Join(',',@($remaining))))}
$fixedText=[IO.File]::ReadAllText($runtimePath,[Text.Encoding]::UTF8)
if($fixedText-notmatch'function\s+Get-GlobalHubInputIdentity\(\$Descriptor\)'){Fail 'Corrected descriptor parameter is not present.'}

$defect=[ordered]@{
    schema='keelaryn.manager-defects.v1'
    scope='Pre-freeze process-entry findings for Manager 4.17.13'
    defects=@([ordered]@{
        id='MGR-DEF-0031'
        title='PowerShell automatic $input variable replaces global Hub input descriptor parameter'
        severity='P1'
        status='fixed'
        release_blocker=$true
        detected_in='4.17.13'
        detected_stage='prefreeze_process_entry_qualification'
        defect_class='PowerShell automatic-variable collision / pending-input reconciliation reachability'
        affected_surfaces=@('S-RUNTIME-INBOX')
        preconditions='A valid multi-Hub registry exists, an identity-bound Hub-owned APPROVED/CANDIDATE/transport object is stranded in the global Manager inbox, and InitializeInstanceRegistry dispatches existing-registry reconciliation under Windows PowerShell 5.1.'
        bad_behavior='Get-GlobalHubInputIdentity receives the automatic $input enumerator instead of the positional descriptor because its parameter is named $Input. Reconciliation fails immediately with Global Hub input descriptor is invalid before ZIP/transport identity validation or safe transfer can occur.'
        root_cause='Windows PowerShell reserves $input as an automatic variable. Declaring Get-GlobalHubInputIdentity($Input) does not preserve the caller-supplied descriptor; function entry replaces it with the pipeline input enumerator. Function-local/static coverage had never executed the pending-global reconciliation path end to end.'
        root_cause_classes=@('RC-REACHABILITY-001','RC-ENTRY-001')
        violated_invariants=@('MH-INBOX-001','MH-REACHABILITY-001')
        related_defects=@()
        permanent_regressions=@('tools/Invoke-ManagerEntryReachabilityMatrix.ps1')
        planned_regressions=@()
        fixed_in='4.17.13'
        evidence=@(
            [ordered]@{type='prefreeze_process_entry_red_run';id='34849395914'},
            [ordered]@{type='prefreeze_process_entry_red_job';id='103993196794'},
            [ordered]@{type='prefreeze_process_entry_red_artifact';id='10350446110'},
            [ordered]@{type='prefreeze_process_entry_red_artifact_sha256';id='49b8fc478bc371667cd1948200a5df766fed1973fe402c1d8a6f7fe2ecf7fe21'},
            [ordered]@{type='prefreeze_process_entry_red_summary';id='101 executed; 100 PASS; only REGISTRY_PENDING_GLOBAL x InitializeInstanceRegistry failed; harness_error=false'},
            [ordered]@{type='powershell_parameter_collision_probe_run';id='34850808950'},
            [ordered]@{type='powershell_parameter_collision_probe_job';id='103997985944'},
            [ordered]@{type='source_symbol';id='Get-GlobalHubInputIdentity'},
            [ordered]@{type='root_cause';id='function parameter $Input is replaced by Windows PowerShell automatic $input enumerator'}
        )
    })
}
Write-Json $defectPath $defect 30

$risk=Get-Content -LiteralPath $riskPath -Raw -Encoding UTF8|ConvertFrom-Json
$surface=@($risk.surfaces|Where-Object{[string]$_.id-ceq'S-RUNTIME-INBOX'})
if($surface.Count-ne1){Fail('S-RUNTIME-INBOX risk surface count='+$surface.Count)}
Add-UniqueString $surface[0] 'symbols' 'Get-GlobalHubInputIdentity'
Add-UniqueString $surface[0] 'symbols' 'Reconcile-StrandedGlobalHubInputsForExistingRegistry'
Add-UniqueString $surface[0] 'regressions' 'tools/Invoke-ManagerEntryReachabilityMatrix.ps1'
Write-Json $riskPath $risk 70

# Rebuild the authoritative public source identity from exact product bytes. INSTALLATION.json
# itself is unchanged, but the managed-content digest and runtime file row must change.
$null=Invoke-Child $manifestBuilder @('-RepositoryRoot',$RepositoryRoot,'-Write') 'PUBLIC_FILE_MANIFEST regeneration'
$null=Invoke-Child $manifestBuilder @('-RepositoryRoot',$RepositoryRoot,'-Check') 'PUBLIC_FILE_MANIFEST reproducibility'
$manifest=Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$manifest.manager.version-cne'4.17.13'){Fail 'Regenerated manifest Manager version mismatch.'}
$runtimeRows=@($manifest.manager.files|Where-Object{[string]$_.path-ceq'product/runtime/Keelaryn__Manager.ps1'})
if($runtimeRows.Count-ne1){Fail('Regenerated manifest runtime row count='+$runtimeRows.Count)}
$provenance=Get-Content -LiteralPath $provenancePath -Raw -Encoding UTF8|ConvertFrom-Json
$provenance.source_manager_installation_sha256=[string]$manifest.manager.installation_sha256
$provenance.source_manager_gate_managed_content_sha256=[string]$manifest.manager.gate_managed_content_sha256
$provenance.candidate_identity.validated_development_parent=$ExpectedBase
$dev=$provenance.qualification_evidence.development_4_17_13
Add-PropertyIfMissing $dev 'prefreeze_product_fix' ([pscustomobject][ordered]@{
    defect_id='MGR-DEF-0031'
    status='materialized_unqualified_development'
    red_run_id=34849395914
    red_job_id=103993196794
    red_artifact_id=10350446110
    red_artifact_sha256='49b8fc478bc371667cd1948200a5df766fed1973fe402c1d8a6f7fe2ecf7fe21'
    root_cause_probe_run_id=34850808950
    root_cause_probe_job_id=103997985944
    fix='Get-GlobalHubInputIdentity parameter renamed from automatic-variable collision $Input to $Descriptor'
    exact_green_requalification='required_before_freeze'
})
Write-Json $provenancePath $provenance 60

$null=Invoke-Child $metadataVerifier @('-RepositoryRoot',$RepositoryRoot) 'Public candidate metadata verification after R8 product fix'
$null=Invoke-Child $engineeringVerifier @('-RepositoryRoot',$RepositoryRoot) 'Engineering knowledge verification after MGR-DEF-0031 materialization'

$changed=@(& git.exe -C $RepositoryRoot diff --name-only)
$expected=@('PUBLIC_FILE_MANIFEST.json','PUBLIC_PROVENANCE.json','manager/product/runtime/Keelaryn__Manager.ps1','tests/knowledge/defects/manager-4.17.13-prefreeze.json','tests/knowledge/risk-map.json')|Sort-Object
if(([string]::Join('|',@($changed|Sort-Object)))-cne([string]::Join('|',$expected))){Fail('Unexpected R8 product patch set: '+($changed-join', '))}
$managerChanged=@(& git.exe -C $RepositoryRoot diff --name-only -- manager)
if($managerChanged.Count-ne1-or[string]$managerChanged[0]-cne'manager/product/runtime/Keelaryn__Manager.ps1'){Fail('R8 product-byte scope is not exactly the runtime file: '+($managerChanged-join', '))}

$beforeManifestManaged='9804c7aebc6cfedef128a281186683a1f11a32c88c46a82a21a81eae6dbc3de0'
if([string]$manifest.manager.gate_managed_content_sha256-ceq$beforeManifestManaged){Fail 'Managed-content digest did not change after runtime product fix.'}
if([string]$manifest.manager.installation_sha256-cne'acc2b2eeff9b32775dfeaea2d1ca4ee0b8c4293b14acd70efdd8ca08db4eb66b'){Fail 'INSTALLATION identity changed even though INSTALLATION.json bytes were not modified.'}

$receipt=[ordered]@{
    schema='keelaryn.manager-41713-prefreeze-product-fix-r8.v1'
    manager_version='4.17.13'
    base=$ExpectedBase
    defect_id='MGR-DEF-0031'
    product_file='manager/product/runtime/Keelaryn__Manager.ps1'
    fix='rename Get-GlobalHubInputIdentity parameter $Input to $Descriptor'
    runtime_sha256=[string]$runtimeRows[0].sha256
    installation_sha256=[string]$manifest.manager.installation_sha256
    managed_content_sha256=[string]$manifest.manager.gate_managed_content_sha256
    product_bytes_changed=$true
    candidate_issued=$false
    completed_utc=[DateTime]::UtcNow.ToString('o')
}
Write-Json (Join-Path $EvidenceRoot 'R8_PRODUCT_FIX_MATERIALIZATION.json') $receipt 10
Write-Host 'Manager 4.17.13 R8 product-fix materialization: PASS' -ForegroundColor Green
