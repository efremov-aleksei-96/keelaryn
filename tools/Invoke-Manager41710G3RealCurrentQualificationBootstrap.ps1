[CmdletBinding()]
param(
    [string]$KeelarynRoot = 'D:\0\0__Core\keelaryn',
    [string]$InboxRoot = 'D:\0\1__Inbox'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repo = 'efremov-aleksei-96/keelaryn'
$runId = '34762615650'
$artifactName = 'manager-4.17.10-g3-hosted-qualification'
$expectedVersion = '4.17.10'
$expectedBaseline = '4.17.9'
$expectedCandidate = 'af128f0f10752ff1500155707b56260aac296569'
$expectedGateSha256 = '83ba8110017ba40b3bf4400d3ef52012ec2eee65fce9ad9fe34e20b1d711cf3c'
$unpack = Join-Path $KeelarynRoot 'tests\UNPACK_MANAGER_GATE.cmd'
$installation = Join-Path $KeelarynRoot 'manager\product\install\INSTALLATION.json'
$issuedGate = Join-Path $InboxRoot ('manager-' + $expectedVersion + '.zip')
$downloadRoot = Join-Path ([IO.Path]::GetTempPath()) ('keelaryn-manager-' + $expectedVersion + '-g3-' + [Guid]::NewGuid().ToString('N'))

function Fail([string]$Message) {
    throw ('Manager ' + $expectedVersion + ' g3 real-current bootstrap: ' + $Message)
}

Write-Host '=== KEELARYN MANAGER 4.17.10 g3 REAL-CURRENT QUALIFICATION BOOTSTRAP ===' -ForegroundColor Cyan
Write-Host ('Frozen candidate: ' + $expectedCandidate)
Write-Host ('Hosted qualification run: ' + $runId)
Write-Host ('Expected ordinary g3 gate SHA-256: ' + $expectedGateSha256)
Write-Host 'This bootstrap does not install Manager 4.17.10. Full Gate remains production-read-only.'

if (-not (Test-Path -LiteralPath $KeelarynRoot -PathType Container)) { Fail ('Keelaryn root is missing: ' + $KeelarynRoot) }
if (-not (Test-Path -LiteralPath $unpack -PathType Leaf)) { Fail ('UNPACK_MANAGER_GATE.cmd is missing: ' + $unpack) }
if (-not (Test-Path -LiteralPath $installation -PathType Leaf)) { Fail ('production INSTALLATION.json is missing: ' + $installation) }

$installed = Get-Content -LiteralPath $installation -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$installed.manager_version -cne $expectedBaseline) {
    Fail ('production Manager baseline must be exactly ' + $expectedBaseline + '; observed ' + [string]$installed.manager_version)
}
Write-Host ('Production Manager baseline: ' + $expectedBaseline + ' PASS') -ForegroundColor Green

$gh = Get-Command gh.exe -ErrorAction SilentlyContinue
if ($null -eq $gh) { $gh = Get-Command gh -ErrorAction SilentlyContinue }
if ($null -eq $gh) { Fail 'GitHub CLI (gh) is not available in PATH.' }

& $gh.Source auth status --hostname github.com *> $null
if ($LASTEXITCODE -ne 0) { Fail 'GitHub CLI is not authenticated for github.com.' }

