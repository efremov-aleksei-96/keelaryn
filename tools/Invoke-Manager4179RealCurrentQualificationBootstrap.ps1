[CmdletBinding()]
param(
    [string]$KeelarynRoot = 'D:\0\0__Core\keelaryn',
    [string]$InboxRoot = 'D:\0\1__Inbox'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repo = 'efremov-aleksei-96/keelaryn'
$runId = '34753663749'
$artifactName = 'manager-4.17.9-g1-hosted-qualification'
$expectedVersion = '4.17.9'
$expectedBaseline = '4.17.8'
$expectedGateSha256 = 'f0f62c19b52cc75cd75a0a6d7cff9495614ebc08a9a2ec4492cc075199d5fcba'
$unpack = Join-Path $KeelarynRoot 'tests\UNPACK_MANAGER_GATE.cmd'
$installation = Join-Path $KeelarynRoot 'manager\product\install\INSTALLATION.json'
$issuedGate = Join-Path $InboxRoot ('manager-' + $expectedVersion + '.zip')
$downloadRoot = Join-Path ([IO.Path]::GetTempPath()) ('keelaryn-manager-' + $expectedVersion + '-g1-' + [Guid]::NewGuid().ToString('N'))

function Fail([string]$Message) {
    throw ('Manager ' + $expectedVersion + ' g1 real-current bootstrap: ' + $Message)
}

Write-Host '=== KEELARYN MANAGER 4.17.9 g1 REAL-CURRENT QUALIFICATION BOOTSTRAP ===' -ForegroundColor Cyan
Write-Host ('Frozen candidate: cb036051586d567502ce31ca8f1192a39bd69ddf')
Write-Host ('Hosted qualification run: ' + $runId)
Write-Host ('Expected gate SHA-256: ' + $expectedGateSha256)
Write-Host 'This bootstrap does not install Manager 4.17.9. Full Gate remains production-read-only.'

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

    $downloadedGate = Join-Path $downloadRoot ('manager-' + $expectedVersion + '.zip')
    if (-not (Test-Path -LiteralPath $downloadedGate -PathType Leaf)) {
        $matches = @(Get-ChildItem -LiteralPath $downloadRoot -Filter ('manager-' + $expectedVersion + '.zip') -File -Recurse)
        if ($matches.Count -ne 1) { Fail ('expected exactly one manager-' + $expectedVersion + '.zip in hosted artifact; observed ' + $matches.Count) }
        $downloadedGate = $matches[0].FullName
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
    Write-Host 'The unpacker will launch the validated Full Gate. Production Manager/Hub must remain unchanged during this qualification.'
    Write-Host ''

    & $unpack $issuedGate
    $exit = $LASTEXITCODE
    if ($exit -ne 0) { Fail ('UNPACK_MANAGER_GATE / Full Gate returned exit code ' + $exit) }

    Write-Host ''
    Write-Host 'REAL-CURRENT QUALIFICATION LAUNCH COMPLETED WITH EXIT 0.' -ForegroundColor Green
    Write-Host 'Do not install Manager 4.17.9 yet. Preserve the Full Gate output/results for review.'
}
finally {
    if (Test-Path -LiteralPath $downloadRoot) {
        Remove-Item -LiteralPath $downloadRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
