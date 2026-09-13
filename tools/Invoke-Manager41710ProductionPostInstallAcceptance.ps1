[CmdletBinding()]
param(
    [string]$KeelarynRoot = 'D:\0\0__Core\keelaryn'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$expectedVersion = '4.17.10'
$expectedUpdateSha256 = 'c3d005861f1c2b4e39e6a7bf826cbb4ff81460fd89a595592d1960a711277a6f'
$manager = Join-Path $KeelarynRoot 'manager\product\runtime\Keelaryn__Manager.ps1'
$ui = Join-Path $KeelarynRoot 'manager\product\tools\KeelarynMenu.ps1'
$installation = Join-Path $KeelarynRoot 'manager\product\install\INSTALLATION.json'
$hub = Join-Path $KeelarynRoot 'hub'
$testedUpdate = Join-Path $KeelarynRoot 'tests\results\manager-4.17.10\artifacts\Keelaryn__Manager_Update_v4.17.10_Built.zip'

function Fail([string]$Message) { throw ('Manager 4.17.10 production acceptance: ' + $Message) }

function Invoke-CapturedPowerShell([string]$Script,[string[]]$Arguments,[string]$Label) {
    $exe = Join-Path $PSHOME 'powershell.exe'
    $old = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = @(& $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Script @Arguments 2>&1)
        $exit = [int]$LASTEXITCODE
    }
    finally { $ErrorActionPreference = $old }
    foreach ($line in @($output)) { Write-Host ([string]$line) }
    if ($exit -ne 0) { Fail ($Label + ' failed with exit=' + $exit) }
    return @($output | ForEach-Object { [string]$_ })
}

function Get-PrivateTreeFingerprint([string]$Root) {
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { Fail ('Hub root missing: ' + $Root) }
    $fullRoot = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    $rows = New-Object System.Collections.ArrayList
    $stack = New-Object 'System.Collections.Generic.Stack[string]'
    $stack.Push($fullRoot)
    $totalBytes = [int64]0
    while ($stack.Count -gt 0) {
        $dir = $stack.Pop()
        foreach ($item in @(Get-ChildItem -LiteralPath $dir -Force -ErrorAction Stop)) {
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { Fail ('Hub tree contains reparse point: ' + $item.FullName) }
            if ($item.PSIsContainer) {
                $stack.Push($item.FullName)
                continue
            }
            $relative = $item.FullName.Substring($fullRoot.Length).TrimStart('\').Replace('\','/')
            $sha = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            $totalBytes += [int64]$item.Length
            [void]$rows.Add(($relative + '|' + $item.Length + '|' + $sha))
        }
    }
    $payload = [string]::Join("`n", @($rows | Sort-Object))
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($payload)
        $digest = (($sha256.ComputeHash($bytes) | ForEach-Object { $_.ToString('x2') }) -join '')
    }
    finally { $sha256.Dispose() }
    return [pscustomobject]@{ Count = $rows.Count; Bytes = $totalBytes; Digest = $digest }
}

Write-Host '=== KEELARYN MANAGER 4.17.10 PRODUCTION POST-INSTALL ACCEPTANCE ===' -ForegroundColor Cyan
Write-Host 'Read-only acceptance: Manager/frontend SelfTests, main render, installation info, Doctor, tested UPDATE identity, current Hub compatibility, and Hub immutability.'

foreach ($path in @($manager,$ui,$installation,$testedUpdate)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { Fail ('required file missing: ' + $path) }
}

$manifest = Get-Content -LiteralPath $installation -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$manifest.manager_version -cne $expectedVersion) { Fail ('installed Manager version must be ' + $expectedVersion + '; observed ' + [string]$manifest.manager_version) }
Write-Host ('Installed Manager version: ' + $expectedVersion + ' PASS') -ForegroundColor Green

