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
    $header = '  ' + $Trigger + ':'
    $inTrigger = $false
    $inPaths = $false
    $result = New-Object System.Collections.ArrayList
    foreach ($line in $lines) {
        if (-not $inTrigger) {
            if ($line -ceq $header) { $inTrigger = $true }
            continue
        }
        if ($line -match '^  [A-Za-z_][A-Za-z0-9_-]*:' -or $line -ceq 'permissions:') { break }
        if (-not $inPaths) {
            if ($line -ceq '    paths:') { $inPaths = $true }
            continue
        }
        if ($line -match "^      - '(?<path>[^']+)'\s*$") { [void]$result.Add([string]$Matches['path']); continue }
        if ($line -match '^    \S') { break }
    }
    if (-not $inTrigger -or -not $inPaths -or $result.Count -eq 0) { Fail ('Workflow path contract missing for trigger: ' + $Trigger) }
    @($result)
}

$contract = Get-Content -LiteralPath (Require-File 'REPOSITORY_GOVERNANCE.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$contract.schema -ne 'keelaryn.repository-governance.v1') { Fail 'Unsupported governance schema.' }
if ([int]$contract.revision -ne 5) { Fail ('Unexpected governance revision: ' + [string]$contract.revision) }
if ([string]$contract.repository -ne 'efremov-aleksei-96/keelaryn') { Fail 'Unexpected governed repository.' }
if (-not [string]::IsNullOrWhiteSpace($Repository) -and [string]$contract.repository -ne $Repository) { Fail 'Requested repository does not match governance contract.' }
if ([string]$contract.default_branch -ne 'main') { Fail 'Governance default branch must be main.' }
if (-not [bool]$contract.merge_policy.allow_squash_merge -or [bool]$contract.merge_policy.allow_merge_commit -or [bool]$contract.merge_policy.allow_rebase_merge -or [bool]$contract.merge_policy.allow_auto_merge) { Fail 'Merge policy mismatch.' }

$hygiene = $contract.branch_hygiene
if ($null -eq $hygiene -or -not [bool]$hygiene.delete_branch_on_merge -or -not [bool]$hygiene.cleanup_at_cycle_close -or -not [bool]$hygiene.preserve_unique_qualification_refs -or -not [bool]$hygiene.freeze_preserved_branch_before_delete) { Fail 'Branch hygiene contract is incomplete.' }
if ([string]$hygiene.provenance_tag_prefix -ne 'provenance/') { Fail 'Provenance tag prefix mismatch.' }
Assert-StringSet @($hygiene.preserved_prefixes) @('candidate-manager-','framework-','gate-framework-','manager-','release-manager-') 'Preserved branch prefixes'
if ([string]::IsNullOrWhiteSpace([string]$hygiene.policy)) { Fail 'Branch hygiene policy text is missing.' }

$tagPolicy = $contract.provenance_tag_ruleset
if ([string]$tagPolicy.name -ne 'Keelaryn immutable provenance tags' -or [string]$tagPolicy.target -ne 'tag' -or [string]$tagPolicy.enforcement -ne 'active') { Fail 'Provenance tag ruleset contract mismatch.' }
Assert-StringSet @($tagPolicy.include_refs) @('refs/tags/v*','refs/tags/provenance/**') 'Provenance tag includes'
if (@($tagPolicy.bypass_actors).Count -ne 0 -or -not [bool]$tagPolicy.required_rules.non_fast_forward -or -not [bool]$tagPolicy.required_rules.deletion) { Fail 'Provenance tag ruleset must have no bypass and block update/deletion.' }

$ci = $contract.ci_concurrency
if (-not [bool]$ci.cancel_obsolete_pull_request_runs -or [bool]$ci.cancel_main_push_runs) { Fail 'CI concurrency policy mismatch.' }
Assert-StringSet @($ci.pr_cancel_workflows) @('.github/workflows/repository-governance.yml','.github/workflows/public-release.yml','.github/workflows/release-policy.yml') 'PR-cancel workflow scope'
Assert-StringSet @($ci.deferred_workflows) @('.github/workflows/windows-powershell.yml') 'Deferred workflow scope'
if ([string]::IsNullOrWhiteSpace([string]$ci.source_validation_policy) -or [string]::IsNullOrWhiteSpace([string]$ci.policy)) { Fail 'CI concurrency policy text is missing.' }

$immutable = $contract.release_policy.immutable_releases
foreach ($property in @('repository_setting_required','future_releases_must_be_immutable','release_attestation_required','verify_each_asset_attestation')) {
    if ($null -eq $immutable.PSObject.Properties[$property] -or -not [bool]$immutable.$property) { Fail ('Immutable release policy must require ' + $property + '.') }
}
if ([string]$immutable.legacy_release_baseline -ne 'LEGACY_RELEASE_BASELINE.json') { Fail 'Legacy release baseline path mismatch.' }
$legacyTags = @($immutable.legacy_mutable_tags | ForEach-Object { ([string]$_).Trim() })
Assert-StringSet $legacyTags @('v4.11.0','v4.12.0','v4.13.1') 'Legacy mutable releases'

$baseline = Get-Content -LiteralPath (Require-File 'LEGACY_RELEASE_BASELINE.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$baseline.schema -ne 'keelaryn.legacy-release-baseline.v1' -or [string]$baseline.repository -ne [string]$contract.repository) { Fail 'Legacy baseline identity mismatch.' }
$rows = @($baseline.releases)
Assert-StringSet @($rows | ForEach-Object { [string]$_.tag }) $legacyTags 'Legacy baseline tag set'
foreach ($row in $rows) {
    if ([string]$row.target_commit -notmatch '^[0-9a-f]{40}$' -or [int64]$row.release_id -le 0 -or [bool]$row.immutable) { Fail ('Invalid legacy release row: ' + [string]$row.tag) }
    $assets = @($row.assets)
    if ($assets.Count -eq 0) { Fail ('Legacy release has no assets: ' + [string]$row.tag) }
    $names = @($assets | ForEach-Object { [string]$_.name })
    if (@($names | Select-Object -Unique).Count -ne $names.Count) { Fail ('Legacy release has duplicate asset names: ' + [string]$row.tag) }
    foreach ($asset in $assets) {
        if ([int64]$asset.size -lt 0 -or [string]$asset.sha256 -notmatch '^[0-9a-f]{64}$') { Fail ('Invalid legacy asset identity: ' + [string]$row.tag + '/' + [string]$asset.name) }
    }
}

$criticalPaths = @($contract.release_policy.critical_paths)
Assert-StringSet $criticalPaths @('.github/workflows/public-release.yml','manager/**','PUBLIC_PROVENANCE.json','REPOSITORY_GOVERNANCE.json','LEGACY_RELEASE_BASELINE.json','README.md','GETTING_STARTED.md','docs/USING_WITH_CHATGPT.md','docs/TROUBLESHOOTING.md') 'Release-critical paths'
$pushPaths = @($contract.release_policy.public_release_push_paths)
Assert-StringSet $pushPaths @('.github/workflows/public-release.yml','manager/**','PUBLIC_PROVENANCE.json','REPOSITORY_GOVERNANCE.json','LEGACY_RELEASE_BASELINE.json') 'Public-release push paths'
if (-not [bool]$contract.release_policy.future_provenance.qualified_product_source_commit_required) { Fail 'Future provenance must require qualified product-source commit.' }
if ([string]$contract.release_policy.conditional_pr_gate.required_context -ne 'release-policy' -or [string]$contract.release_policy.conditional_pr_gate.dependency_context -ne 'distribution-gate') { Fail 'Conditional release gate contract mismatch.' }

$requiredFiles = @('.github/CODEOWNERS','.github/dependabot.yml','.github/pull_request_template.md','.github/workflows/repository-governance.yml','.github/workflows/release-policy.yml','.github/workflows/windows-powershell.yml','.github/workflows/public-release.yml','CONTRIBUTING.md','SECURITY.md','docs/REPOSITORY_GOVERNANCE.md','tools/Invoke-RepositoryGovernanceAdmin.ps1','tools/Verify-GitHubActionsPolicy.ps1','tools/Verify-RepositoryGovernance.ps1','tools/Verify-RepositoryGovernanceOnline.ps1')
foreach ($relative in $requiredFiles) { [void](Require-File $relative) }

$governancePowerShellFiles = @('tools/Invoke-RepositoryGovernanceAdmin.ps1','tools/Verify-GitHubActionsPolicy.ps1','tools/Verify-RepositoryGovernance.ps1','tools/Verify-RepositoryGovernanceOnline.ps1')
foreach ($relative in $governancePowerShellFiles) {
    $tokens = $null
    $parseErrors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile((Require-File $relative),[ref]$tokens,[ref]$parseErrors)
    if (@($parseErrors).Count -gt 0) {
        $messages = @($parseErrors | ForEach-Object { $_.Message }) -join '; '
        Fail ('Windows PowerShell parser failed for ' + $relative + ': ' + $messages)
    }
}

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
$releasePolicySource = Read-Utf8 (Require-File '.github/workflows/release-policy.yml')
Require-Token $governanceWorkflow $prCancelToken 'Repository governance concurrency'
Require-Token $releaseSource $prCancelToken 'Public release concurrency'
Require-Token $releasePolicySource 'cancel-in-progress: true' 'Release-policy concurrency'
Require-Token $sourceWorkflow 'cancel-in-progress: true' 'Deferred source-validation legacy state'
if ($sourceWorkflow.IndexOf('QualificationExecutionIdentity',[System.StringComparison]::Ordinal) -ge 0) { Fail 'Deferred source workflow unexpectedly contains unqualified semantic-scope redesign.' }
if ($governanceWorkflow -match '(?m)^\s*cancel-in-progress:\s*true\s*$' -or $releaseSource -match '(?m)^\s*cancel-in-progress:\s*true\s*$') { Fail 'A main-capable r5 workflow unconditionally cancels evidence.' }

foreach ($token in @('production_validation.full_gate_pass','production_validation.production_doctor_pass','production_validation.production_ux_smoke_pass','production_validation.tested_update_sha256','REPOSITORY_GOVERNANCE.json','LEGACY_RELEASE_BASELINE.json','LEGACY_MUTABLE','--draft','isImmutable','gh release verify','gh release verify-asset','--cleanup-tag','contents: write','.WaitForExit(15000)','.WaitForExit(5000)','First-run menu smoke timed out after 15 seconds')) { Require-Token $releaseSource $token 'Public release workflow' }
if ($releaseSource -match '\.WaitForExit\(\)') { Fail 'Public release workflow contains parameterless WaitForExit().' }
Assert-StringSet (Get-WorkflowTriggerPaths $releaseSource 'pull_request') $criticalPaths 'Public-release pull-request path filter'
Assert-StringSet (Get-WorkflowTriggerPaths $releaseSource 'push') $pushPaths 'Public-release push path filter'
foreach ($token in @('release-policy:','distribution-gate','HEAD_SHA','Release-critical PR detected','Release policy PASS','check-runs?per_page=100','release_policy.critical_paths')) { Require-Token $releasePolicySource $token 'Conditional release-policy workflow' }
Require-Token $governanceWorkflow 'Verify-RepositoryGovernance.ps1' 'Repository governance source step'
Require-Token $governanceWorkflow 'Verify-RepositoryGovernanceOnline.ps1' 'Repository governance online step'

$doc = Read-Utf8 (Require-File 'docs/REPOSITORY_GOVERNANCE.md')
foreach ($token in @('immutable releases','release attestation','legacy mutable','release-policy','branch hygiene','LEGACY_RELEASE_BASELINE.json','provenance tag','Verify-RepositoryGovernanceOnline.ps1','source validation')) { Require-Token $doc $token 'Repository governance documentation' }
Assert-StringSet @($contract.main_ruleset.required_rules.required_status_checks.contexts) @('source-gate','repository-governance','release-policy') 'Required status checks'

Write-Host ('Repository governance source contract: PASS. revision=5; legacy=' + $legacyTags.Count + '; critical_paths=' + $criticalPaths.Count + '; pr_cancel_workflows=' + @($ci.pr_cancel_workflows).Count + '; deferred=' + @($ci.deferred_workflows).Count + '; ps_parser=' + $governancePowerShellFiles.Count) -ForegroundColor Green
exit 0
