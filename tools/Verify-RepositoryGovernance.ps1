[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [string]$Repository = $env:GITHUB_REPOSITORY
)

$ErrorActionPreference = 'Stop'
$RepositoryRoot = [System.IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')

function Fail([string]$Message) { throw $Message }
function Read-Utf8([string]$Path) { [System.IO.File]::ReadAllText($Path,[System.Text.Encoding]::UTF8) }
function Require-File([string]$Relative) {
    $path = Join-Path $RepositoryRoot $Relative.Replace('/','\')
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { Fail ('Missing repository governance file: ' + $Relative) }
    $path
}
function Require-Token([string]$Text,[string]$Token,[string]$Purpose) {
    if ($Text.IndexOf($Token,[System.StringComparison]::Ordinal) -lt 0) { Fail ($Purpose + ' missing token: ' + $Token) }
}
function Assert-StringSet([object[]]$Actual,[object[]]$Expected,[string]$Purpose) {
    $a = @($Actual | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ })
    $e = @($Expected | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ })
    if (@($a | Select-Object -Unique).Count -ne $a.Count) { Fail ($Purpose + ' contains duplicates.') }
    if (@($e | Select-Object -Unique).Count -ne $e.Count) { Fail ($Purpose + ' expected set contains duplicates.') }
    if ($a.Count -ne $e.Count) { Fail ($Purpose + ' count mismatch: actual=' + $a.Count + ' expected=' + $e.Count) }
    foreach ($value in $e) { if ($a -cnotcontains $value) { Fail ($Purpose + ' missing value: ' + $value) } }
    foreach ($value in $a) { if ($e -cnotcontains $value) { Fail ($Purpose + ' unexpected value: ' + $value) } }
}
function Get-WorkflowTriggerPaths([string]$Text,[string]$Trigger) {
    $lines = @($Text -split "`r?`n")
    $triggerHeader = '  ' + $Trigger + ':'
    $inTrigger = $false
    $inPaths = $false
    $result = New-Object System.Collections.ArrayList
    foreach ($line in $lines) {
        if (-not $inTrigger) {
            if ($line -ceq $triggerHeader) { $inTrigger = $true }
            continue
        }
        if ($line -match '^  [A-Za-z_][A-Za-z0-9_-]*:' -or $line -ceq 'permissions:') { break }
        if (-not $inPaths) {
            if ($line -ceq '    paths:') { $inPaths = $true }
            continue
        }
        if ($line -match "^      - '(?<path>[^']+)'\s*$") {
            [void]$result.Add([string]$Matches['path'])
            continue
        }
        if ($line -match '^    \S') { break }
    }
    if (-not $inTrigger) { Fail ('Workflow is missing trigger block: ' + $Trigger) }
    if (-not $inPaths) { Fail ('Workflow trigger is missing paths list: ' + $Trigger) }
    if ($result.Count -eq 0) { Fail ('Workflow trigger path list is empty: ' + $Trigger) }
    @($result)
}

$contractPath = Require-File 'REPOSITORY_GOVERNANCE.json'
$contract = Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$contract.schema -ne 'keelaryn.repository-governance.v1') { Fail ('Unsupported governance schema: ' + [string]$contract.schema) }
if ([int]$contract.revision -ne 5) { Fail ('Unexpected governance revision: ' + [string]$contract.revision) }
if ([string]$contract.repository -ne 'efremov-aleksei-96/keelaryn') { Fail 'Unexpected governed repository.' }
if (-not [string]::IsNullOrWhiteSpace($Repository) -and [string]$contract.repository -ne $Repository) { Fail 'Requested repository does not match governance contract.' }
if ([string]$contract.default_branch -ne 'main') { Fail 'Governance default branch must be main.' }

if (-not [bool]$contract.merge_policy.allow_squash_merge) { Fail 'Governance must allow squash merge.' }
if ([bool]$contract.merge_policy.allow_merge_commit) { Fail 'Governance must forbid merge commits.' }
if ([bool]$contract.merge_policy.allow_rebase_merge) { Fail 'Governance must forbid rebase merge.' }
if ([bool]$contract.merge_policy.allow_auto_merge) { Fail 'Governance must keep auto-merge disabled.' }

