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
if([string]::IsNullOrWhiteSpace($EvidenceRoot)){$EvidenceRoot=Join-Path $env:RUNNER_TEMP 'manager-41713-prefreeze-knowledge-r6b'}
New-Item -ItemType Directory -Force -Path $EvidenceRoot|Out-Null
function Fail([string]$Message){throw $Message}
function Write-Utf8([string]$Path,[string]$Text){[IO.File]::WriteAllText($Path,$Text,$Utf8)}
function Replace-Once([string]$Path,[string]$Old,[string]$New,[string]$Label){$s=[IO.File]::ReadAllText($Path,[Text.Encoding]::UTF8);$count=[regex]::Matches($s,[regex]::Escape($Old)).Count;if($count-ne1){Fail($Label+' count='+$count)};Write-Utf8 $Path ($s.Replace($Old,$New))}
function Invoke-Child([string]$Script,[string[]]$Arguments){$exe=Join-Path $PSHOME 'powershell.exe';$old=$ErrorActionPreference;try{$ErrorActionPreference='Continue';$out=@(& $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Script @Arguments 2>&1|ForEach-Object{[string]$_});$code=[int]$LASTEXITCODE}finally{$ErrorActionPreference=$old};foreach($line in @($out)){Write-Host $line};if($code-ne0){Fail('Child failed: '+$Script+' exit='+$code)};return [pscustomobject]@{ExitCode=$code;Text=[string]::Join("`n",@($out))}}

$head=(& git.exe -C $RepositoryRoot rev-parse HEAD).Trim().ToLowerInvariant()
if($head-cne$ExpectedBase.ToLowerInvariant()){Fail('Unexpected target HEAD: '+$head+' expected='+$ExpectedBase)}
if(@(& git.exe -C $RepositoryRoot status --porcelain).Count-ne0){Fail 'Target checkout is not clean.'}

$r6=Join-Path $PSScriptRoot 'Materialize-Manager41713PrefreezeKnowledgeR6.ps1'
$null=Invoke-Child $r6 @('-RepositoryRoot',$RepositoryRoot,'-ExpectedBase',$ExpectedBase,'-EvidenceRoot',$EvidenceRoot)

$workflowPath=Join-Path $RepositoryRoot '.github\workflows\entry-reachability-validation.yml'
$old="      - 'tests/knowledge/entry-reachability.json'`n      - 'tests/knowledge/invariants/multi-hub.json'`n      - 'tools/Test-ManagerEntryReachabilityKnowledge.ps1'"
$new="      - 'tests/knowledge/entry-reachability.json'`n      - 'tests/knowledge/invariants/multi-hub.json'`n      - 'tests/knowledge/state-machines/multi-hub.json'`n      - 'tools/Test-ManagerEntryReachabilityKnowledge.ps1'"
Replace-Once $workflowPath $old $new 'entry workflow state-machine dependency trigger'
$text=[IO.File]::ReadAllText($workflowPath,[Text.Encoding]::UTF8)
if([regex]::Matches($text,[regex]::Escape("tests/knowledge/state-machines/multi-hub.json")).Count-ne1){Fail 'Entry-reachability workflow must contain exactly one canonical state-machine path trigger.'}

$changed=@(& git.exe -C $RepositoryRoot diff --name-only)
$expected=@('.github/workflows/entry-reachability-validation.yml','MANAGER_DEVELOPMENT_STATE.json','PUBLIC_PROVENANCE.json','tests/knowledge/entry-reachability.json','tests/knowledge/prefreeze-semantic-review.json','tests/knowledge/risk-map.json','tests/knowledge/state-machines/multi-hub.json','tools/Invoke-ManagerEntryReachabilityMatrix.ps1','tools/Test-ManagerEngineeringKnowledge.ps1','tools/Test-ManagerEntryReachabilityKnowledge.ps1')|Sort-Object
if(([string]::Join('|',@($changed|Sort-Object)))-cne([string]::Join('|',$expected))){Fail('Unexpected R6b patch set: '+($changed-join', '))}
if(@(& git.exe -C $RepositoryRoot diff --name-only -- manager).Count-ne0){Fail 'Manager product bytes changed in R6b knowledge convergence.'}
Write-Host 'Manager 4.17.13 prefreeze knowledge convergence R6b: PASS' -ForegroundColor Green
