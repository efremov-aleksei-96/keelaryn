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
if([string]::IsNullOrWhiteSpace($EvidenceRoot)){$EvidenceRoot=Join-Path $env:RUNNER_TEMP 'manager-41713-prefreeze-knowledge-r6c'}
New-Item -ItemType Directory -Force -Path $EvidenceRoot|Out-Null
function Fail([string]$Message){throw $Message}
function Write-Utf8([string]$Path,[string]$Text){[IO.File]::WriteAllText($Path,$Text,$Utf8)}
function Replace-Once([string]$Path,[string]$Old,[string]$New,[string]$Label){$s=[IO.File]::ReadAllText($Path,[Text.Encoding]::UTF8);$count=[regex]::Matches($s,[regex]::Escape($Old)).Count;if($count-ne1){Fail($Label+' count='+$count)};Write-Utf8 $Path ($s.Replace($Old,$New))}
function Parse-File([string]$Path){$t=$null;$e=$null;[void][Management.Automation.Language.Parser]::ParseFile($Path,[ref]$t,[ref]$e);if(@($e).Count){Fail('Parser failed: '+$Path+' :: '+([string]::Join(' | ',@($e|ForEach-Object{$_.Message}))))}}
function Invoke-Child([string]$Script,[string[]]$Arguments){$exe=Join-Path $PSHOME 'powershell.exe';$old=$ErrorActionPreference;try{$ErrorActionPreference='Continue';$out=@(& $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Script @Arguments 2>&1|ForEach-Object{[string]$_});$code=[int]$LASTEXITCODE}finally{$ErrorActionPreference=$old};foreach($line in @($out)){Write-Host $line};if($code-ne0){Fail('Child failed: '+$Script+' exit='+$code)};return [pscustomobject]@{ExitCode=$code;Text=[string]::Join("`n",@($out))}}

$head=(& git.exe -C $RepositoryRoot rev-parse HEAD).Trim().ToLowerInvariant()
if($head-cne$ExpectedBase.ToLowerInvariant()){Fail('Unexpected target HEAD: '+$head+' expected='+$ExpectedBase)}
if(@(& git.exe -C $RepositoryRoot status --porcelain).Count-ne0){Fail 'Target checkout is not clean.'}

$r6b=Join-Path $PSScriptRoot 'Materialize-Manager41713PrefreezeKnowledgeR6b.ps1'
$null=Invoke-Child $r6b @('-RepositoryRoot',$RepositoryRoot,'-ExpectedBase',$ExpectedBase,'-EvidenceRoot',$EvidenceRoot)

$matrixPath=Join-Path $RepositoryRoot 'tools\Invoke-ManagerEntryReachabilityMatrix.ps1'
$oldInit="`$results=New-Object System.Collections.ArrayList;`$version='unknown';`$harnessError=`$null"
$newInit="`$results=New-Object System.Collections.ArrayList;`$version='unknown';`$harnessError=`$null;`$successor=`$null"
Replace-Once $matrixPath $oldInit $newInit 'matrix safe successor initialization'

$oldBeforeInvoke="            `$activeBefore=if(Test-Path -LiteralPath `$activeFile -PathType Leaf){(Get-FileHash -LiteralPath `$activeFile -Algorithm SHA256).Hash.ToLowerInvariant()}else{'missing'}`n            `$r=Invoke-Runtime `$runtime (Get-ActionArguments `$spec.Action);`$exitCode=`$r.ExitCode"
$newBeforeInvoke="            `$activeBefore=if(Test-Path -LiteralPath `$activeFile -PathType Leaf){(Get-FileHash -LiteralPath `$activeFile -Algorithm SHA256).Hash.ToLowerInvariant()}else{'missing'}`n            `$instancesStatePath=Join-Path `$stateRoot 'instances';`$compatBaselinePath=Join-Path `$stateRoot 'baseline'`n            `$instancesStateBefore=Get-TreeDigest `$instancesStatePath;`$compatBaselineBefore=Get-TreeDigest `$compatBaselinePath`n            `$r=Invoke-Runtime `$runtime (Get-ActionArguments `$spec.Action);`$exitCode=`$r.ExitCode"
Replace-Once $matrixPath $oldBeforeInvoke $newBeforeInvoke 'matrix lifecycle-state before digest'