$hygiene = $contract.branch_hygiene
if ($null -eq $hygiene) { Fail 'Governance is missing branch_hygiene.' }
if (-not [bool]$hygiene.delete_branch_on_merge) { Fail 'Branch hygiene must require delete_branch_on_merge.' }
if (-not [bool]$hygiene.cleanup_at_cycle_close) { Fail 'Branch hygiene must require cleanup at cycle close.' }
if (-not [bool]$hygiene.preserve_unique_qualification_refs) { Fail 'Branch hygiene must preserve unique qualification refs.' }
if (-not [bool]$hygiene.freeze_preserved_branch_before_delete) { Fail 'Preserved branches must be frozen before deletion.' }
if ([string]$hygiene.provenance_tag_prefix -ne 'provenance/') { Fail 'Provenance tag prefix must be provenance/.' }
$preservedPrefixes = @($hygiene.preserved_prefixes)
Assert-StringSet $preservedPrefixes @('candidate-manager-','framework-','gate-framework-','manager-','release-manager-') 'Preserved branch prefixes'
if ([string]::IsNullOrWhiteSpace([string]$hygiene.policy)) { Fail 'Branch hygiene policy text is missing.' }

$tagPolicy = $contract.provenance_tag_ruleset
if ($null -eq $tagPolicy) { Fail 'Governance is missing provenance_tag_ruleset.' }
if ([string]$tagPolicy.name -ne 'Keelaryn immutable provenance tags') { Fail 'Unexpected provenance tag ruleset name.' }
if ([string]$tagPolicy.target -ne 'tag') { Fail 'Provenance ruleset target must be tag.' }
if ([string]$tagPolicy.enforcement -ne 'active') { Fail 'Provenance ruleset must require active enforcement.' }
Assert-StringSet @($tagPolicy.include_refs) @('refs/tags/v*','refs/tags/provenance/**') 'Provenance tag includes'
if (@($tagPolicy.bypass_actors).Count -ne 0) { Fail 'Provenance tag ruleset bypass list must be empty.' }
if (-not [bool]$tagPolicy.required_rules.non_fast_forward -or -not [bool]$tagPolicy.required_rules.deletion) { Fail 'Provenance tag ruleset must block update and deletion.' }

$ci = $contract.ci_concurrency
if ($null -eq $ci) { Fail 'Governance is missing ci_concurrency.' }
if (-not [bool]$ci.cancel_obsolete_pull_request_runs) { Fail 'CI must cancel obsolete PR runs.' }
if ([bool]$ci.cancel_main_push_runs) { Fail 'CI must preserve main push evidence runs.' }
if ([string]::IsNullOrWhiteSpace([string]$ci.policy)) { Fail 'CI concurrency policy text is missing.' }

$immutable = $contract.release_policy.immutable_releases
if ($null -eq $immutable) { Fail 'Governance is missing immutable release policy.' }
foreach ($property in @('repository_setting_required','future_releases_must_be_immutable','release_attestation_required','verify_each_asset_attestation')) {
    if ($null -eq $immutable.PSObject.Properties[$property] -or -not [bool]$immutable.$property) { Fail ('Immutable release policy must require ' + $property + '.') }
}
if ([string]$immutable.legacy_release_baseline -ne 'LEGACY_RELEASE_BASELINE.json') { Fail 'Legacy release baseline path mismatch.' }
$legacyTags = @($immutable.legacy_mutable_tags | ForEach-Object { ([string]$_).Trim() })
foreach ($tag in $legacyTags) { if ($tag -notmatch '^v\d+\.\d+\.\d+$') { Fail ('Invalid legacy tag: ' + $tag) } }
if ([string]::IsNullOrWhiteSpace([string]$immutable.legacy_policy)) { Fail 'Legacy mutable release policy text is missing.' }

