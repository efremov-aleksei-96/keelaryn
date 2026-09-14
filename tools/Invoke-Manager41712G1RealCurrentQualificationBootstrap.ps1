[CmdletBinding()]
param(
    [string]$KeelarynRoot = 'D:\0\0__Core\keelaryn',
    [string]$InboxRoot = 'D:\0\1__Inbox'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repo = 'efremov-aleksei-96/keelaryn'
$runId = '34809456682'
$artifactName = 'manager-4.17.12-g1-hosted-qualification'
$expectedVersion = '4.17.12'
$expectedBaseline = '4.17.11'
$expectedCandidate = '3dde367f1bd83f661bd29c75912732e9f92efa02'
$expectedCandidateTree = '63e42a5bfdd6000ee273f5f927902f6ac29703b6'
$expectedDevelopmentParent = '9c639cc954fef5e8a17966c43636c3d86b93a6a7'
$expectedBaselineCommit = 'f6d04c175a22bd44f15c3d699a05ab5d60fa9a83'
$expectedGateSha256 = 'd256df61396fa2afa08916b7ac3efb41e2ba4c9dcfc6556fbe61a6f774396200'
$expectedManagedDigest = '5118a866aa54ed916bb087fe41a4ac724bf527181b79b1c34e9b29311bf10fb8'
$expectedInstallationSha256 = 'f66f83aba661868c6ff5007e77f96b3be8be34536000c060cdd0017dcf553b5d'
$expectedBaselineInstallationSha256 = 'cd531baa24836a518afdf582e5313006cdc503fcc212b8b1bcffbb7c55ae2bfc'
$unpack = Join-Path $KeelarynRoot 'tests\UNPACK_MANAGER_GATE.cmd'
$installation = Join-Path $KeelarynRoot 'manager\product\install\INSTALLATION.json'
$registry = Join-Path $KeelarynRoot 'manager\state\instances.json'
$issuedGate = Join-Path $InboxRoot ('manager-' + $expectedVersion + '.zip')
$downloadRoot = Join-Path ([IO.Path]::GetTempPath()) ('keelaryn-manager-' + $expectedVersion + '-g1-' + [Guid]::NewGuid().ToString('N'))

function Fail([string]$Message) {
    throw ('Manager ' + $expectedVersion + ' g1 real-current bootstrap: ' + $Message)
}

Write-Host '=== KEELARYN MANAGER 4.17.12 g1 REAL-CURRENT QUALIFICATION BOOTSTRAP ===' -ForegroundColor Cyan
Write-Host ('Frozen candidate: ' + $expectedCandidate)
Write-Host ('Frozen tree: ' + $expectedCandidateTree)
Write-Host ('Hosted qualification run: ' + $runId)
Write-Host ('Expected ordinary g1 gate SHA-256: ' + $expectedGateSha256)
Write-Host 'This bootstrap does not install Manager 4.17.12. Full Gate remains production-read-only.'

if (-not (Test-Path -LiteralPath $KeelarynRoot -PathType Container)) { Fail ('Keelaryn root is missing: ' + $KeelarynRoot) }
if (-not (Test-Path -LiteralPath $unpack -PathType Leaf)) { Fail ('UNPACK_MANAGER_GATE.cmd is missing: ' + $unpack) }
if (-not (Test-Path -LiteralPath $installation -PathType Leaf)) { Fail ('production INSTALLATION.json is missing: ' + $installation) }

$installed = Get-Content -LiteralPath $installation -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$installed.manager_version -cne $expectedBaseline) {
    Fail ('production Manager baseline must be exactly ' + $expectedBaseline + '; observed ' + [string]$installed.manager_version)
}
$installedInstallationSha = (Get-FileHash -LiteralPath $installation -Algorithm SHA256).Hash.ToLowerInvariant()
if ($installedInstallationSha -cne $expectedBaselineInstallationSha256) {
    Fail ('production Manager INSTALLATION identity mismatch; expected ' + $expectedBaselineInstallationSha256 + '; observed ' + $installedInstallationSha)
}
if (Test-Path -LiteralPath $registry -PathType Leaf) {
    Fail ('production multi-Hub registry is active unexpectedly: ' + $registry)
}
Write-Host ('Production Manager baseline: ' + $expectedBaseline + ' PASS') -ForegroundColor Green
Write-Host ('Production INSTALLATION identity: PASS ' + $installedInstallationSha) -ForegroundColor Green
Write-Host 'Production multi-Hub state: inactive as required.' -ForegroundColor Green

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
    if ([string]$receipt.candidate_revision -cne 'g1') { Fail ('hosted receipt candidate revision mismatch: ' + [string]$receipt.candidate_revision) }
    if ([string]$receipt.candidate_commit -cne $expectedCandidate) { Fail ('hosted receipt candidate commit mismatch: ' + [string]$receipt.candidate_commit) }
    if ([string]$receipt.candidate_tree -cne $expectedCandidateTree) { Fail ('hosted receipt candidate tree mismatch: ' + [string]$receipt.candidate_tree) }
    if ([string]$receipt.validated_development_parent -cne $expectedDevelopmentParent) { Fail ('hosted receipt development parent mismatch: ' + [string]$receipt.validated_development_parent) }
    if ([string]$receipt.baseline_version -cne $expectedBaseline) { Fail ('hosted receipt baseline mismatch: ' + [string]$receipt.baseline_version) }
    if ([string]$receipt.baseline_commit -cne $expectedBaselineCommit) { Fail ('hosted receipt baseline commit mismatch: ' + [string]$receipt.baseline_commit) }
    if ([string]$receipt.managed_digest -cne $expectedManagedDigest) { Fail ('hosted receipt managed digest mismatch: ' + [string]$receipt.managed_digest) }
    if ([string]$receipt.installation_sha256 -cne $expectedInstallationSha256) { Fail ('hosted receipt installation SHA mismatch: ' + [string]$receipt.installation_sha256) }
    if ([string]$receipt.ordinary_gate_sha256 -cne $expectedGateSha256) { Fail ('hosted receipt gate SHA mismatch: ' + [string]$receipt.ordinary_gate_sha256) }
    if (-not [bool]$receipt.strict_risk_defect_gate_pass) { Fail 'hosted receipt did not record strict Risk/Defect Gate PASS.' }
    if (-not [bool]$receipt.risk_context_lifecycle_regression_pass) { Fail 'hosted receipt did not record risk-context lifecycle regression PASS.' }
    if (-not [bool]$receipt.release_instruction_identity_pass) { Fail 'hosted receipt did not record release-instruction identity PASS.' }
    if (-not [bool]$receipt.manager_41712_review_regression_pass) { Fail 'hosted receipt did not record Manager 4.17.12 regression PASS.' }
    if ([string]$receipt.prefreeze_adversarial_review -cne 'pass_no_open_findings') { Fail ('hosted receipt adversarial-review state mismatch: ' + [string]$receipt.prefreeze_adversarial_review) }
    if (-not [bool]$receipt.source_gate_pass -or -not [bool]$receipt.disposable_full_gate_pass) { Fail 'hosted qualification did not record SourceGate + disposable Full Gate PASS.' }
    if ([bool]$receipt.production_qualified) { Fail 'hosted receipt must not claim production qualification.' }
    if (-not [bool]$receipt.requires_real_current_backed_gate) { Fail 'hosted receipt does not require real-current qualification.' }
    Write-Host 'Hosted qualification receipt identity: PASS' -ForegroundColor Green

    $downloadedGate = Join-Path $downloadRoot ('manager-' + $expectedVersion + '.zip')
    if (-not (Test-Path -LiteralPath $downloadedGate -PathType Leaf)) { Fail ('ordinary gate is missing: ' + $downloadedGate) }
    $actual = (Get-FileHash -LiteralPath $downloadedGate -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -cne $expectedGateSha256) { Fail ('gate SHA-256 mismatch; expected ' + $expectedGateSha256 + '; observed ' + $actual) }
    Write-Host ('Hosted gate identity: PASS ' + $actual) -ForegroundColor Green

    New-Item -ItemType Directory -Force -Path $InboxRoot | Out-Null
    if (Test-Path -LiteralPath $issuedGate -PathType Leaf) {
        $existing = (Get-FileHash -LiteralPath $issuedGate -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($existing -cne $expectedGateSha256) { Fail ('refusing to overwrite mismatched existing gate: ' + $issuedGate + '; observed ' + $existing) }
        Write-Host ('Existing issued gate already has exact identity: ' + $issuedGate)
    } else {
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
    Write-Host 'Launching established UNPACK_MANAGER_GATE.cmd...' -ForegroundColor Cyan
    Write-Host ('Target: ' + (Join-Path $KeelarynRoot ('tests\work\manager-' + $expectedVersion)))
    & $unpack $issuedGate
    $exit = $LASTEXITCODE
    if ($exit -ne 0) { Fail ('UNPACK_MANAGER_GATE / Full Gate returned exit code ' + $exit) }

    $resultsRoot = Join-Path $KeelarynRoot ('tests\results\manager-' + $expectedVersion)
    $fullGateResult = Join-Path $resultsRoot 'FULL_GATE_RESULT.json'
    $testedUpdate = Join-Path $resultsRoot ('artifacts\Keelaryn__Manager_Update_v' + $expectedVersion + '_Built.zip')
    $installer = Join-Path $resultsRoot 'artifacts\INSTALL_TESTED_MANAGER_UPDATE.cmd'
    if (-not (Test-Path -LiteralPath $fullGateResult -PathType Leaf)) { Fail ('Full Gate receipt is missing: ' + $fullGateResult) }
    if (-not (Test-Path -LiteralPath $testedUpdate -PathType Leaf)) { Fail ('tested UPDATE is missing after Full Gate: ' + $testedUpdate) }
    if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) { Fail ('tested installer is missing after Full Gate: ' + $installer) }
    $full = Get-Content -LiteralPath $fullGateResult -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not [bool]$full.pass) { Fail 'FULL_GATE_RESULT.json does not record PASS.' }
    $testedUpdateSha = (Get-FileHash -LiteralPath $testedUpdate -Algorithm SHA256).Hash.ToLowerInvariant()

    Write-Host ''
    Write-Host 'REAL-CURRENT QUALIFICATION COMPLETED WITH EXIT 0.' -ForegroundColor Green
    Write-Host ('TESTED_UPDATE_SHA256=' + $testedUpdateSha) -ForegroundColor Green
    Write-Host ('FULL_GATE_RESULT=' + $fullGateResult)
    Write-Host ('TESTED_UPDATE_PATH=' + $testedUpdate)
    Write-Host ('TESTED_INSTALLER_PATH=' + $installer)
    Write-Host 'Do not install Manager 4.17.12 yet. Preserve the complete Full Gate output/results for review.'
}
finally {
    if (Test-Path -LiteralPath $downloadRoot) {
        Remove-Item -LiteralPath $downloadRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
