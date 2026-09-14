[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RepositoryRoot,
    [Parameter(Mandatory=$true)][string]$ExpectedBase,
    [string]$EvidenceRoot=''
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$Utf8=New-Object Text.UTF8Encoding($false)
if([string]::IsNullOrWhiteSpace($EvidenceRoot)){$EvidenceRoot=Join-Path $env:RUNNER_TEMP 'manager-41713-prefreeze-knowledge-r6'}
New-Item -ItemType Directory -Force -Path $EvidenceRoot|Out-Null
function Fail([string]$Message){throw $Message}
function Write-Utf8([string]$Path,[string]$Text){[IO.File]::WriteAllText($Path,$Text,$Utf8)}
function Write-Json([string]$Path,$Object,[int]$Depth=70){Write-Utf8 $Path ((($Object|ConvertTo-Json -Depth $Depth).Replace("`r`n","`n"))+"`n")}
function Replace-Once([string]$Path,[string]$Old,[string]$New,[string]$Label){$s=[IO.File]::ReadAllText($Path,[Text.Encoding]::UTF8);$count=[regex]::Matches($s,[regex]::Escape($Old)).Count;if($count-ne1){Fail($Label+' count='+$count)};Write-Utf8 $Path ($s.Replace($Old,$New))}
function Parse-File([string]$Path){$t=$null;$e=$null;[void][Management.Automation.Language.Parser]::ParseFile($Path,[ref]$t,[ref]$e);if(@($e).Count){Fail('Parser failed: '+$Path+' :: '+([string]::Join(' | ',@($e|ForEach-Object{$_.Message}))))}}
function Invoke-Child([string]$Script,[string[]]$Arguments){$exe=Join-Path $PSHOME 'powershell.exe';$old=$ErrorActionPreference;try{$ErrorActionPreference='Continue';$out=@(& $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Script @Arguments 2>&1|ForEach-Object{[string]$_});$code=[int]$LASTEXITCODE}finally{$ErrorActionPreference=$old};foreach($line in @($out)){Write-Host $line};if($code-ne0){Fail('Child failed: '+$Script+' exit='+$code)};return [pscustomobject]@{ExitCode=$code;Text=[string]::Join("`n",@($out))}}

$head=(& git.exe -C $RepositoryRoot rev-parse HEAD).Trim().ToLowerInvariant()
if($head-cne$ExpectedBase.ToLowerInvariant()){Fail('Unexpected target HEAD: '+$head+' expected='+$ExpectedBase)}
if(@(& git.exe -C $RepositoryRoot status --porcelain).Count-ne0){Fail 'Target checkout is not clean.'}

$r5=Join-Path $PSScriptRoot 'Materialize-Manager41713PrefreezeKnowledgeR5.ps1'
$null=Invoke-Child $r5 @('-RepositoryRoot',$RepositoryRoot,'-ExpectedBase',$ExpectedBase,'-EvidenceRoot',(Join-Path $EvidenceRoot 'r5'))

$riskPath=Join-Path $RepositoryRoot 'tests\knowledge\risk-map.json'
$engineeringPath=Join-Path $RepositoryRoot 'tools\Test-ManagerEngineeringKnowledge.ps1'
$risk=Get-Content -LiteralPath $riskPath -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$risk.schema-cne'keelaryn.manager-risk-map.v1'){Fail 'Unexpected risk-map schema.'}
function Add-RuleMapping([string]$SurfaceId,[string]$RuleId){
    $surface=@($risk.surfaces|Where-Object{[string]$_.id-ceq$SurfaceId})
    if($surface.Count-ne1){Fail('Risk surface count for '+$SurfaceId+' = '+$surface.Count)}
    $rules=@($surface[0].state_machine_rules|ForEach-Object{[string]$_})
    if($rules-cnotcontains$RuleId){$surface[0].state_machine_rules=@($rules)+@($RuleId)}
}
foreach($rid in @(
    'R-INACTIVE-CORRUPT-SWITCH',
    'R-INACTIVE-MISSING-SWITCH',
    'R-MISMATCH-SWITCH',
    'R-NONAPPROVED-SWITCH',
    'R-POSTCOMMIT-SWITCH',
    'R-REGISTRY-DOCUMENT-INVALID-LIST',
    'R-SINGLE-BIND',
    'R-CURRENT-DEGRADED-INIT'
)){Add-RuleMapping 'S-RUNTIME-REGISTRY-RESOLUTION' $rid}
foreach($rid in @('R-BROKEN-ACTIVE-UPDATE-ALL-CORRUPT','R-BROKEN-ACTIVE-UPDATE-ALL-MISSING')){Add-RuleMapping 'S-RUNTIME-UPDATE-HANDOFF' $rid}
Add-RuleMapping 'S-RUNTIME-INBOX' 'R-REGISTRY-GLOBAL-PENDING-INIT'
Write-Json $riskPath $risk 70