$baselinePath = Require-File 'LEGACY_RELEASE_BASELINE.json'
$baseline = Get-Content -LiteralPath $baselinePath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$baseline.schema -ne 'keelaryn.legacy-release-baseline.v1') { Fail 'Unsupported legacy baseline schema.' }
if ([string]$baseline.repository -ne [string]$contract.repository) { Fail 'Legacy baseline repository mismatch.' }
if ([string]::IsNullOrWhiteSpace([string]$baseline.policy)) { Fail 'Legacy baseline policy text is missing.' }
$baselineReleases = @($baseline.releases)
if ($baselineReleases.Count -eq 0) { Fail 'Legacy baseline is empty.' }
$baselineTags = @($baselineReleases | ForEach-Object { ([string]$_.tag).Trim() })
Assert-StringSet $legacyTags $baselineTags 'Legacy mutable/baseline tag set'
foreach ($row in $baselineReleases) {
    $tag = ([string]$row.tag).Trim()
    if ([string]$row.target_commit -notmatch '^[0-9a-f]{40}$') { Fail ('Invalid legacy target commit: ' + $tag) }
    if ([int64]$row.release_id -le 0) { Fail ('Invalid legacy release id: ' + $tag) }
    if ([bool]$row.immutable) { Fail ('Legacy baseline may contain only mutable releases: ' + $tag) }
    $assets = @($row.assets)
    if ($assets.Count -eq 0) { Fail ('Legacy release has no assets: ' + $tag) }
    $assetNames = @($assets | ForEach-Object { ([string]$_.name).Trim() })
    Assert-StringSet $assetNames @($assetNames | Select-Object -Unique) ('Legacy asset names ' + $tag)
    foreach ($asset in $assets) {
        if ([string]::IsNullOrWhiteSpace([string]$asset.name)) { Fail ('Legacy asset has empty name: ' + $tag) }
        if ([int64]$asset.size -lt 0) { Fail ('Invalid legacy asset size: ' + $tag + '/' + [string]$asset.name) }
        if ([string]$asset.sha256 -notmatch '^[0-9a-f]{64}$') { Fail ('Invalid legacy asset SHA-256: ' + $tag + '/' + [string]$asset.name) }
    }
}

$criticalPaths = @($contract.release_policy.critical_paths)
Assert-StringSet $criticalPaths @('.github/workflows/public-release.yml','manager/**','PUBLIC_PROVENANCE.json','REPOSITORY_GOVERNANCE.json','LEGACY_RELEASE_BASELINE.json','README.md','GETTING_STARTED.md','docs/USING_WITH_CHATGPT.md','docs/TROUBLESHOOTING.md') 'Release-critical paths'
$pushPaths = @($contract.release_policy.public_release_push_paths)
Assert-StringSet $pushPaths @('.github/workflows/public-release.yml','manager/**','PUBLIC_PROVENANCE.json','REPOSITORY_GOVERNANCE.json','LEGACY_RELEASE_BASELINE.json') 'Public-release push paths'
if (-not [bool]$contract.release_policy.future_provenance.qualified_product_source_commit_required) { Fail 'Future provenance must require qualified product-source commit.' }
if ([string]::IsNullOrWhiteSpace([string]$contract.release_policy.future_provenance.policy)) { Fail 'Future provenance policy text is missing.' }
if ([string]$contract.release_policy.conditional_pr_gate.required_context -ne 'release-policy') { Fail 'Conditional release context mismatch.' }
if ([string]$contract.release_policy.conditional_pr_gate.dependency_context -ne 'distribution-gate') { Fail 'Conditional release dependency mismatch.' }

foreach ($relative in @(
    '.github/CODEOWNERS',
    '.github/dependabot.yml',
    '.github/pull_request_template.md',
    '.github/workflows/repository-governance.yml',
    '.github/workflows/release-policy.yml',
    '.github/workflows/windows-powershell.yml',
    '.github/workflows/public-release.yml',
    'CONTRIBUTING.md',
    'SECURITY.md',
    'docs/REPOSITORY_GOVERNANCE.md',
    'tools/Invoke-RepositoryGovernanceAdmin.ps1',
    'tools/Verify-GitHubActionsPolicy.ps1',
    'tools/Verify-RepositoryGovernance.ps1',
    'tools/Verify-RepositoryGovernanceOnline.ps1'
)) { [void](Require-File $relative) }

