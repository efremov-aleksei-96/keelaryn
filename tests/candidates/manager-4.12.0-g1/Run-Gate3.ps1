[CmdletBinding()]
param()
$ErrorActionPreference='Stop'

$root=[System.IO.Path]::GetFullPath($env:GITHUB_WORKSPACE)
if([string]::IsNullOrWhiteSpace($root)){throw 'GITHUB_WORKSPACE is unavailable.'}
$runnerTemp=[System.IO.Path]::GetFullPath($env:RUNNER_TEMP)
if([string]::IsNullOrWhiteSpace($runnerTemp)){throw 'RUNNER_TEMP is unavailable.'}

function Run-External([scriptblock]$Action,[string]$Failure){
    & $Action
    if($LASTEXITCODE-ne0){throw $Failure}
}
function Hash([string]$Path){return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}
function Write-Utf8NoBom([string]$Path,[string]$Text){[System.IO.File]::WriteAllText($Path,$Text,(New-Object System.Text.UTF8Encoding($false)))}
function Write-Ascii([string]$Path,[string]$Text){[System.IO.File]::WriteAllText($Path,$Text,(New-Object System.Text.ASCIIEncoding))}
function Normalize-LfAscii([string]$Path){
    $text=[System.Text.Encoding]::ASCII.GetString([System.IO.File]::ReadAllBytes($Path)).Replace("`r`n","`n")
    Write-Ascii $Path $text
}
function Restore-CrlfAscii([string]$Path){
    $text=[System.IO.File]::ReadAllText($Path,[System.Text.Encoding]::ASCII).Replace("`r`n","`n").Replace("`n","`r`n")
    Write-Ascii $Path $text
}
function Invoke-Menu([string]$MenuPath,[string]$InputText){
    $psi=New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName=(Join-Path $PSHOME 'powershell.exe')
    $psi.Arguments='-NoProfile -ExecutionPolicy Bypass -File "'+$MenuPath+'" -Action Menu -NoRootLauncher'
    $psi.UseShellExecute=$false
    $psi.RedirectStandardInput=$true
    $psi.RedirectStandardOutput=$true
    $psi.RedirectStandardError=$true
    $p=New-Object System.Diagnostics.Process
    $p.StartInfo=$psi
    [void]$p.Start()
    $outTask=$p.StandardOutput.ReadToEndAsync()
    $errTask=$p.StandardError.ReadToEndAsync()
    $p.StandardInput.Write($InputText)
    $p.StandardInput.Close()
    $p.WaitForExit()
    $output=$outTask.Result+$errTask.Result
    if($p.ExitCode-ne0){throw("Menu process failed with "+$p.ExitCode+": "+$output)}
    return $output
}

Write-Host 'Gate3: verify qualified public 4.11.0 base' -ForegroundColor Cyan
powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'tools\Verify-PublicRepository.ps1') -RepositoryRoot $root
if($LASTEXITCODE-ne0){exit $LASTEXITCODE}
$install=Get-Content (Join-Path $root 'manager\product\install\INSTALLATION.json') -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$install.manager_version-ne'4.11.0'){throw 'Candidate patch base must be Manager 4.11.0.'}

Write-Host 'Gate3: reconstruct exact Manager 4.12.0 g1 bytes' -ForegroundColor Cyan
$parts=Join-Path $root 'tests\candidates\manager-4.12.0-g1'
$managerPatch=Join-Path $runnerTemp 'manager-4.12.0-g1.patch'
cmd.exe /d /c "copy /b `"$parts\part1.patch`"+`"$parts\part2.patch`"+`"$parts\part3.patch`"+`"$parts\part4.patch`" `"$managerPatch`" >nul"
if($LASTEXITCODE-ne0){throw 'Could not reconstruct Manager candidate patch.'}
$managerPatchText=[System.IO.File]::ReadAllText($managerPatch,[System.Text.Encoding]::UTF8).Replace("`r`n","`n")
Write-Utf8NoBom $managerPatch $managerPatchText
if((Hash $managerPatch)-ne'644c124a32c74fa229b79a8c7e0652fc88d18ca002dd214fe17fd86c74471383'){throw 'Manager candidate patch hash mismatch.'}
$menu=Join-Path $root 'manager\product\tools\KeelarynMenu.ps1'
Normalize-LfAscii $menu
git apply --check --whitespace=nowarn "$managerPatch"
if($LASTEXITCODE-ne0){throw 'Manager 4.12.0 patch does not apply cleanly.'}
git apply --whitespace=nowarn "$managerPatch"
if($LASTEXITCODE-ne0){throw 'Manager 4.12.0 patch application failed.'}
git diff --check
if($LASTEXITCODE-ne0){throw 'LF-normalized Manager candidate failed git diff --check.'}
Restore-CrlfAscii $menu
$installPath=Join-Path $root 'manager\product\install\INSTALLATION.json'
if((Hash $installPath)-ne'7d616af1999a0071299044ac4f5f72d14f1bd74f5bc4fb280714db2076efaf77'){throw 'Candidate INSTALLATION identity mismatch.'}

