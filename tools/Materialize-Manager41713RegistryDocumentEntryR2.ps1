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
if([string]::IsNullOrWhiteSpace($EvidenceRoot)){$EvidenceRoot=Join-Path $env:RUNNER_TEMP 'manager-41713-registry-document-entry-proof-r2'}
New-Item -ItemType Directory -Force -Path $EvidenceRoot|Out-Null
function Fail([string]$Message){throw $Message}
function Write-Utf8([string]$Path,[string]$Text){[IO.File]::WriteAllText($Path,$Text,$Utf8)}
function Write-Json([string]$Path,$Object){Write-Utf8 $Path ((($Object|ConvertTo-Json -Depth 50).Replace("`r`n","`n"))+"`n")}
function Replace-Once([string]$Path,[string]$Old,[string]$New,[string]$Label){
    $s=[IO.File]::ReadAllText($Path,[Text.Encoding]::UTF8);$count=[regex]::Matches($s,[regex]::Escape($Old)).Count
    if($count-ne1){Fail($Label+' count='+$count)};Write-Utf8 $Path ($s.Replace($Old,$New))
}
function Parse-File([string]$Path){$tokens=$null;$errors=$null;[void][Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors);if(@($errors).Count){Fail('Parser failed: '+$Path+' :: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}}
function Invoke-Child([string]$Script,[string[]]$Arguments){
    $exe=Join-Path $PSHOME 'powershell.exe';$old=$ErrorActionPreference
    try{$ErrorActionPreference='Continue';$out=@(& $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Script @Arguments 2>&1|ForEach-Object{[string]$_});$code=[int]$LASTEXITCODE}finally{$ErrorActionPreference=$old}
    foreach($line in @($out)){Write-Host $line};if($code-ne0){Fail('Child failed: '+$Script+' exit='+$code)}
}

$head=(& git.exe -C $RepositoryRoot rev-parse HEAD).Trim().ToLowerInvariant()
if($head-cne$ExpectedBase.ToLowerInvariant()){Fail('Unexpected target HEAD: '+$head+' expected='+$ExpectedBase)}
if(@(& git.exe -C $RepositoryRoot status --porcelain).Count-ne0){Fail 'Target checkout is not clean.'}

$r1=Join-Path $PSScriptRoot 'Materialize-Manager41713RegistryDocumentEntryR1.ps1'
$r1Evidence=Join-Path $EvidenceRoot 'r1'
Invoke-Child $r1 @('-RepositoryRoot',$RepositoryRoot,'-ExpectedBase',$ExpectedBase,'-EvidenceRoot',$r1Evidence)

$modelPath=Join-Path $RepositoryRoot 'tests\knowledge\entry-reachability.json'
$validatorPath=Join-Path $RepositoryRoot 'tools\Test-ManagerEntryReachabilityKnowledge.ps1'
$matrixPath=Join-Path $RepositoryRoot 'tools\Invoke-ManagerEntryReachabilityMatrix.ps1'

$oldHandler="                'registry_document_rejected_after_dispatch' {`$startupBlocked=`$r.Text.Contains('Invalid Keelaryn multi-Hub registry:');`$pass=(`$r.ExitCode-ne0-and`$hubsUnchanged-and`$controlStateUnchanged-and-not`$startupBlocked);`$detail=if(`$pass){'unsafe registry document was rejected after startup allow-dispatch without Hub or registry/active metadata mutation'}else{'unsafe registry handling was blocked in startup, succeeded unexpectedly, or mutated state: '+`$r.Text}}"
$newHandler="                'registry_document_rejected_after_dispatch' {`$startupBlocked=`$r.Text.Contains('Invalid Keelaryn multi-Hub registry:');`$operationReached=`$r.Text.Contains('Manager instance registry JSON is invalid:');`$pass=(`$r.ExitCode-ne0-and`$hubsUnchanged-and`$controlStateUnchanged-and-not`$startupBlocked-and`$operationReached);`$detail=if(`$pass){'unsafe registry document passed startup allow-dispatch, reached action-level registry parsing, and was rejected without Hub or registry/active metadata mutation'}else{'action-level unsafe-registry rejection was not proven, startup blocked first, or state mutated: '+`$r.Text}}"
Replace-Once $matrixPath $oldHandler $newHandler 'action-level invalid-registry dispatch proof'

$model=Get-Content -LiteralPath $modelPath -Raw -Encoding UTF8|ConvertFrom-Json
$sentence=' REGISTRY_DOCUMENT_INVALID ListInstances/SwitchInstance/BindInstance coverage must prove the action body reparsed the authoritative registry and emitted the canonical Manager instance registry JSON is invalid failure after startup allow-dispatch.'
if(-not([string]$model.freeze_rule).Contains('action body reparsed the authoritative registry')){$model.freeze_rule=([string]$model.freeze_rule)+$sentence}
Write-Json $modelPath $model

$oldValidator="if(-not([string]`$model.freeze_rule).Contains('preserve instances.json and active_instance.json bytes')){Fail 'Freeze rule must require registry/active control-state preservation for rejected recovery.'}"
$newValidator=$oldValidator+"`nif(-not([string]`$model.freeze_rule).Contains('action body reparsed the authoritative registry')){Fail 'Freeze rule must require action-level invalid-registry reparse proof.'}"
Replace-Once $validatorPath $oldValidator $newValidator 'validator action-level invalid-registry proof rule'

Parse-File $validatorPath;Parse-File $matrixPath
Invoke-Child $validatorPath @('-RepositoryRoot',$RepositoryRoot)
$matrixOut=Join-Path $EvidenceRoot 'ENTRY_REACHABILITY_RESULT.json'
Invoke-Child $matrixPath @('-RepositoryRoot',$RepositoryRoot,'-OutputPath',$matrixOut)
$report=Get-Content -LiteralPath $matrixOut -Raw -Encoding UTF8|ConvertFrom-Json
if(-not[bool]$report.pass-or[int]$report.scenario_count-ne92-or[int]$report.executed_count-ne92){Fail('Expected exact strengthened 92/92 matrix PASS; count='+[string]$report.scenario_count+' executed='+[string]$report.executed_count)}
$docTarget=@($report.scenarios|Where-Object{[string]$_.state-ceq'REGISTRY_DOCUMENT_INVALID'-and@('ListInstances','SwitchInstance','BindInstance') -ccontains [string]$_.action})
if($docTarget.Count-ne3-or@($docTarget|Where-Object{-not[bool]$_.pass-or[string]$_.expected_mode-cne'registry_document_rejected_after_dispatch'-or-not([string]$_.detail).Contains('reached action-level registry parsing')}).Count-ne0){Fail 'List/Switch/Bind invalid-registry scenarios did not all prove action-level registry reparsing after startup allow-dispatch.'}

$changed=@(& git.exe -C $RepositoryRoot diff --name-only);$expected=@('tests/knowledge/entry-reachability.json','tools/Invoke-ManagerEntryReachabilityMatrix.ps1','tools/Test-ManagerEntryReachabilityKnowledge.ps1')|Sort-Object
if(([string]::Join('|',@($changed|Sort-Object)))-cne([string]::Join('|',$expected))){Fail('Unexpected materialized patch set: '+($changed-join', '))}
if(@(& git.exe -C $RepositoryRoot diff --name-only -- manager).Count-ne0){Fail 'Manager product bytes changed in registry-document R2 proof materialization.'}
Write-Host 'Manager 4.17.13 registry-document action-level process-entry proof R2: PASS' -ForegroundColor Green
