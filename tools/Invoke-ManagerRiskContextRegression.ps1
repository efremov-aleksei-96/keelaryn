[CmdletBinding()]
param(
    [string]$RepositoryRoot=(Join-Path $PSScriptRoot '..')
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$Utf8NoBom=New-Object Text.UTF8Encoding($false)

function Fail([string]$Message){throw $Message}
function Invoke-Git([string]$Root,[string[]]$Arguments){
    $old=$ErrorActionPreference
    try{$ErrorActionPreference='Continue';$rows=@(& git.exe -C $Root @Arguments 2>&1);$code=[int]$LASTEXITCODE}finally{$ErrorActionPreference=$old}
    if($code-ne0){Fail('git '+($Arguments-join' ')+' failed: '+([string]::Join(' | ',@($rows))))}
    return @($rows|ForEach-Object{[string]$_})
}
function Invoke-ChildResult([string]$Script,[string[]]$Arguments){
    $powershell=Join-Path $PSHOME 'powershell.exe'
    $old=$ErrorActionPreference
    try{$ErrorActionPreference='Continue';$rows=@(& $powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Script @Arguments 2>&1);$code=[int]$LASTEXITCODE}finally{$ErrorActionPreference=$old}
    return [pscustomobject]@{ExitCode=$code;Output=@($rows|ForEach-Object{[string]$_})}
}
function Commit-One([string]$Root,[string]$Message){
    [void](Invoke-Git $Root @('add','-A'))
    [void](Invoke-Git $Root @('commit','-m',$Message))
    $rows=@(Invoke-Git $Root @('rev-parse','HEAD'))
    if($rows.Count-ne1){Fail('Could not resolve synthetic commit for '+$Message)}
    return $rows[0].Trim().ToLowerInvariant()
}
function Assert-ChildFails([string]$Label,$Result,[string]$Pattern){
    if($Result.ExitCode-eq0){Fail($Label+' must fail closed.')}
    $combined=[string]::Join(' | ',@($Result.Output))
    if($combined-notmatch$Pattern){Fail($Label+' failure was not explicit. output='+$combined)}
}

$riskTool=Join-Path $RepositoryRoot 'tools\Build-ManagerRiskContext.ps1'
if(-not(Test-Path -LiteralPath $riskTool -PathType Leaf)){Fail 'Build-ManagerRiskContext.ps1 is missing.'}
$knowledgeSource=Join-Path $RepositoryRoot 'tests\knowledge'
$riskWorkflow=Join-Path $RepositoryRoot '.github\workflows\manager-risk-defect-gate.yml'
if(-not(Test-Path -LiteralPath $riskWorkflow -PathType Leaf)){Fail 'manager-risk-defect-gate.yml is missing.'}
$riskWorkflowText=[IO.File]::ReadAllText($riskWorkflow,[Text.Encoding]::UTF8)
foreach($token in @('Dispatched checkout identity mismatch','Risk qualification range must be non-empty','git merge-base --is-ancestor','git rev-list --count')){
    if(-not$riskWorkflowText.Contains($token)){Fail('Risk workflow lost fail-closed range guard token: '+$token)}
}
if(-not$riskWorkflowText.Contains('Invoke-ManagerRiskDefectGate.ps1')){Fail 'Risk workflow no longer delegates to the strict gate implementation.'}
Write-Host '  PASS workflow exact-head and proper-ancestor range guards are wired' -ForegroundColor Green
if(-not(Test-Path -LiteralPath $knowledgeSource -PathType Container)){Fail 'Engineering knowledge root is missing.'}

$temp=Join-Path ([IO.Path]::GetTempPath()) ('keelaryn-risk-context-regression-'+[guid]::NewGuid().ToString('N'))
try{
    [void][IO.Directory]::CreateDirectory($temp)
    [void](Invoke-Git $temp @('init'))
    [void](Invoke-Git $temp @('config','user.name','Keelaryn Regression'))
    [void](Invoke-Git $temp @('config','user.email','keelaryn-regression@example.invalid'))

    $testsRoot=Join-Path $temp 'tests'
    [void][IO.Directory]::CreateDirectory($testsRoot)
    Copy-Item -LiteralPath $knowledgeSource -Destination (Join-Path $testsRoot 'knowledge') -Recurse -Force

    $runtimeDir=Join-Path $temp 'manager\product\runtime'
    [void][IO.Directory]::CreateDirectory($runtimeDir)
    $runtimePath=Join-Path $runtimeDir 'Keelaryn__Manager.ps1'
    [IO.File]::WriteAllText($runtimePath,"function Invoke-Broken {`n    if (`n}`n",$Utf8NoBom)
    $base=Commit-One $temp 'synthetic base with unparsable historical runtime'

    Remove-Item -LiteralPath $runtimePath -Force
    $deletedHead=Commit-One $temp 'delete unparsable historical runtime'

    $outDir=Join-Path $temp 'out-deleted'
    [void][IO.Directory]::CreateDirectory($outDir)
    $outMd=Join-Path $outDir 'MANAGER_RISK_CONTEXT.md'
    $deletedRun=Invoke-ChildResult $riskTool @('-RepositoryRoot',$temp,'-BaseCommit',$base,'-HeadCommit',$deletedHead,'-OutputPath',$outMd)
    if($deletedRun.ExitCode-ne0){Fail('Valid proper-ancestor range must succeed. output='+([string]::Join(' | ',@($deletedRun.Output))))}
    $outJson=[IO.Path]::ChangeExtension($outMd,'.json')
    if(-not(Test-Path -LiteralPath $outJson -PathType Leaf)){Fail 'Historical fallback run did not produce risk JSON.'}
    $report=Get-Content -LiteralPath $outJson -Raw -Encoding UTF8|ConvertFrom-Json
    $runtimeChange=@($report.changed_files|Where-Object{[string]$_.path-ceq'manager/product/runtime/Keelaryn__Manager.ps1'})
    if($runtimeChange.Count-ne1){Fail('Expected one synthetic runtime change; actual='+$runtimeChange.Count)}
    if(@($runtimeChange[0].symbols)-notcontains'__HISTORICAL_PARSE_FALLBACK__'){Fail 'Historical parse fallback marker is missing from changed-file symbols.'}
    if(@($report.matched_surfaces).Count-eq0){Fail 'Historical parse fallback must conservatively match path-level risk surfaces.'}
    if(@($report.matched_surfaces|ForEach-Object{[string]$_.id})-notcontains'S-RUNTIME-REGISTRY-RESOLUTION'){Fail 'Historical parse fallback did not include the registry-resolution risk surface.'}
    Write-Host '  PASS valid proper-ancestor range and historical parse fallback' -ForegroundColor Green

    $equalOut=Join-Path $temp 'out-equal\MANAGER_RISK_CONTEXT.md'
    $equalRun=Invoke-ChildResult $riskTool @('-RepositoryRoot',$temp,'-BaseCommit',$deletedHead,'-HeadCommit',$deletedHead,'-OutputPath',$equalOut)
    Assert-ChildFails 'base=head risk range' $equalRun 'must be non-empty'
    Write-Host '  PASS base=head risk range fails closed' -ForegroundColor Green

    [IO.File]::WriteAllText($runtimePath,"function Invoke-StillBroken {`n    if (`n}`n",$Utf8NoBom)
    $invalidHead=Commit-One $temp 'synthetic unparsable current runtime'

    $reversedOut=Join-Path $temp 'out-reversed\MANAGER_RISK_CONTEXT.md'
    $reversedRun=Invoke-ChildResult $riskTool @('-RepositoryRoot',$temp,'-BaseCommit',$invalidHead,'-HeadCommit',$deletedHead,'-OutputPath',$reversedOut)
    Assert-ChildFails 'reversed risk range' $reversedRun 'proper ancestor'
    Write-Host '  PASS reversed risk range fails closed' -ForegroundColor Green

    $invalidOut=Join-Path $temp 'out-invalid-head\MANAGER_RISK_CONTEXT.md'
    $invalidRun=Invoke-ChildResult $riskTool @('-RepositoryRoot',$temp,'-BaseCommit',$deletedHead,'-HeadCommit',$invalidHead,'-OutputPath',$invalidOut)
    if($invalidRun.ExitCode-eq0){Fail 'Unparsable current/head source must remain fail-closed.'}
    $combined=[string]::Join(' | ',@($invalidRun.Output))
    if($combined-notmatch'Could not parse .*Keelaryn__Manager\.ps1'){Fail('Current-head parse failure was not explicit. output='+$combined)}
    Write-Host '  PASS unparsable current/head source remains fatal' -ForegroundColor Green

    [void](Invoke-Git $temp @('checkout','--orphan','unrelated-risk-range'))
    $marker=Join-Path $temp 'unrelated.txt'
    [IO.File]::WriteAllText($marker,"unrelated`n",$Utf8NoBom)
    $unrelatedHead=Commit-One $temp 'synthetic unrelated head'
    $unrelatedOut=Join-Path $temp 'out-unrelated\MANAGER_RISK_CONTEXT.md'
    $unrelatedRun=Invoke-ChildResult $riskTool @('-RepositoryRoot',$temp,'-BaseCommit',$deletedHead,'-HeadCommit',$unrelatedHead,'-OutputPath',$unrelatedOut)
    Assert-ChildFails 'unrelated risk range' $unrelatedRun 'proper ancestor'
    Write-Host '  PASS unrelated risk range fails closed' -ForegroundColor Green

    Write-Host 'MANAGER RISK CONTEXT REGRESSION: PASS' -ForegroundColor Green
}finally{
    if(Test-Path -LiteralPath $temp){Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue}
}