Write-Host 'Gate3: reconstruct Gate Framework r11' -ForegroundColor Cyan
$frameworkPatch=Join-Path $parts 'framework-r11.patch'
$canonicalFrameworkPatch=Join-Path $runnerTemp 'framework-r11.patch'
$frameworkPatchText=[System.IO.File]::ReadAllText($frameworkPatch,[System.Text.Encoding]::UTF8).Replace("`r`n","`n")
Write-Utf8NoBom $canonicalFrameworkPatch $frameworkPatchText
if((Hash $canonicalFrameworkPatch)-ne'24a8f1fcf07dde532cbe542354487e5b682babceaa2cde129ddb8b1397df48af'){throw 'Framework r11 patch hash mismatch.'}
$full=Join-Path $root 'tests\framework\manager-gate\templates\Run-KeelarynManagerFullGate.ps1'
$source=Join-Path $root 'tests\framework\manager-gate\templates\Run-KeelarynManagerSourceGate.ps1'
if((Hash $full)-ne'c6e1fc79e6ffff15baf69292d782134d3aae25334d7eb1b5a29b143766526d2a'){throw 'Frozen r9 FullGate identity mismatch.'}
if((Hash $source)-ne'a0afd33988451bf6af2460355ca5c8f577b7401a202734bb54dd660edccaf1eb'){throw 'Frozen r9 SourceGate identity mismatch.'}
Normalize-LfAscii $full
Normalize-LfAscii $source
git apply --check --whitespace=nowarn "$canonicalFrameworkPatch"
if($LASTEXITCODE-ne0){throw 'Framework r11 patch does not apply cleanly to LF-normalized frozen r9.'}
git apply --whitespace=nowarn "$canonicalFrameworkPatch"
if($LASTEXITCODE-ne0){throw 'Framework r11 patch application failed.'}
Restore-CrlfAscii $full
Restore-CrlfAscii $source
if((Hash $full)-ne'2e7ac7f14dc6528da6e1d75dc7c97e6f84839af451b86c572920c9bb8a308fb9'){throw 'Framework r11 FullGate identity mismatch.'}
if((Hash $source)-ne'fff6dccaea97695a68820fdd64115a4364fdc6248bbaf4a9c91db6926c4ef414'){throw 'Framework r11 SourceGate identity mismatch.'}
$frameworkMarker=(Get-Content (Join-Path $root 'tests\framework\manager-gate\FRAMEWORK_REVISION.txt') -Raw -Encoding UTF8).Trim()
if($frameworkMarker-ne'11'){throw 'Framework revision is not 11.'}

Write-Host 'Gate3: build Gate Revision 3 and bind candidate identity' -ForegroundColor Cyan
$builder=Join-Path $root 'tests\framework\manager-gate\Build-ManagerGate.ps1'
$gateZip=Join-Path $runnerTemp 'manager-4.12.0.zip'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $builder -SourceRoot (Join-Path $root 'manager') -BaselineVersion '4.11.0' -GateRevision 3 -OutputPath $gateZip -Force
if($LASTEXITCODE-ne0){exit $LASTEXITCODE}
$work=Join-Path $root 'tests\work'
Expand-Archive -LiteralPath $gateZip -DestinationPath $work -Force
$candidate=Join-Path $work 'manager-4.12.0'
$spec=Get-Content (Join-Path $candidate 'gate\GATE_SPEC.json') -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$spec.candidate_version-ne'4.12.0'){throw 'Candidate version mismatch.'}
if([string]$spec.baseline_manager_version-ne'4.11.0'){throw 'Baseline mismatch.'}
if([int]$spec.framework_revision-ne11){throw 'Expected Gate Framework revision 11.'}
if([int]$spec.gate_revision-ne3){throw 'Expected Gate Revision 3.'}
if([string]$spec.candidate_installation_sha256-ne'7d616af1999a0071299044ac4f5f72d14f1bd74f5bc4fb280714db2076efaf77'){throw 'INSTALLATION identity differs from Manager g1.'}
if([string]$spec.candidate_managed_content_sha256-ne'fb0137c9485475ba7af069d5f1b7fe97c1b16121b9b97d47b3669e0cd435b32b'){throw 'Managed-content identity differs from Manager g1.'}
$env:CANDIDATE_ROOT=$candidate
$env:CANDIDATE_GATE_ZIP=$gateZip
Write-Host ('Gate3 ZIP SHA256: '+(Hash $gateZip))