$actualUpdateSha = (Get-FileHash -LiteralPath $testedUpdate -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualUpdateSha -cne $expectedUpdateSha256) { Fail ('tested UPDATE SHA mismatch; expected ' + $expectedUpdateSha256 + '; observed ' + $actualUpdateSha) }
Write-Host ('Tested UPDATE identity: PASS ' + $actualUpdateSha) -ForegroundColor Green

$hubBefore = Get-PrivateTreeFingerprint $hub
Write-Host ('Production Hub snapshot captured: files=' + $hubBefore.Count + '; bytes=' + $hubBefore.Bytes)

Write-Host ''
Write-Host '=== MANAGER SELFTEST ==='
[void](Invoke-CapturedPowerShell $manager @('-SelfTest') 'Manager SelfTest')

Write-Host ''
Write-Host '=== FRONTEND SELFTEST ==='
[void](Invoke-CapturedPowerShell $ui @('-SelfTest','-NoRootLauncher') 'Frontend SelfTest')

Write-Host ''
Write-Host '=== PRODUCTION MAIN RENDER ==='
$render = Invoke-CapturedPowerShell $ui @('-Action','RenderMain','-NoRootLauncher') 'RenderMain'
$renderText = [string]::Join("`n", $render)
foreach ($needle in @('Keelaryn','Keelaryn Manager 4.17.10','Everyday','[2] Doctor','[5] Installation info')) {
    if (-not $renderText.Contains($needle)) { Fail ('RenderMain missing required contract line: ' + $needle) }
}
Write-Host 'Production main render contract: PASS' -ForegroundColor Green

Write-Host ''
Write-Host '=== PRODUCTION INSTALLATION INFO ==='
$info = Invoke-CapturedPowerShell $ui @('-Action','InstanceInfo','-NoRootLauncher') 'Installation info'
$infoText = [string]::Join("`n", $info)
if ([string]::IsNullOrWhiteSpace($infoText)) { Fail 'Installation info returned no output.' }
if (-not $infoText.Contains('Version: 4.17.10')) { Fail 'Installation info does not identify Manager 4.17.10.' }
Write-Host 'Production installation info: PASS' -ForegroundColor Green

Write-Host ''
Write-Host '=== PRODUCTION DOCTOR ==='
$doctor = Invoke-CapturedPowerShell $manager @('-Doctor') 'Doctor'
$doctorText = [string]::Join("`n", $doctor)
if ($doctorText -match '(?m)^\s*\[(WARN|ERROR)\]') { Fail 'Doctor produced WARN or ERROR output.' }
foreach ($needle in @('[OK] manager.version: Manager version markers agree at 4.17.10.','[OK] instances.registry: Single-instance compatibility mode; multi-Hub registry is not initialized.','[OK] baseline.identity: Installed ARTIFACT and CURRENT identify ','[OK] baseline.current: Installed vault portable content exactly matches CURRENT;')) {
    if (-not $doctorText.Contains($needle)) { Fail ('Doctor missing required production acceptance line: ' + $needle) }
}
Write-Host 'Production Doctor/current-Hub compatibility: PASS' -ForegroundColor Green

$hubAfter = Get-PrivateTreeFingerprint $hub
if ($hubAfter.Count -ne $hubBefore.Count -or $hubAfter.Bytes -ne $hubBefore.Bytes -or $hubAfter.Digest -cne $hubBefore.Digest) {
    Fail ('production Hub changed during read-only acceptance; before files=' + $hubBefore.Count + ' bytes=' + $hubBefore.Bytes + '; after files=' + $hubAfter.Count + ' bytes=' + $hubAfter.Bytes)
}
Write-Host ('Production Hub immutable during acceptance: PASS files=' + $hubAfter.Count + '; bytes=' + $hubAfter.Bytes) -ForegroundColor Green

Write-Host ''
Write-Host 'MANAGER 4.17.10 PRODUCTION POST-INSTALL ACCEPTANCE: PASS' -ForegroundColor Green
Write-Host 'Current production Hub compatibility was validated at execution time; no personal Hub fingerprint is published.'
Write-Host 'Multi-Hub registry remains intentionally inactive. Public release/main merge still requires final review.'