$oldControl="            `$activeAfter=if(Test-Path -LiteralPath `$activeFile -PathType Leaf){(Get-FileHash -LiteralPath `$activeFile -Algorithm SHA256).Hash.ToLowerInvariant()}else{'missing'}`n            `$controlStateUnchanged=(`$registryAfter-ceq`$registryBefore-and`$activeAfter-ceq`$activeBefore)"
$newControl="            `$activeAfter=if(Test-Path -LiteralPath `$activeFile -PathType Leaf){(Get-FileHash -LiteralPath `$activeFile -Algorithm SHA256).Hash.ToLowerInvariant()}else{'missing'}`n            `$controlStateUnchanged=(`$registryAfter-ceq`$registryBefore-and`$activeAfter-ceq`$activeBefore)`n            `$instancesStateAfter=Get-TreeDigest `$instancesStatePath;`$compatBaselineAfter=Get-TreeDigest `$compatBaselinePath`n            `$lifecycleStateUnchanged=(`$controlStateUnchanged-and`$instancesStateAfter-ceq`$instancesStateBefore-and`$compatBaselineAfter-ceq`$compatBaselineBefore)"
Replace-Once $matrixPath $oldControl $newControl 'matrix lifecycle-state after digest'

Replace-Once $matrixPath "'list_success' {`$pass=(`$r.ExitCode-eq0-and`$r.Text.Contains('Registered Hubs:')-and`$hubsUnchanged);" "'list_success' {`$pass=(`$r.ExitCode-eq0-and`$r.Text.Contains('Registered Hubs:')-and`$hubsUnchanged-and`$lifecycleStateUnchanged);" 'list lifecycle immutability'
Replace-Once $matrixPath "`$pass=(`$r.ExitCode-eq0-and`$hubsUnchanged-and`$installed-ceq[string]`$successor.Version-and`$restartObserved-and`$packageConsumed)" "`$pass=(`$r.ExitCode-eq0-and`$hubsUnchanged-and`$lifecycleStateUnchanged-and`$installed-ceq[string]`$successor.Version-and`$restartObserved-and`$packageConsumed)" 'UpdateManager lifecycle immutability'
Replace-Once $matrixPath "`$pass=(`$r.ExitCode-eq0-and`$hubsUnchanged-and`$controlStateUnchanged-and`$r.Text.Contains('Multi-Hub registry is already initialized and valid.'))" "`$pass=(`$r.ExitCode-eq0-and`$hubsUnchanged-and`$lifecycleStateUnchanged-and`$r.Text.Contains('Multi-Hub registry is already initialized and valid.'))" 'Initialize existing-registry lifecycle immutability'
Replace-Once $matrixPath "`$pass=(`$r.ExitCode-eq0-and`$hubsUnchanged);`$detail=if(`$pass){'Manager-global action completed independently of degraded Hub context'}" "`$pass=(`$r.ExitCode-eq0-and`$hubsUnchanged-and`$lifecycleStateUnchanged);`$detail=if(`$pass){'Manager-global action completed independently of degraded Hub context without Hub lifecycle mutation'}" 'generic global lifecycle immutability'
Replace-Once $matrixPath "'diagnostic_reached' {`$pass=(`$r.Text.Contains('Keelaryn Doctor - Manager')-and`$hubsUnchanged);" "'diagnostic_reached' {`$pass=(`$r.Text.Contains('Keelaryn Doctor - Manager')-and`$hubsUnchanged-and`$lifecycleStateUnchanged);" 'Doctor lifecycle immutability'
Replace-Once $matrixPath "`$pass=(`$r.ExitCode-ne0-and`$hubsUnchanged-and`$controlStateUnchanged-and-not`$startupBlocked-and`$operationReached)" "`$pass=(`$r.ExitCode-ne0-and`$hubsUnchanged-and`$lifecycleStateUnchanged-and-not`$startupBlocked-and`$operationReached)" 'invalid registry recovery lifecycle immutability'
Replace-Once $matrixPath "`$pass=(`$r.ExitCode-ne0-and`$hubsUnchanged-and`$controlStateUnchanged-and`$reached)" "`$pass=(`$r.ExitCode-ne0-and`$hubsUnchanged-and`$lifecycleStateUnchanged-and`$reached)" 'invalid registry init lifecycle immutability'
Replace-Once $matrixPath "'fail_closed' {`$pass=(`$r.ExitCode-ne0-and`$hubsUnchanged-and`$controlStateUnchanged);" "'fail_closed' {`$pass=(`$r.ExitCode-ne0-and`$hubsUnchanged-and`$lifecycleStateUnchanged);" 'fail-closed lifecycle immutability'

