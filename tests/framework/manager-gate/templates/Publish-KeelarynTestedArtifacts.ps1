[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$CandidateRoot,
    [Parameter(Mandatory=$true)][string]$ResultsRoot,
    [Parameter(Mandatory=$true)][string]$SourceGateResultPath,
    [Parameter(Mandatory=$true)][string]$GateSummaryPath
)

$ErrorActionPreference='Stop'

function Sha([string]$Path){return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}
function Write-Utf8NoBom([string]$Path,[string]$Text){
    $parent=Split-Path -Parent $Path;if($parent){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
    [System.IO.File]::WriteAllText($Path,$Text,(New-Object System.Text.UTF8Encoding($false)))
}
function Ensure-SafeDirectory([string]$Path,[string]$Purpose){
    if(-not(Test-Path -LiteralPath $Path)){New-Item -ItemType Directory -Force -Path $Path|Out-Null}
    $item=Get-Item -LiteralPath $Path -Force
    if(-not$item.PSIsContainer-or($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){throw($Purpose+' is unsafe: '+$Path)}
}

$CandidateRoot=[System.IO.Path]::GetFullPath($CandidateRoot).TrimEnd('\')
$ResultsRoot=[System.IO.Path]::GetFullPath($ResultsRoot).TrimEnd('\')
$SourceGateResultPath=[System.IO.Path]::GetFullPath($SourceGateResultPath)
$GateSummaryPath=[System.IO.Path]::GetFullPath($GateSummaryPath)
foreach($p in @($SourceGateResultPath,$GateSummaryPath)){if(-not(Test-Path -LiteralPath $p -PathType Leaf)){throw('Required gate evidence missing: '+$p)}}

$source=(Get-Content -LiteralPath $SourceGateResultPath -Raw -Encoding UTF8)|ConvertFrom-Json
$summary=(Get-Content -LiteralPath $GateSummaryPath -Raw -Encoding UTF8)|ConvertFrom-Json
$specPath=Join-Path $CandidateRoot 'gate\GATE_SPEC.json'
if(-not(Test-Path -LiteralPath $specPath -PathType Leaf)){throw('Gate spec missing: '+$specPath)}
$spec=(Get-Content -LiteralPath $specPath -Raw -Encoding UTF8)|ConvertFrom-Json

if([string]$source.schema-ne'keelaryn.manager-source-gate-result.v1'-or[string]$source.status-ne'passed'){throw 'SourceGate result is not a passed v1 result.'}
if([string]$summary.schema-ne'keelaryn.manager.windows-gate-summary.v16'-or[string]$summary.status-ne'passed'){throw 'Full Gate summary is not PASS.'}
$version=[string]$spec.candidate_version
if([string]$source.candidate_version-ne$version-or[string]$summary.manager_version-ne$version){throw 'Candidate version mismatch across gate evidence.'}
if([int]$source.gate_revision-ne[int]$spec.gate_revision-or[int]$summary.gate_revision-ne[int]$spec.gate_revision){throw 'Gate revision mismatch across gate evidence.'}
if([int]$source.framework_revision-ne[int]$spec.framework_revision){throw 'Framework revision mismatch across SourceGate/spec.'}
if([string]$source.gate_spec_sha256-ne(Sha $specPath)){throw 'SourceGate result is not bound to current GATE_SPEC.'}
if([string]$source.candidate_installation_sha256-ne[string]$spec.candidate_installation_sha256-or[string]$source.candidate_managed_content_sha256-ne[string]$spec.candidate_managed_content_sha256){throw 'SourceGate candidate binding mismatch.'}

$releaseRel=[string]$source.release.root_relative
if($releaseRel-cne'_releases'){throw('Unsupported SourceGate release root contract: '+$releaseRel)}
$releaseRoot=Join-Path $CandidateRoot $releaseRel
if(-not(Test-Path -LiteralPath $releaseRoot -PathType Container)){throw('SourceGate release root missing: '+$releaseRoot)}
$releaseItem=Get-Item -LiteralPath $releaseRoot -Force
if(($releaseItem.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){throw('SourceGate release root is a reparse point: '+$releaseRoot)}

$manifestRel=[string]$source.release.manifest_relative
if([string]::IsNullOrWhiteSpace($manifestRel)-or[System.IO.Path]::IsPathRooted($manifestRel)-or$manifestRel.Contains('..')){throw 'SourceGate manifest relative path is unsafe.'}
$manifestPath=Join-Path $releaseRoot $manifestRel
if(-not(Test-Path -LiteralPath $manifestPath -PathType Leaf)-or(Sha $manifestPath)-ne([string]$source.release.manifest_sha256).ToLowerInvariant()){throw 'SourceGate release manifest evidence mismatch.'}

$updateRows=@($source.release.artifacts|Where-Object{[string]$_.role-eq'update'})
if($updateRows.Count-ne1){throw 'SourceGate result must contain exactly one UPDATE artifact.'}
$updateRow=$updateRows[0]
$updateRel=[string]$updateRow.path
if([string]::IsNullOrWhiteSpace($updateRel)-or[System.IO.Path]::IsPathRooted($updateRel)-or$updateRel.Contains('..')){throw 'SourceGate UPDATE relative path is unsafe.'}
$updatePath=Join-Path $releaseRoot $updateRel
if(-not(Test-Path -LiteralPath $updatePath -PathType Leaf)){throw('SourceGate UPDATE missing: '+$updatePath)}
$updateSha=Sha $updatePath
if($updateSha-ne([string]$updateRow.sha256).ToLowerInvariant()){throw 'SourceGate UPDATE hash mismatch.'}
if([int64](Get-Item -LiteralPath $updatePath -Force).Length-ne[int64]$updateRow.bytes){throw 'SourceGate UPDATE size mismatch.'}

$artifactsRoot=Join-Path $ResultsRoot 'artifacts'
Ensure-SafeDirectory $artifactsRoot 'Tested artifacts directory'
$destUpdate=Join-Path $artifactsRoot (Split-Path $updatePath -Leaf)
$destManifest=Join-Path $artifactsRoot (Split-Path $manifestPath -Leaf)
foreach($pair in @(@($updatePath,$destUpdate),@($manifestPath,$destManifest))){
    $src=[string]$pair[0];$dst=[string]$pair[1]
    if(Test-Path -LiteralPath $dst -PathType Leaf){if((Sha $dst)-ne(Sha $src)){Remove-Item -LiteralPath $dst -Force;Copy-Item -LiteralPath $src -Destination $dst -Force}}
    else{Copy-Item -LiteralPath $src -Destination $dst -Force}
    if((Sha $dst)-ne(Sha $src)){throw('Tested artifact copy hash mismatch: '+$dst)}
}

$tested=[ordered]@{
    schema='keelaryn.manager-tested-release.v1'
    status='full_gate_passed'
    manager_version=$version
    baseline_version=[string]$summary.baseline_version
    gate_revision=[int]$summary.gate_revision
    framework_revision=[int]$source.framework_revision
    gate_spec_sha256=(Sha $specPath)
    source_gate_result_sha256=(Sha $SourceGateResultPath)
    gate_summary_relative='../GATE_SUMMARY.json'
    update=[ordered]@{file=(Split-Path $destUpdate -Leaf);sha256=(Sha $destUpdate);bytes=[int64](Get-Item -LiteralPath $destUpdate -Force).Length}
    release_manifest=[ordered]@{file=(Split-Path $destManifest -Leaf);sha256=(Sha $destManifest)}
    published_utc=(Get-Date).ToUniversalTime().ToString('o')
}
$testedPath=Join-Path $artifactsRoot 'TESTED_RELEASE.json'
Write-Utf8NoBom $testedPath ((($tested|ConvertTo-Json -Depth 8).Replace("`r`n","`n"))+"`n")

$installerPs=@'
[CmdletBinding()]
param([switch]$ValidateOnly)
$ErrorActionPreference='Stop'
function Sha([string]$Path){return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}
function Get-ProductionDoctorReport([string]$ManagerRoot){
    $receipt=Join-Path $ManagerRoot 'state\layout.json'
    $path=if(Test-Path -LiteralPath $receipt -PathType Leaf){Join-Path $ManagerRoot 'state\logs\DOCTOR_REPORT.json'}else{Join-Path $ManagerRoot '_logs\DOCTOR_REPORT.json'}
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw('Production Doctor report missing: '+$path)}
    return (Get-Content -LiteralPath $path -Raw -Encoding UTF8)|ConvertFrom-Json
}
function Test-IsPermittedTransitionDoctorWarning($Finding){
    if($null-eq$Finding){return $false}
    if([string]$Finding.Severity-cne'WARN'-or[string]$Finding.Code-cne'governance.status'){return $false}
    $message=([string]$Finding.Message).Trim()
    if($message.StartsWith('Hub governance receipt is missing.',[System.StringComparison]::Ordinal)){return $true}
    return [regex]::IsMatch($message,'^Hub governance r[0-9]+ is older than Manager r[0-9]+\.',[System.Text.RegularExpressions.RegexOptions]::CultureInvariant)
}
function Assert-ProductionDoctorResult([int]$ExitCode,$Report){
    if($null-eq$Report){throw 'Production Doctor report is missing.'}
    $errors=[int]$Report.errors
    $warnings=[int]$Report.warnings
    $warningRows=@($Report.findings|Where-Object{[string]$_.Severity-ceq'WARN'})
    if($errors-ne0){throw('Production Doctor reports errors='+$errors+'.')}
    if($ExitCode-eq0){
        if($warnings-ne0-or$warningRows.Count-ne0){throw 'Production Doctor exit=0 is inconsistent with warning findings.'}
        return $false
    }
    if($ExitCode-ne2){throw('Production Doctor failed with non-transition exit='+$ExitCode+'.')}
    if($warnings-lt1-or$warningRows.Count-ne$warnings){throw 'Production Doctor exit=2 warning count/report findings are inconsistent.'}
    foreach($finding in $warningRows){
        if(-not(Test-IsPermittedTransitionDoctorWarning $finding)){
            throw('Production Doctor rejected non-transition warning: '+[string]$finding.Code+'; '+[string]$finding.Message)
        }
    }
    return $true
}
$artifactsRoot=[System.IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
$testedPath=Join-Path $artifactsRoot 'TESTED_RELEASE.json'
if(-not(Test-Path -LiteralPath $testedPath -PathType Leaf)){throw('TESTED_RELEASE.json missing: '+$testedPath)}
$tested=(Get-Content -LiteralPath $testedPath -Raw -Encoding UTF8)|ConvertFrom-Json
if([string]$tested.schema-ne'keelaryn.manager-tested-release.v1'-or[string]$tested.status-ne'full_gate_passed'){throw 'Tested release metadata is not PASS.'}
$resultsVersionRoot=Split-Path $artifactsRoot -Parent
$summaryPath=Join-Path $resultsVersionRoot 'GATE_SUMMARY.json'
if(-not(Test-Path -LiteralPath $summaryPath -PathType Leaf)){throw('GATE_SUMMARY.json missing: '+$summaryPath)}
$summary=(Get-Content -LiteralPath $summaryPath -Raw -Encoding UTF8)|ConvertFrom-Json
if([string]$summary.status-ne'passed'-or[string]$summary.manager_version-ne[string]$tested.manager_version-or[int]$summary.gate_revision-ne[int]$tested.gate_revision){throw 'Gate summary does not match tested release metadata.'}
$updatePath=Join-Path $artifactsRoot ([string]$tested.update.file)
if(-not(Test-Path -LiteralPath $updatePath -PathType Leaf)){throw('Tested UPDATE missing: '+$updatePath)}
if((Sha $updatePath)-ne([string]$tested.update.sha256).ToLowerInvariant()){throw 'Tested UPDATE hash mismatch.'}
if([int64](Get-Item -LiteralPath $updatePath -Force).Length-ne[int64]$tested.update.bytes){throw 'Tested UPDATE size mismatch.'}
Write-Host 'TESTED UPDATE VALIDATION: PASS' -ForegroundColor Green
Write-Host ('Package: '+$updatePath)
if($ValidateOnly){exit 0}
$resultsRoot=Split-Path $resultsVersionRoot -Parent
$testsRoot=Split-Path $resultsRoot -Parent
$keelarynRoot=Split-Path $testsRoot -Parent
$managerRoot=Join-Path $keelarynRoot 'manager'
$installPath=Join-Path $managerRoot 'product\install\INSTALLATION.json'
$frontend=Join-Path $managerRoot 'product\tools\KeelarynMenu.ps1'
$runtime=Join-Path $managerRoot 'product\runtime\Keelaryn__Manager.ps1'
foreach($p in @($installPath,$frontend,$runtime)){if(-not(Test-Path -LiteralPath $p -PathType Leaf)){throw('Production Manager file missing: '+$p)}}
$current=[version][string]((Get-Content -LiteralPath $installPath -Raw -Encoding UTF8|ConvertFrom-Json).manager_version)
$target=[version][string]$tested.manager_version
$baseline=[version][string]$tested.baseline_version
if($current-gt$target){throw('Refusing downgrade: production Manager '+$current+' is newer than tested '+$target+'.')}
if($current-ne$target-and$current-ne$baseline){throw('Refusing untested install path: Full Gate validated '+$baseline+' -> '+$target+', but production is '+$current+'.')}
$exe=Join-Path $PSHOME 'powershell.exe'
if($current-lt$target){
    & $exe -NoProfile -ExecutionPolicy Bypass -File $frontend -Action ImportPackage -Path $updatePath -Replace -NoRootLauncher
    if([int]$LASTEXITCODE-ne0){throw('Production update failed. ExitCode='+[int]$LASTEXITCODE)}
}else{Write-Host ('Manager '+$target+' is already installed. Running fresh Doctor.') -ForegroundColor DarkGray}
& $exe -NoProfile -ExecutionPolicy Bypass -File $runtime -Doctor
$doctorExit=[int]$LASTEXITCODE
$doctorReport=Get-ProductionDoctorReport $managerRoot
$transitionWarning=[bool](Assert-ProductionDoctorResult $doctorExit $doctorReport)
if($transitionWarning){
    $messages=@($doctorReport.findings|Where-Object{[string]$_.Severity-ceq'WARN'}|ForEach-Object{[string]$_.Message})
    Write-Host ('PRODUCTION DOCTOR: PASS WITH TRANSITION WARNINGS - '+([string]::Join(' | ',$messages))) -ForegroundColor Yellow
}else{
    Write-Host 'PRODUCTION DOCTOR: PASS' -ForegroundColor Green
}
$installed=[version][string]((Get-Content -LiteralPath $installPath -Raw -Encoding UTF8|ConvertFrom-Json).manager_version)
if($installed-ne$target){throw('Installed Manager version mismatch after update: '+$installed+' != '+$target)}
Write-Host ('PRODUCTION INSTALL: PASS - Manager '+$target) -ForegroundColor Green
'@
$installerPath=Join-Path $artifactsRoot 'Install-TestedManagerUpdate.ps1'
Write-Utf8NoBom $installerPath $installerPs
$installerCmd=Join-Path $artifactsRoot 'INSTALL_TESTED_MANAGER_UPDATE.cmd'
$cmdText='@echo off'+"`r`n"+'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-TestedManagerUpdate.ps1"'+"`r`n"+'set "RC=%ERRORLEVEL%"'+"`r`n"+'echo.'+"`r`n"+'if "%RC%"=="0" (echo Tested Manager installation completed.) else (echo Tested Manager installation failed. ExitCode=%RC%)'+"`r`n"+'pause'+"`r`n"+'exit /b %RC%'+"`r`n"
[System.IO.File]::WriteAllText($installerCmd,$cmdText,[System.Text.Encoding]::ASCII)

Write-Host ('Tested Manager UPDATE: '+$destUpdate) -ForegroundColor Green
Write-Host ('One-click installer: '+$installerCmd) -ForegroundColor Green
Write-Output ('KEELARYN_TESTED_UPDATE_PATH:'+ $destUpdate)
Write-Output ('KEELARYN_TESTED_INSTALLER_PATH:'+ $installerCmd)