Write-Host 'Gate3: Windows PowerShell 5.1 SourceGate' -ForegroundColor Cyan
powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $candidate 'gate\Run-KeelarynManagerSourceGate.ps1') -ManagerRoot $candidate
if($LASTEXITCODE-ne0){exit $LASTEXITCODE}

Write-Host 'Gate3: prepare immutable 4.11.0 CURRENT-backed fixture' -ForegroundColor Cyan
$published=Join-Path $runnerTemp 'Keelaryn_v4.11.0_Windows.zip'
Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/efremov-aleksei-96/keelaryn/releases/download/v4.11.0/Keelaryn_v4.11.0_Windows.zip' -OutFile $published
if((Hash $published)-ne'c4a3412d7a6e633f892b2451576c619c6de95375b8ba13aa818deb0f7b6e4241'){throw 'Published 4.11.0 distribution hash mismatch.'}
$fixtureParent=Join-Path $runnerTemp ('production_fixture_'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $fixtureParent|Out-Null
Expand-Archive -LiteralPath $published -DestinationPath $fixtureParent -Force
$production=Join-Path $fixtureParent 'keelaryn'
$runtime=Join-Path $production 'manager\product\runtime\Keelaryn__Manager.ps1'
$cfgPath=Join-Path $fixtureParent 'genesis.json'
$cfg=[ordered]@{schema='keelaryn.genesis-input.v1';language='en';purpose='mixed';timezone='UTC';areas=@('Fixture');projects=@('Baseline')}
Write-Utf8NoBom $cfgPath (($cfg|ConvertTo-Json -Depth 5)+"`n")
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $runtime -Genesis -GenesisConfigPath $cfgPath -GenesisConfirmed
if($LASTEXITCODE-ne0){exit $LASTEXITCODE}
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $runtime -Doctor
if($LASTEXITCODE-ne0){exit $LASTEXITCODE}

Write-Host 'Gate3: CURRENT-backed disposable Full Gate' -ForegroundColor Cyan
powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $candidate 'gate\Run-KeelarynManagerFullGate.ps1') -CandidateRoot $candidate -ProductionRoot $production
if($LASTEXITCODE-ne0){exit $LASTEXITCODE}

Write-Host 'Gate3: build Generic DISTRIBUTION for first-run UX smoke' -ForegroundColor Cyan
$candidateRuntime=Join-Path $candidate 'product\runtime\Keelaryn__Manager.ps1'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $candidateRuntime -BuildRelease
if($LASTEXITCODE-ne0){exit $LASTEXITCODE}
$dist=Join-Path $candidate '_releases\Keelaryn__Manager_Distribution_v4.12.0.zip'
if(-not(Test-Path -LiteralPath $dist -PathType Leaf)){throw 'Candidate Generic DISTRIBUTION missing.'}

Write-Host 'Gate3: first-run and source-checkout recovery UX' -ForegroundColor Cyan
$first=Join-Path $runnerTemp ('first_'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $first|Out-Null
Expand-Archive -LiteralPath $dist -DestinationPath $first -Force
$firstMenu=Join-Path $first 'keelaryn\manager\product\tools\KeelarynMenu.ps1'
$output=Invoke-Menu $firstMenu "3`r`n0`r`n"
foreach($token in @('Welcome to Keelaryn','Create a new Hub','Connect an existing Hub','Everyday')){
    if(-not$output.Contains($token)){throw("First-run output missing: "+$token)}
}

$collision=Join-Path $runnerTemp ('collision_'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $collision|Out-Null
Expand-Archive -LiteralPath $dist -DestinationPath $collision -Force
$collisionRoot=Join-Path $collision 'keelaryn'
$collisionHub=Join-Path $collisionRoot 'hub'
New-Item -ItemType Directory -Path $collisionHub|Out-Null
Set-Content -LiteralPath (Join-Path $collisionHub 'README.md') -Value 'repository boundary marker' -Encoding ASCII
$collisionMenu=Join-Path $collisionRoot 'manager\product\tools\KeelarynMenu.ps1'
$output=Invoke-Menu $collisionMenu "3`r`n0`r`n"
foreach($token in @('not an empty first-run state','Genesis will not overwrite it','source checkout is not a clean runtime installation')){
    if(-not$output.Contains($token)){throw("Recovery output missing: "+$token)}
}

Write-Host 'MANAGER 4.12.0 G1 / GATE REVISION 3 / FRAMEWORK R11 PASS' -ForegroundColor Green
