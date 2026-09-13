[CmdletBinding()]
param(
    [string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'),
    [string]$OutputDirectory=(Join-Path $env:RUNNER_TEMP 'keelaryn-development-validation')
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[System.IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$OutputDirectory=[System.IO.Path]::GetFullPath($OutputDirectory).TrimEnd('\')
$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)

function Fail([string]$Message){throw $Message}
function Sha([string]$Path){
    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){Fail('Hash target missing: '+$Path)}
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Write-Json([string]$Path,$Object){
    $parent=[System.IO.Path]::GetDirectoryName($Path)
    if($parent -and -not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
    $text=(($Object|ConvertTo-Json -Depth 40).Replace("`r`n","`n"))+"`n"
    [System.IO.File]::WriteAllText($Path,$text,$Utf8NoBom)
}
function Parse-File([string]$Path){
    $tokens=$null;$errors=$null
    [void][System.Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors)
    if(@($errors).Count-ne 0){Fail('PowerShell parser failed: '+$Path+'; '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
}
function Invoke-ChildResult([string]$Script,[string[]]$Arguments){
    if($null-eq $Arguments){$Arguments=@()}
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
function Invoke-Child([string]$Script,[string[]]$Arguments){
    $result=Invoke-ChildResult $Script $Arguments
    if($result.ExitCode-ne 0){Fail('Child command failed. exit='+$result.ExitCode+' script='+$Script+' args='+($Arguments-join' ')+' output='+([string]::Join(' | ',@($result.Output))))}
}
function Invoke-GitOne([string[]]$Arguments){
    $old=$ErrorActionPreference
    try{$ErrorActionPreference='Continue';$out=@(& git.exe -C $RepositoryRoot @Arguments 2>&1);$code=[int]$LASTEXITCODE}finally{$ErrorActionPreference=$old}
    if($code-ne0-or$out.Count-ne1){Fail('git '+($Arguments-join' ')+' failed: '+([string]::Join(' | ',@($out))))}
    return ([string]$out[0]).Trim().ToLowerInvariant()
}
function Copy-Managed([string]$Source,[string]$Destination){
    $install=Get-Content -LiteralPath (Join-Path $Source 'product\install\INSTALLATION.json') -Raw -Encoding UTF8|ConvertFrom-Json
    if(Test-Path -LiteralPath $Destination){Remove-Item -LiteralPath $Destination -Recurse -Force}
    [void][System.IO.Directory]::CreateDirectory($Destination)
    foreach($raw in @($install.managed_files)){
        $relative=([string]$raw).Replace('/','\')
        $src=Join-Path $Source $relative
        $dst=Join-Path $Destination $relative
        if(-not(Test-Path -LiteralPath $src -PathType Leaf)){Fail('Managed source missing: '+$relative)}
        $parent=[System.IO.Path]::GetDirectoryName($dst)
        if($parent -and -not [System.IO.Directory]::Exists($parent)){[void][System.IO.Directory]::CreateDirectory($parent)}
        [System.IO.File]::Copy($src,$dst,$true)
    }
}
function Find-One([string]$Root,[string]$Name){
    $rows=@(Get-ChildItem -LiteralPath $Root -File -Recurse -Force -Filter $Name)
    if($rows.Count-ne 1){Fail('Expected one '+$Name+' below '+$Root+'; actual='+$rows.Count)}
    return $rows[0].FullName
}
function Assert-SameStringSet($Expected,$Actual,[string]$Label){
    $expectedRows=@($Expected|ForEach-Object{[string]$_}|Sort-Object -Unique)
    $actualRows=@($Actual|ForEach-Object{[string]$_}|Sort-Object -Unique)
    if(([string]::Join('|',$expectedRows))-cne([string]::Join('|',$actualRows))){Fail($Label+' mismatch. expected='+([string]::Join(',',$expectedRows))+' actual='+([string]::Join(',',$actualRows)))}
}

$manager=Join-Path $RepositoryRoot 'manager'
$installPath=Join-Path $manager 'product\install\INSTALLATION.json'
if(-not(Test-Path -LiteralPath $installPath -PathType Leaf)){Fail 'Manager INSTALLATION.json is missing.'}
$install=Get-Content -LiteralPath $installPath -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$install.schema-cne 'keelaryn.manager.installation.v2'){Fail('Unsupported Manager installation schema: '+[string]$install.schema)}
$version=([string]$install.manager_version).Trim()
if($version-notmatch '^\d+\.\d+\.\d+$'){Fail('Invalid Manager version: '+$version)}
$developmentStatePath=Join-Path $RepositoryRoot 'MANAGER_DEVELOPMENT_STATE.json'
if(-not(Test-Path -LiteralPath $developmentStatePath -PathType Leaf)){Fail 'MANAGER_DEVELOPMENT_STATE.json is missing.'}
$developmentState=Get-Content -LiteralPath $developmentStatePath -Raw -Encoding UTF8|ConvertFrom-Json

if(Test-Path -LiteralPath $OutputDirectory){Remove-Item -LiteralPath $OutputDirectory -Recurse -Force}
[void][System.IO.Directory]::CreateDirectory($OutputDirectory)
$evidence=Join-Path $OutputDirectory 'evidence'
[void][System.IO.Directory]::CreateDirectory($evidence)

Write-Host ('Keelaryn development validation - Manager '+$version)
Write-Host '[1/7] Parse Manager and development/risk PowerShell source...'
$psFiles=@(Get-ChildItem -LiteralPath $manager -File -Recurse -Force -Filter '*.ps1')
if($psFiles.Count-eq 0){Fail 'No Manager PowerShell files found.'}
foreach($file in $psFiles){Parse-File $file.FullName}
$knowledgeTools=@(
    'tools\Test-ManagerEngineeringKnowledge.ps1',
    'tools\Build-ManagerRiskContext.ps1',
    'tools\Invoke-ManagerRiskDefectGate.ps1',
    'tools\Invoke-ManagerRiskContextRegression.ps1',
    'tools\Verify-ManagerReleaseInstructions.ps1',
    'tools\Invoke-Manager41711ReviewRegression.ps1',
    'tools\Invoke-Manager41712ReviewRegression.ps1'
)
foreach($relative in $knowledgeTools){
    $path=Join-Path $RepositoryRoot $relative
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){Fail('Engineering knowledge tool is missing: '+$relative)}
    Parse-File $path
}
Write-Host ('Parser: PASS. Manager files='+$psFiles.Count+'; knowledge tools='+$knowledgeTools.Count) -ForegroundColor Green

Write-Host '[2/7] Validate engineering knowledge and reproducible task risk context...'
$knowledgeTool=Join-Path $RepositoryRoot 'tools\Test-ManagerEngineeringKnowledge.ps1'
Invoke-Child $knowledgeTool @('-RepositoryRoot',$RepositoryRoot)
$head=Invoke-GitOne @('rev-parse','--verify','HEAD^{commit}')
$base=Invoke-GitOne @('rev-parse','--verify','HEAD^^{commit}')
$riskTool=Join-Path $RepositoryRoot 'tools\Build-ManagerRiskContext.ps1'
$riskA=Join-Path $OutputDirectory 'risk-a\MANAGER_RISK_CONTEXT.md'
$riskB=Join-Path $OutputDirectory 'risk-b\MANAGER_RISK_CONTEXT.md'
Invoke-Child $riskTool @('-RepositoryRoot',$RepositoryRoot,'-BaseCommit',$base,'-HeadCommit',$head,'-OutputPath',$riskA)
Invoke-Child $riskTool @('-RepositoryRoot',$RepositoryRoot,'-BaseCommit',$base,'-HeadCommit',$head,'-OutputPath',$riskB)
$riskAJson=[IO.Path]::ChangeExtension($riskA,'.json')
$riskBJson=[IO.Path]::ChangeExtension($riskB,'.json')
if((Sha $riskA)-cne(Sha $riskB)){Fail 'MANAGER_RISK_CONTEXT.md is not deterministic for the exact same base/head.'}
if((Sha $riskAJson)-cne(Sha $riskBJson)){Fail 'MANAGER_RISK_CONTEXT.json is not deterministic for the exact same base/head.'}
Copy-Item -LiteralPath $riskA -Destination (Join-Path $evidence 'MANAGER_RISK_CONTEXT.md') -Force
Copy-Item -LiteralPath $riskAJson -Destination (Join-Path $evidence 'MANAGER_RISK_CONTEXT.json') -Force
$riskContextRegression=Join-Path $RepositoryRoot 'tools\Invoke-ManagerRiskContextRegression.ps1'
Invoke-Child $riskContextRegression @('-RepositoryRoot',$RepositoryRoot)
Write-Host 'Engineering knowledge + risk context reproducibility + lifecycle regression: PASS' -ForegroundColor Green

Write-Host '[3/7] Prove strict Risk/Defect Gate policy state...'
$riskGateTool=Join-Path $RepositoryRoot 'tools\Invoke-ManagerRiskDefectGate.ps1'
$riskGateRoot=Join-Path $OutputDirectory 'risk-gate'
$riskGateRun=Invoke-ChildResult $riskGateTool @('-RepositoryRoot',$RepositoryRoot,'-BaseCommit',$base,'-HeadCommit',$head,'-OutputDirectory',$riskGateRoot)
$riskGateEvidence=Join-Path $riskGateRoot 'RISK_DEFECT_GATE.json'
if(-not(Test-Path -LiteralPath $riskGateEvidence -PathType Leaf)){Fail 'Strict Risk/Defect Gate did not produce evidence.'}
$riskGateReport=Get-Content -LiteralPath $riskGateEvidence -Raw -Encoding UTF8|ConvertFrom-Json
$riskPolicy=[string]$developmentState.qualification.risk_defect_gate.status
if($riskPolicy-ceq'expected_fail_while_open_release_blockers_exist'){
    if($riskGateRun.ExitCode-ne1){Fail('Strict Risk/Defect Gate must FAIL with exit 1 while blockers are open; actual='+$riskGateRun.ExitCode)}
    if([bool]$riskGateReport.pass -or [bool]$riskGateReport.candidate_freeze_permitted){Fail 'Strict Risk/Defect Gate unexpectedly permits candidate freeze.'}
    $unexpected=@($riskGateReport.failures|Where-Object{[string]$_.kind-cne'open_release_blocker'})
    if($unexpected.Count-ne0){Fail('Strict gate has unexpected failure classes: '+([string]::Join(',',@($unexpected|ForEach-Object{[string]$_.kind+':'+[string]$_.id}))))}
    $actualBlockers=@($riskGateReport.failures|Where-Object{[string]$_.kind-ceq'open_release_blocker'}|ForEach-Object{[string]$_.id})
    Assert-SameStringSet @($developmentState.open_release_blockers) $actualBlockers 'Strict-gate blocker set'
    Write-Host 'Strict Risk/Defect Gate: expected policy FAIL proven; blocker set exact.' -ForegroundColor Green
}elseif($riskPolicy-ceq'required_pass_before_freeze'){
    if($riskGateRun.ExitCode-ne0 -or -not[bool]$riskGateReport.pass -or -not[bool]$riskGateReport.candidate_freeze_permitted){Fail 'Strict Risk/Defect Gate is required to PASS by development state.'}
    Write-Host 'Strict Risk/Defect Gate: PASS required by policy and observed.' -ForegroundColor Green
}else{Fail('Unsupported development-state risk gate policy: '+$riskPolicy)}
Copy-Item -LiteralPath $riskGateEvidence -Destination (Join-Path $evidence 'RISK_DEFECT_GATE_POLICY_CHECK.json') -Force

Write-Host '[4/7] Run Manager review regression and release-identity chain...'
$releaseInstructionGuard=Join-Path $RepositoryRoot 'tools\Verify-ManagerReleaseInstructions.ps1'
Invoke-Child $releaseInstructionGuard @('-RepositoryRoot',$RepositoryRoot)
foreach($regressionName in @('Invoke-Manager41710ReviewRegression.ps1','Invoke-Manager41711ReviewRegression.ps1','Invoke-Manager41712ReviewRegression.ps1')){
    $regression=Join-Path $RepositoryRoot ('tools\'+$regressionName)
    if(-not(Test-Path -LiteralPath $regression -PathType Leaf)){Fail('Manager review regression tool is missing: '+$regressionName)}
    Parse-File $regression
    Invoke-Child $regression @('-RepositoryRoot',$RepositoryRoot)
}
Write-Host 'Manager 4.17.10 + 4.17.11 + 4.17.12 review regression and release-instruction chain: PASS' -ForegroundColor Green

Write-Host '[5/7] Run Manager and frontend SelfTests from source...'
$runtime=Join-Path $manager 'product\runtime\Keelaryn__Manager.ps1'
$menu=Join-Path $manager 'product\tools\KeelarynMenu.ps1'
Invoke-Child $runtime @('-SelfTest')
Invoke-Child $menu @('-SelfTest','-NoRootLauncher')
Write-Host 'SelfTests: PASS' -ForegroundColor Green

Write-Host '[6/7] Run deterministic BuildRelease x2 in isolated disposable Manager roots...'
$buildA=Join-Path $OutputDirectory 'build-a\manager'
$buildB=Join-Path $OutputDirectory 'build-b\manager'
Copy-Managed $manager $buildA
Copy-Managed $manager $buildB

foreach($copy in @($buildA,$buildB)){
    $copyRuntime=Join-Path $copy 'product\runtime\Keelaryn__Manager.ps1'
    Invoke-Child $copyRuntime @('-InitializePresentation')
    Invoke-Child $copyRuntime @('-SelfTest')
    Invoke-Child $copyRuntime @('-BuildRelease')
}

$expected=@(
    [string]::Concat('Keelaryn__Manager_SOURCE_v',$version,'.zip')
    [string]::Concat('Keelaryn__Manager_Distribution_v',$version,'.zip')
    [string]::Concat('Keelaryn__Manager_Update_v',$version,'_Built.zip')
    [string]::Concat('Keelaryn__Manager_AI_CONTEXT_v',$version,'.zip')
    [string]::Concat('Keelaryn__Manager_RELEASE_v',$version,'.json')
)
if($expected.Count-ne 5){Fail('Expected artifact-name set count mismatch: '+$expected.Count)}
$artifacts=New-Object System.Collections.ArrayList
foreach($name in $expected){
    $a=Find-One $buildA $name
    $b=Find-One $buildB $name
    $ha=Sha $a;$hb=Sha $b
    if($ha-cne $hb){Fail('Deterministic BuildRelease mismatch: '+$name+'; '+$ha+' != '+$hb)}
    [void]$artifacts.Add([ordered]@{name=$name;sha256=$ha;bytes=[long](Get-Item -LiteralPath $a -Force).Length})
}
Write-Host 'Deterministic BuildRelease x2: PASS' -ForegroundColor Green

Write-Host '[7/7] Write compact development evidence...'
$report=[ordered]@{
    schema='keelaryn.manager-development-validation.v3'
    classification='development_only'
    manager_version=$version
    source_sha=$env:GITHUB_SHA
    risk_base_commit=$base
    risk_head_commit=$head
    runner=$env:RUNNER_NAME
    parser_files=$psFiles.Count
    engineering_knowledge_pass=$true
    risk_context_reproducible=$true
    risk_context_lifecycle_regression_pass=$true
    risk_defect_gate_policy_check_pass=$true
    risk_defect_gate_observed_pass=[bool]$riskGateReport.pass
    risk_defect_gate_expected_policy=$riskPolicy
    review_regressions_pass=$true
    manager_selftest_pass=$true
    frontend_selftest_pass=$true
    deterministic_build_release_pass=$true
    release_artifacts=@($artifacts)
    production_qualified=$false
    candidate_issued=$false
    production_hub_used=$false
    completed_utc=[DateTime]::UtcNow.ToString('o')
}
$reportPath=Join-Path $evidence 'DEVELOPMENT_VALIDATION.json'
Write-Json $reportPath $report

Remove-Item -LiteralPath (Join-Path $OutputDirectory 'build-a') -Recurse -Force
Remove-Item -LiteralPath (Join-Path $OutputDirectory 'build-b') -Recurse -Force
Remove-Item -LiteralPath (Join-Path $OutputDirectory 'risk-a') -Recurse -Force
Remove-Item -LiteralPath (Join-Path $OutputDirectory 'risk-b') -Recurse -Force
Remove-Item -LiteralPath (Join-Path $OutputDirectory 'risk-gate') -Recurse -Force

Write-Host ''
Write-Host 'KEELARYN DEVELOPMENT VALIDATION: PASS' -ForegroundColor Green
Write-Host ('Evidence: '+$evidence)
Write-Host 'Classification: development_only; production_qualified=false'