$oldReportStart="`$failed=@(`$results|Where-Object{-not[bool]`$_.pass})`n`$report=[ordered]@{"
$newReportStart="`$failed=@(`$results|Where-Object{-not[bool]`$_.pass})`n`$syntheticSuccessorVersion=if(`$null-ne`$successor){[string]`$successor.Version}else{''}`n`$report=[ordered]@{"
Replace-Once $matrixPath $oldReportStart $newReportStart 'matrix failure-safe successor evidence'
Replace-Once $matrixPath "synthetic_successor_version=[string]`$successor.Version" "synthetic_successor_version=`$syntheticSuccessorVersion" 'matrix safe successor report field'
Parse-File $matrixPath

$validator=Join-Path $RepositoryRoot 'tools\Test-ManagerEntryReachabilityKnowledge.ps1'
$null=Invoke-Child $validator @('-RepositoryRoot',$RepositoryRoot)
$finalMatrix=Join-Path $EvidenceRoot 'ENTRY_REACHABILITY_RESULT_FINAL.json'
$null=Invoke-Child $matrixPath @('-RepositoryRoot',$RepositoryRoot,'-OutputPath',$finalMatrix)
$report=Get-Content -LiteralPath $finalMatrix -Raw -Encoding UTF8|ConvertFrom-Json
if(-not[bool]$report.pass-or[int]$report.scenario_count-ne96-or[int]$report.executed_count-ne96){Fail 'R6c strengthened final matrix must PASS exact 96/96.'}
$nonTarget=@($report.scenarios|Where-Object{[string]$_.expected_mode-cne'target_success'})
if(@($nonTarget|Where-Object{-not[bool]$_.pass}).Count-ne0){Fail 'R6c non-target lifecycle immutability proof contains failures.'}

$changed=@(& git.exe -C $RepositoryRoot diff --name-only)
$expected=@('.github/workflows/entry-reachability-validation.yml','MANAGER_DEVELOPMENT_STATE.json','PUBLIC_PROVENANCE.json','tests/knowledge/entry-reachability.json','tests/knowledge/prefreeze-semantic-review.json','tests/knowledge/risk-map.json','tests/knowledge/state-machines/multi-hub.json','tools/Invoke-ManagerEntryReachabilityMatrix.ps1','tools/Test-ManagerEngineeringKnowledge.ps1','tools/Test-ManagerEntryReachabilityKnowledge.ps1')|Sort-Object
if(([string]::Join('|',@($changed|Sort-Object)))-cne([string]::Join('|',$expected))){Fail('Unexpected R6c patch set: '+($changed-join', '))}
if(@(& git.exe -C $RepositoryRoot diff --name-only -- manager).Count-ne0){Fail 'Manager product bytes changed in R6c knowledge convergence.'}
Write-Host 'Manager 4.17.13 prefreeze knowledge convergence R6c: PASS' -ForegroundColor Green
