[CmdletBinding()]
param(
    [string]$KeelarynRoot = 'D:\0\0__Core\keelaryn',
    [string]$InboxRoot = 'D:\0\1__Inbox'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repo = 'efremov-aleksei-96/keelaryn'
$runId = '34812953426'
$artifactName = 'manager-4.17.12-g1-gate-r2'
$expectedVersion = '4.17.12'
$expectedBaseline = '4.17.11'
$expectedCandidate = '3dde367f1bd83f661bd29c75912732e9f92efa02'
$expectedCandidateTree = '63e42a5bfdd6000ee273f5f927902f6ac29703b6'
$expectedGateRevision = 2
$expectedGateSha256 = '0b027b87d4fb0c452990f19d4d9d4d6b7f48bf0a710e28aba74da42084a04a11'
$priorGateRevision = 1
$priorGateSha256 = 'd256df61396fa2afa08916b7ac3efb41e2ba4c9dcfc6556fbe61a6f774396200'
$expectedManagedDigest = '5118a866aa54ed916bb087fe41a4ac724bf527181b79b1c34e9b29311bf10fb8'
$expectedInstallationSha256 = 'f66f83aba661868c6ff5007e77f96b3be8be34536000c060cdd0017dcf553b5d'
$expectedBaselineInstallationSha256 = 'cd531baa24836a518afdf582e5313006cdc503fcc212b8b1bcffbb7c55ae2bfc'
$unpack = Join-Path $KeelarynRoot 'tests\UNPACK_MANAGER_GATE.cmd'
$installation = Join-Path $KeelarynRoot 'manager\product\install\INSTALLATION.json'
$registry = Join-Path $KeelarynRoot 'manager\state\instances.json'
$issuedGate = Join-Path $InboxRoot ('manager-' + $expectedVersion + '.zip')
$resultsRoot = Join-Path $KeelarynRoot ('tests\results\manager-' + $expectedVersion)
$workRoot = Join-Path $KeelarynRoot ('tests\work\manager-' + $expectedVersion)
$historyRoot = Join-Path $KeelarynRoot 'tests\results\history\manager-4.17.12-g1-gate-r1-real-current-fail-20260914T0615Z'
$historyResults = Join-Path $historyRoot 'results'
$historyGate = Join-Path $historyRoot 'manager-4.17.12-gate-r1.zip'
$historyClassification = Join-Path $historyRoot 'FAILURE_CLASSIFICATION.json'
$downloadRoot = Join-Path ([IO.Path]::GetTempPath()) ('keelaryn-manager-' + $expectedVersion + '-g1-r2-' + [Guid]::NewGuid().ToString('N'))

function Fail([string]$Message) {
    throw ('Manager ' + $expectedVersion + ' g1 gate-r2 real-current bootstrap: ' + $Message)
}

function Write-Utf8NoBom([string]$Path,[string]$Text) {
    [IO.File]::WriteAllText($Path,$Text,(New-Object Text.UTF8Encoding($false)))
}

Write-Host '=== KEELARYN MANAGER 4.17.12 g1 GATE-r2 REAL-CURRENT QUALIFICATION BOOTSTRAP ===' -ForegroundColor Cyan
Write-Host ('Frozen candidate: ' + $expectedCandidate)
Write-Host ('Frozen tree: ' + $expectedCandidateTree)
Write-Host ('Hosted gate-r2 qualification run: ' + $runId)
Write-Host ('Expected gate-r2 SHA-256: ' + $expectedGateSha256)
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
    Write-Host 'Downloading exact hosted gate-r2 qualification artifact...'
    & $gh.Source run download $runId --repo $repo --name $artifactName --dir $downloadRoot
    if ($LASTEXITCODE -ne 0) { Fail ('gh run download failed with exit code ' + $LASTEXITCODE) }

    $receiptPath = Join-Path $downloadRoot 'GATE_R2_QUALIFICATION.json'
    if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) { Fail 'GATE_R2_QUALIFICATION.json is missing from hosted artifact root.' }
    $receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$receipt.schema -cne 'keelaryn.manager-gate-revision-qualification.v1') { Fail ('gate-r2 receipt schema mismatch: ' + [string]$receipt.schema) }
    if ([string]$receipt.classification -cne 'gate_execution_revision_only') { Fail ('gate-r2 receipt classification mismatch: ' + [string]$receipt.classification) }
    if ([string]$receipt.manager_version -cne $expectedVersion) { Fail ('gate-r2 receipt Manager mismatch: ' + [string]$receipt.manager_version) }
    if ([string]$receipt.candidate_revision -cne 'g1') { Fail ('gate-r2 receipt candidate revision mismatch: ' + [string]$receipt.candidate_revision) }
    if ([string]$receipt.candidate_commit -cne $expectedCandidate) { Fail ('gate-r2 receipt candidate commit mismatch: ' + [string]$receipt.candidate_commit) }
    if ([string]$receipt.candidate_tree -cne $expectedCandidateTree) { Fail ('gate-r2 receipt candidate tree mismatch: ' + [string]$receipt.candidate_tree) }
    if ([string]$receipt.baseline_version -cne $expectedBaseline) { Fail ('gate-r2 receipt baseline mismatch: ' + [string]$receipt.baseline_version) }
    if ([int]$receipt.gate_revision -ne $expectedGateRevision) { Fail ('gate-r2 receipt revision mismatch: ' + [string]$receipt.gate_revision) }
    if ([int]$receipt.framework_revision -ne 24) { Fail ('gate-r2 receipt framework revision mismatch: ' + [string]$receipt.framework_revision) }
    if ([string]$receipt.managed_digest -cne $expectedManagedDigest) { Fail ('gate-r2 receipt managed digest mismatch: ' + [string]$receipt.managed_digest) }
    if ([string]$receipt.installation_sha256 -cne $expectedInstallationSha256) { Fail ('gate-r2 receipt installation SHA mismatch: ' + [string]$receipt.installation_sha256) }
    if ([string]$receipt.gate_sha256 -cne $expectedGateSha256) { Fail ('gate-r2 receipt gate SHA mismatch: ' + [string]$receipt.gate_sha256) }
    if (-not [bool]$receipt.source_gate_pass) { Fail 'gate-r2 hosted qualification did not record SourceGate PASS.' }
    if ([bool]$receipt.production_qualified) { Fail 'gate-r2 hosted receipt must not claim production qualification.' }
    Write-Host 'Hosted gate-r2 receipt identity: PASS' -ForegroundColor Green

    $downloadedGate = Join-Path $downloadRoot ('manager-' + $expectedVersion + '.zip')
    if (-not (Test-Path -LiteralPath $downloadedGate -PathType Leaf)) { Fail ('gate-r2 ZIP is missing: ' + $downloadedGate) }
    $actual = (Get-FileHash -LiteralPath $downloadedGate -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -cne $expectedGateSha256) { Fail ('gate-r2 SHA-256 mismatch; expected ' + $expectedGateSha256 + '; observed ' + $actual) }
    Write-Host ('Hosted gate-r2 identity: PASS ' + $actual) -ForegroundColor Green

    # Preserve the failed r1 qualification before any r2 publication or rerun.
    New-Item -ItemType Directory -Force -Path $historyRoot | Out-Null
    if (Test-Path -LiteralPath $resultsRoot -PathType Container) {
        if (Test-Path -LiteralPath $historyResults) { Fail ('historical r1 results destination already exists: ' + $historyResults) }
        Move-Item -LiteralPath $resultsRoot -Destination $historyResults
        Write-Host ('Preserved failed r1 results: ' + $historyResults) -ForegroundColor Yellow
    } elseif (-not (Test-Path -LiteralPath $historyResults -PathType Container)) {
        Fail ('neither current failed r1 results nor historical r1 results were found; refusing to lose qualification provenance')
    }

    $classification = [ordered]@{
        schema = 'keelaryn.manager-real-current-failure-classification.v1'
        manager_version = $expectedVersion
        candidate_revision = 'g1'
        candidate_commit = $expectedCandidate
        candidate_tree = $expectedCandidateTree
        gate_revision = $priorGateRevision
        gate_sha256 = $priorGateSha256
        classification = 'environment_or_measurement_ambiguity'
        product_failure = $false
        failed_phase = 'AI_CONTEXT performance control'
        failed_check = 'AI_CONTEXT benchmark threshold remains ambiguous around +5%.'
        benchmark_blocks = 15
        robust_block_delta_median_pct = 2.1
        block_delta_mad_pp = 7.0
        decision_margin_pp = 5.6
        threshold_pct = 5.0
        disposition = 'preserve_failed_evidence_and_repeat_same_frozen_candidate_under_new_gate_revision'
        product_bytes_changed = $false
        framework_bytes_changed = $false
        recorded_utc = [DateTime]::UtcNow.ToString('o')
    }
    Write-Utf8NoBom $historyClassification (($classification | ConvertTo-Json -Depth 8).Replace("`r`n","`n") + "`n")

    if (Test-Path -LiteralPath $issuedGate -PathType Leaf) {
        $existing = (Get-FileHash -LiteralPath $issuedGate -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($existing -ceq $priorGateSha256) {
            if (Test-Path -LiteralPath $historyGate -PathType Leaf) {
                $historySha = (Get-FileHash -LiteralPath $historyGate -Algorithm SHA256).Hash.ToLowerInvariant()
                if ($historySha -cne $priorGateSha256) { Fail ('historical r1 gate exists with wrong SHA: ' + $historySha) }
            } else {
                Copy-Item -LiteralPath $issuedGate -Destination $historyGate
                $historySha = (Get-FileHash -LiteralPath $historyGate -Algorithm SHA256).Hash.ToLowerInvariant()
                if ($historySha -cne $priorGateSha256) { Fail ('historical r1 gate copy SHA mismatch: ' + $historySha) }
            }
            Remove-Item -LiteralPath $issuedGate -Force
            Write-Host ('Preserved failed r1 gate: ' + $historyGate) -ForegroundColor Yellow
        } elseif ($existing -cne $expectedGateSha256) {
            Fail ('refusing to replace unrecognized existing gate: ' + $issuedGate + '; observed ' + $existing)
        }
    }

    # tests\work is disposable; failed durable evidence is already preserved under tests\results\history.
    if (Test-Path -LiteralPath $workRoot -PathType Container) {
        Remove-Item -LiteralPath $workRoot -Recurse -Force
        Write-Host ('Removed disposable r1 work tree: ' + $workRoot)
    }

    New-Item -ItemType Directory -Force -Path $InboxRoot | Out-Null
    if (Test-Path -LiteralPath $issuedGate -PathType Leaf) {
        $existing = (Get-FileHash -LiteralPath $issuedGate -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($existing -cne $expectedGateSha256) { Fail ('existing issued gate is not exact r2: ' + $existing) }
        Write-Host ('Exact gate-r2 already issued: ' + $issuedGate)
    } else {
        $stage = $issuedGate + '.tmp-' + [Guid]::NewGuid().ToString('N')
        Copy-Item -LiteralPath $downloadedGate -Destination $stage
        $stageSha = (Get-FileHash -LiteralPath $stage -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($stageSha -cne $expectedGateSha256) {
            Remove-Item -LiteralPath $stage -Force -ErrorAction SilentlyContinue
            Fail ('staged gate-r2 SHA changed unexpectedly: ' + $stageSha)
        }
        Move-Item -LiteralPath $stage -Destination $issuedGate
        Write-Host ('Issued exact gate-r2: ' + $issuedGate)
    }

    Write-Host ''
    Write-Host 'Launching established UNPACK_MANAGER_GATE.cmd for gate revision 2...' -ForegroundColor Cyan
    Write-Host ('Target: ' + $workRoot)
    & $unpack $issuedGate
    $exit = $LASTEXITCODE
    if ($exit -ne 0) { Fail ('UNPACK_MANAGER_GATE / Full Gate r2 returned exit code ' + $exit) }

    $fullGateResult = Join-Path $resultsRoot 'FULL_GATE_RESULT.json'
    $testedUpdate = Join-Path $resultsRoot ('artifacts\Keelaryn__Manager_Update_v' + $expectedVersion + '_Built.zip')
    $installer = Join-Path $resultsRoot 'artifacts\INSTALL_TESTED_MANAGER_UPDATE.cmd'
    if (-not (Test-Path -LiteralPath $fullGateResult -PathType Leaf)) { Fail ('Full Gate r2 receipt is missing: ' + $fullGateResult) }
    if (-not (Test-Path -LiteralPath $testedUpdate -PathType Leaf)) { Fail ('tested UPDATE is missing after Full Gate r2: ' + $testedUpdate) }
    if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) { Fail ('tested installer is missing after Full Gate r2: ' + $installer) }
    $full = Get-Content -LiteralPath $fullGateResult -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not [bool]$full.pass) { Fail 'FULL_GATE_RESULT.json does not record PASS.' }
    if ($full.PSObject.Properties['gate_revision'] -and [int]$full.gate_revision -ne $expectedGateRevision) { Fail ('Full Gate receipt gate revision mismatch: ' + [string]$full.gate_revision) }
    $testedUpdateSha = (Get-FileHash -LiteralPath $testedUpdate -Algorithm SHA256).Hash.ToLowerInvariant()

    Write-Host ''
    Write-Host 'REAL-CURRENT GATE-r2 QUALIFICATION COMPLETED WITH EXIT 0.' -ForegroundColor Green
    Write-Host ('TESTED_UPDATE_SHA256=' + $testedUpdateSha) -ForegroundColor Green
    Write-Host ('FULL_GATE_RESULT=' + $fullGateResult)
    Write-Host ('TESTED_UPDATE_PATH=' + $testedUpdate)
    Write-Host ('TESTED_INSTALLER_PATH=' + $installer)
    Write-Host ('FAILED_R1_EVIDENCE=' + $historyRoot)
    Write-Host 'Do not install Manager 4.17.12 yet. Preserve the complete Full Gate r2 output/results for review.'
}
finally {
    if (Test-Path -LiteralPath $downloadRoot) {
        Remove-Item -LiteralPath $downloadRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