$workflowFiles = @('.github/workflows/windows-powershell.yml','.github/workflows/public-release.yml','.github/workflows/repository-governance.yml','.github/workflows/release-policy.yml')
foreach ($relative in $workflowFiles) {
    $src = Read-Utf8 (Require-File $relative)
    if ($src -match '(?im)^\s*pull_request_target\s*:') { Fail ('pull_request_target is forbidden in ' + $relative) }
    if ($src -notmatch '(?ms)^permissions:\s*\r?\n\s+contents:\s+read\s*(?:\r?\n|$)') { Fail ('Workflow must default to contents: read: ' + $relative) }
}

$prCancelToken = 'cancel-in-progress: $' + "{{ github.event_name == 'pull_request' }}"
$sourceWorkflow = Read-Utf8 (Require-File '.github/workflows/windows-powershell.yml')
$governanceWorkflow = Read-Utf8 (Require-File '.github/workflows/repository-governance.yml')
$releaseSource = Read-Utf8 (Require-File '.github/workflows/public-release.yml')
Require-Token $sourceWorkflow $prCancelToken 'Windows source concurrency'
Require-Token $governanceWorkflow $prCancelToken 'Repository governance concurrency'
Require-Token $releaseSource $prCancelToken 'Public release concurrency'
if ($sourceWorkflow -match '(?m)^\s*cancel-in-progress:\s*true\s*$') { Fail 'Windows source workflow unconditionally cancels evidence.' }
if ($governanceWorkflow -match '(?m)^\s*cancel-in-progress:\s*true\s*$') { Fail 'Repository governance workflow unconditionally cancels evidence.' }

foreach ($token in @(
    'production_validation.full_gate_pass',
    'production_validation.production_doctor_pass',
    'production_validation.production_ux_smoke_pass',
    'production_validation.tested_update_sha256',
    'REPOSITORY_GOVERNANCE.json',
    'LEGACY_RELEASE_BASELINE.json',
    'LEGACY_MUTABLE',
    '--draft',
    'isImmutable',
    'gh release verify',
    'gh release verify-asset',
    '--cleanup-tag',
    'contents: write',
    '.WaitForExit(15000)',
    '.WaitForExit(5000)',
    'First-run menu smoke timed out after 15 seconds'
)) { Require-Token $releaseSource $token 'Public release workflow' }
if ($releaseSource -match '\.WaitForExit\(\)') { Fail 'Public release workflow contains parameterless WaitForExit().' }

$publicPrPaths = Get-WorkflowTriggerPaths $releaseSource 'pull_request'
$publicPushPaths = Get-WorkflowTriggerPaths $releaseSource 'push'
Assert-StringSet $publicPrPaths $criticalPaths 'Public-release pull-request path filter'
Assert-StringSet $publicPushPaths $pushPaths 'Public-release push path filter'

$releasePolicySource = Read-Utf8 (Require-File '.github/workflows/release-policy.yml')
foreach ($token in @('release-policy:','distribution-gate','HEAD_SHA','Release-critical PR detected','Release policy PASS','check-runs?per_page=100','release_policy.critical_paths')) { Require-Token $releasePolicySource $token 'Conditional release-policy workflow' }

$governanceWorkflow = Read-Utf8 (Require-File '.github/workflows/repository-governance.yml')
Require-Token $governanceWorkflow 'Verify-RepositoryGovernance.ps1' 'Repository governance source step'
Require-Token $governanceWorkflow 'Verify-RepositoryGovernanceOnline.ps1' 'Repository governance online step'

$governanceDoc = Read-Utf8 (Require-File 'docs/REPOSITORY_GOVERNANCE.md')
foreach ($token in @('immutable releases','release attestation','legacy mutable','release-policy','branch hygiene','LEGACY_RELEASE_BASELINE.json','provenance tag','Verify-RepositoryGovernanceOnline.ps1')) { Require-Token $governanceDoc $token 'Repository governance documentation' }

$requiredContexts = @($contract.main_ruleset.required_rules.required_status_checks.contexts)
Assert-StringSet $requiredContexts @('source-gate','repository-governance','release-policy') 'Required status checks'

Write-Host ('Repository governance source contract: PASS. revision=5; legacy=' + $legacyTags.Count + '; critical_paths=' + $criticalPaths.Count + '; online_verifier=separate') -ForegroundColor Green
exit 0