New-Item -ItemType Directory -Force -Path $downloadRoot | Out-Null
try {
    Write-Host 'Downloading exact hosted qualification artifact...'
    & $gh.Source run download $runId --repo $repo --name $artifactName --dir $downloadRoot
    if ($LASTEXITCODE -ne 0) { Fail ('gh run download failed with exit code ' + $LASTEXITCODE) }

    $receiptPath = Join-Path $downloadRoot 'HOSTED_QUALIFICATION.json'
    if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) { Fail 'HOSTED_QUALIFICATION.json is missing from hosted artifact root.' }
    $receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$receipt.manager_version -cne $expectedVersion) { Fail ('hosted receipt Manager mismatch: ' + [string]$receipt.manager_version) }
    if ([string]$receipt.candidate_revision -cne 'g3') { Fail ('hosted receipt candidate revision mismatch: ' + [string]$receipt.candidate_revision) }
    if ([string]$receipt.candidate_commit -cne $expectedCandidate) { Fail ('hosted receipt candidate commit mismatch: ' + [string]$receipt.candidate_commit) }
    if ([string]$receipt.baseline_version -cne $expectedBaseline) { Fail ('hosted receipt baseline mismatch: ' + [string]$receipt.baseline_version) }
    if ([string]$receipt.ordinary_gate_sha256 -cne $expectedGateSha256) { Fail ('hosted receipt gate SHA mismatch: ' + [string]$receipt.ordinary_gate_sha256) }
    if (-not [bool]$receipt.source_gate_pass -or -not [bool]$receipt.disposable_full_gate_pass) { Fail 'hosted qualification did not record both SourceGate and disposable Full Gate PASS.' }
    if ([bool]$receipt.production_qualified) { Fail 'hosted receipt must not claim production qualification.' }
    if (-not [bool]$receipt.requires_real_current_backed_gate) { Fail 'hosted receipt does not require real-current qualification.' }
    Write-Host 'Hosted qualification receipt identity: PASS' -ForegroundColor Green

    $downloadedGate = Join-Path $downloadRoot ('manager-' + $expectedVersion + '.zip')
    if (-not (Test-Path -LiteralPath $downloadedGate -PathType Leaf)) {
        Fail ('artifact-root ordinary gate is missing: ' + $downloadedGate)
    }

    $actual = (Get-FileHash -LiteralPath $downloadedGate -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -cne $expectedGateSha256) { Fail ('gate SHA-256 mismatch; expected ' + $expectedGateSha256 + '; observed ' + $actual) }
    Write-Host ('Hosted gate identity: PASS ' + $actual) -ForegroundColor Green

    New-Item -ItemType Directory -Force -Path $InboxRoot | Out-Null
    if (Test-Path -LiteralPath $issuedGate -PathType Leaf) {
        $existing = (Get-FileHash -LiteralPath $issuedGate -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($existing -cne $expectedGateSha256) {
            Fail ('refusing to overwrite mismatched existing gate: ' + $issuedGate + '; observed ' + $existing)
        }
        Write-Host ('Existing issued gate already has exact identity: ' + $issuedGate)
    }
    else {
        $stage = $issuedGate + '.tmp-' + [Guid]::NewGuid().ToString('N')
        Copy-Item -LiteralPath $downloadedGate -Destination $stage
        $stageSha = (Get-FileHash -LiteralPath $stage -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($stageSha -cne $expectedGateSha256) {
            Remove-Item -LiteralPath $stage -Force -ErrorAction SilentlyContinue
            Fail ('staged gate SHA-256 changed unexpectedly: ' + $stageSha)
        }
        Move-Item -LiteralPath $stage -Destination $issuedGate
        Write-Host ('Issued exact gate: ' + $issuedGate)
    }

    Write-Host ''
    Write-Host 'Launching the established Manager gate unpacker.' -ForegroundColor Cyan
    Write-Host ('Target contract: ' + (Join-Path $KeelarynRoot ('tests\work\manager-' + $expectedVersion)))
    Write-Host 'The unpacker will launch the validated Full Gate. Production Manager/Hub must remain unchanged during qualification.'
    Write-Host ''

    & $unpack $issuedGate
    $exit = $LASTEXITCODE
    if ($exit -ne 0) { Fail ('UNPACK_MANAGER_GATE / Full Gate returned exit code ' + $exit) }

    Write-Host ''
    Write-Host 'REAL-CURRENT QUALIFICATION LAUNCH COMPLETED WITH EXIT 0.' -ForegroundColor Green
    Write-Host 'Do not install Manager 4.17.10 yet. Preserve the complete Full Gate output/results for review.'
}
finally {
    if (Test-Path -LiteralPath $downloadRoot) {
        Remove-Item -LiteralPath $downloadRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