$oldDecl="`$surfaceIds=New-IdSet`n`$surfaceById=@{}`n`$coveredInvariantIds=New-IdSet"
$newDecl="`$surfaceIds=New-IdSet`n`$surfaceById=@{}`n`$coveredInvariantIds=New-IdSet`n`$coveredRuleIds=New-IdSet"
Replace-Once $engineeringPath $oldDecl $newDecl 'engineering covered state-machine rule set'
$oldRuleLoop="    foreach(`$rid in @(`$surface.state_machine_rules)){Assert-Ref `$ruleIds ([string]`$rid) 'state-machine rule' `$sid}"
$newRuleLoop="    foreach(`$rid in @(`$surface.state_machine_rules)){Assert-Ref `$ruleIds ([string]`$rid) 'state-machine rule' `$sid;[void]`$coveredRuleIds.Add([string]`$rid)}"
Replace-Once $engineeringPath $oldRuleLoop $newRuleLoop 'engineering state-machine rule mapping capture'
$oldInvariantCoverage="foreach(`$iid in @(`$invariantIds)){if(-not`$coveredInvariantIds.Contains(`$iid)){Fail('Invariant has no risk-surface mapping: '+`$iid)}}"
$newInvariantCoverage="foreach(`$rule in @(`$machine.rules|Where-Object{[int]`$_.priority-gt0})){`$rid=[string]`$rule.id;if(-not`$coveredRuleIds.Contains(`$rid)){Fail('Non-default state-machine rule has no risk-surface mapping: '+`$rid)}}`n"+$oldInvariantCoverage
Replace-Once $engineeringPath $oldInvariantCoverage $newInvariantCoverage 'engineering complete non-default rule mapping guard'
Parse-File $engineeringPath

$null=Invoke-Child $engineeringPath @('-RepositoryRoot',$RepositoryRoot)

$machine=Get-Content -LiteralPath (Join-Path $RepositoryRoot 'tests\knowledge\state-machines\multi-hub.json') -Raw -Encoding UTF8|ConvertFrom-Json
$risk2=Get-Content -LiteralPath $riskPath -Raw -Encoding UTF8|ConvertFrom-Json
$mapped=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
foreach($surface in @($risk2.surfaces)){foreach($id in @($surface.state_machine_rules)){[void]$mapped.Add([string]$id)}}
$nonDefault=@($machine.rules|Where-Object{[int]$_.priority-gt0}|ForEach-Object{[string]$_.id}|Sort-Object -Unique)
$unmapped=@($nonDefault|Where-Object{-not$mapped.Contains($_)})
if($unmapped.Count-ne0){Fail('R6 still has unmapped non-default rules: '+($unmapped-join', '))}
Write-Host ('R6 risk-map coverage: '+$nonDefault.Count+'/'+$nonDefault.Count+' non-default rules mapped') -ForegroundColor Green

$changed=@(& git.exe -C $RepositoryRoot diff --name-only)
$expected=@('MANAGER_DEVELOPMENT_STATE.json','PUBLIC_PROVENANCE.json','tests/knowledge/entry-reachability.json','tests/knowledge/prefreeze-semantic-review.json','tests/knowledge/risk-map.json','tests/knowledge/state-machines/multi-hub.json','tools/Invoke-ManagerEntryReachabilityMatrix.ps1','tools/Test-ManagerEngineeringKnowledge.ps1','tools/Test-ManagerEntryReachabilityKnowledge.ps1')|Sort-Object
if(([string]::Join('|',@($changed|Sort-Object)))-cne([string]::Join('|',$expected))){Fail('Unexpected R6 patch set: '+($changed-join', '))}
if(@(& git.exe -C $RepositoryRoot diff --name-only -- manager).Count-ne0){Fail 'Manager product bytes changed in R6 knowledge convergence.'}
Write-Host 'Manager 4.17.13 prefreeze knowledge convergence R6: PASS' -ForegroundColor Green
