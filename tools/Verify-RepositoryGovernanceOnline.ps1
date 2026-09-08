[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [string]$Repository = $env:GITHUB_REPOSITORY
)

$ErrorActionPreference = 'Stop'
$RepositoryRoot = [System.IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')

function Fail([string]$Message) { throw $Message }
function Get-Json([string]$Uri,[hashtable]$Headers) {
    try { Invoke-RestMethod -Method Get -Uri $Uri -Headers $Headers -UseBasicParsing -ErrorAction Stop }
    catch { Fail ('GitHub governance query failed: ' + $Uri + '; ' + $_.Exception.Message) }
}
function Assert-Set([object[]]$Actual,[object[]]$Expected,[string]$Purpose) {
    $a = @($Actual | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ })
    $e = @($Expected | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ })
    if ($a.Count -ne $e.Count) { Fail ($Purpose + ' count mismatch: actual=' + $a.Count + ' expected=' + $e.Count) }
    foreach ($value in $e) { if ($a -cnotcontains $value) { Fail ($Purpose + ' missing value: ' + $value) } }
    foreach ($value in $a) { if ($e -cnotcontains $value) { Fail ($Purpose + ' unexpected value: ' + $value) } }
}
function Read-Policy([string]$Relative) {
    $path = Join-Path $RepositoryRoot $Relative.Replace('/','\')
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { Fail ('Missing policy file: ' + $Relative) }
    Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
}

if ([string]::IsNullOrWhiteSpace($Repository) -or $Repository -notmatch '^[^/]+/[^/]+$') { Fail 'Repository must be owner/name.' }
$policy = Read-Policy 'REPOSITORY_GOVERNANCE.json'
$baseline = Read-Policy 'LEGACY_RELEASE_BASELINE.json'
if ([string]$policy.schema -ne 'keelaryn.repository-governance.v1' -or [int]$policy.revision -ne 5) { Fail 'Online verifier requires Repository Governance r5.' }
if ([string]$policy.repository -ne $Repository -or [string]$baseline.repository -ne $Repository) { Fail 'Repository identity mismatch.' }

$headers = @{
    'Accept' = 'application/vnd.github+json'
    'User-Agent' = 'Keelaryn-Repository-Governance-Online'
    'X-GitHub-Api-Version' = '2026-03-10'
}
if (-not [string]::IsNullOrWhiteSpace([string]$env:GITHUB_TOKEN)) { $headers['Authorization'] = 'Bearer ' + [string]$env:GITHUB_TOKEN }
$api = 'https://api.github.com/repos/' + $Repository

$repo = Get-Json $api $headers
if ([string]$repo.default_branch -ne [string]$policy.default_branch) { Fail 'GitHub default branch mismatch.' }
foreach ($property in @('allow_squash_merge','allow_merge_commit','allow_rebase_merge','allow_auto_merge')) {
    if ($null -ne $repo.PSObject.Properties[$property]) {
        if ([bool]$repo.$property -ne [bool]$policy.merge_policy.$property) { Fail ('GitHub merge setting mismatch: ' + $property) }
    }
}

$branch = Get-Json ($api + '/branches/' + [System.Uri]::EscapeDataString([string]$policy.default_branch)) $headers
if (-not [bool]$branch.protected) { Fail 'Default branch is not protected.' }
$rulesetsRaw = Get-Json ($api + '/rulesets?per_page=100') $headers
$rulesets = @(); if ($null -ne $rulesetsRaw) { $rulesets = @($rulesetsRaw) }

$mainMatches = @($rulesets | Where-Object { [string]$_.name -eq [string]$policy.main_ruleset.name })
if ($mainMatches.Count -ne 1) { Fail ('Expected exactly one main ruleset named ' + [string]$policy.main_ruleset.name + '.') }
$main = Get-Json ($api + '/rulesets/' + [string]$mainMatches[0].id) $headers
if ([string]$main.target -ne 'branch') { Fail 'Main ruleset target must be branch.' }
if (([string]$main.enforcement).ToLowerInvariant() -notin @('active','enabled')) { Fail 'Main ruleset is not active.' }
$mainBypass = @()
if ($null -ne $main.PSObject.Properties['bypass_actors'] -and $null -ne $main.bypass_actors) { $mainBypass = @($main.bypass_actors) }
if ($mainBypass.Count -ne 0) { Fail 'Main ruleset bypass list must be empty.' }
$mainIncludes = @(); if ($null -ne $main.conditions.ref_name.include) { $mainIncludes = @($main.conditions.ref_name.include | ForEach-Object { [string]$_ }) }
if ($mainIncludes.Count -ne 1 -or ($mainIncludes[0] -ne '~DEFAULT_BRANCH' -and $mainIncludes[0] -ne 'refs/heads/main')) { Fail 'Main ruleset ref target mismatch.' }
$mainExcludes = @(); if ($null -ne $main.conditions.ref_name.exclude) { $mainExcludes = @($main.conditions.ref_name.exclude) }
if ($mainExcludes.Count -ne 0) { Fail 'Main ruleset must not exclude refs.' }
$types = @($main.rules | ForEach-Object { [string]$_.type })
foreach ($required in @('pull_request','required_status_checks','non_fast_forward','deletion')) { if ($types -notcontains $required) { Fail ('Main ruleset missing rule: ' + $required) } }
$statusRows = @($main.rules | Where-Object { [string]$_.type -eq 'required_status_checks' })
if ($statusRows.Count -ne 1) { Fail 'Main ruleset must contain exactly one required_status_checks rule.' }
if (-not [bool]$statusRows[0].parameters.strict_required_status_checks_policy) { Fail 'Required status checks must be strict.' }
Assert-Set @($statusRows[0].parameters.required_status_checks | ForEach-Object { [string]$_.context }) @($policy.main_ruleset.required_rules.required_status_checks.contexts) 'Live required checks'
$prRows = @($main.rules | Where-Object { [string]$_.type -eq 'pull_request' })
if ($prRows.Count -ne 1) { Fail 'Main ruleset must contain exactly one pull_request rule.' }
$pr = $prRows[0].parameters
if ([int]$pr.required_approving_review_count -ne [int]$policy.main_ruleset.required_rules.pull_request.required_approving_review_count) { Fail 'Approval-count mismatch.' }
if ([bool]$pr.required_review_thread_resolution -ne [bool]$policy.main_ruleset.required_rules.pull_request.required_review_thread_resolution) { Fail 'Review-thread resolution mismatch.' }
Assert-Set @($pr.allowed_merge_methods) @($policy.main_ruleset.required_rules.pull_request.allowed_merge_methods) 'Live allowed merge methods'
Write-Host ('Main ruleset: PASS. id=' + [string]$mainMatches[0].id) -ForegroundColor Green

$tagPolicy = $policy.provenance_tag_ruleset
$tagMatches = @($rulesets | Where-Object { [string]$_.name -eq [string]$tagPolicy.name })
if ($tagMatches.Count -eq 0) {
    if ([string]$env:GITHUB_EVENT_NAME -eq 'pull_request') {
        Write-Warning ('Provenance tag ruleset not active yet; bootstrap PR permits this only until pre-merge admin apply: ' + [string]$tagPolicy.name)
    } else {
        Fail ('Required provenance tag ruleset is not active: ' + [string]$tagPolicy.name)
    }
} elseif ($tagMatches.Count -ne 1) {
    Fail 'Expected exactly one provenance tag ruleset.'
} else {
    $tagRuleset = Get-Json ($api + '/rulesets/' + [string]$tagMatches[0].id) $headers
    if ([string]$tagRuleset.target -ne 'tag') { Fail 'Provenance ruleset target must be tag.' }
    if (([string]$tagRuleset.enforcement).ToLowerInvariant() -notin @('active','enabled')) { Fail 'Provenance ruleset is not active.' }
    $tagBypass = @()
    if ($null -ne $tagRuleset.PSObject.Properties['bypass_actors'] -and $null -ne $tagRuleset.bypass_actors) { $tagBypass = @($tagRuleset.bypass_actors) }
    if ($tagBypass.Count -ne 0) { Fail 'Provenance tag ruleset bypass list must be empty.' }
    Assert-Set @($tagRuleset.conditions.ref_name.include) @($tagPolicy.include_refs) 'Live provenance tag includes'
    $tagExclude = @(); if ($null -ne $tagRuleset.conditions.ref_name.exclude) { $tagExclude = @($tagRuleset.conditions.ref_name.exclude) }
    if ($tagExclude.Count -ne 0) { Fail 'Provenance tag ruleset must not exclude refs.' }
    $tagTypes = @($tagRuleset.rules | ForEach-Object { [string]$_.type })
    foreach ($required in @('deletion','non_fast_forward')) { if ($tagTypes -notcontains $required) { Fail ('Provenance ruleset missing rule: ' + $required) } }
    Write-Host ('Provenance tag ruleset: PASS. id=' + [string]$tagMatches[0].id) -ForegroundColor Green
}

$expectedLegacyTags = @($policy.release_policy.immutable_releases.legacy_mutable_tags | ForEach-Object { [string]$_ })
$baselineRows = @($baseline.releases)
Assert-Set @($baselineRows | ForEach-Object { [string]$_.tag }) $expectedLegacyTags 'Legacy baseline tag set'
foreach ($row in $baselineRows) {
    $tag = ([string]$row.tag).Trim()
    $release = Get-Json ($api + '/releases/tags/' + [System.Uri]::EscapeDataString($tag)) $headers
    if ([bool]$release.draft) { Fail ('Legacy release is draft: ' + $tag) }
    if ([int64]$release.id -ne [int64]$row.release_id) { Fail ('Legacy release id mismatch: ' + $tag) }
    if ($null -ne $release.PSObject.Properties['immutable'] -and [bool]$release.immutable -ne [bool]$row.immutable) { Fail ('Legacy immutable-state mismatch: ' + $tag) }
    $tagRef = Get-Json ($api + '/git/ref/tags/' + [System.Uri]::EscapeDataString($tag)) $headers
    if ([string]$tagRef.object.type -ne 'commit') { Fail ('Legacy release tag is not lightweight: ' + $tag) }
    if ([string]$tagRef.object.sha -cne [string]$row.target_commit) { Fail ('Legacy tag target mismatch: ' + $tag) }
    $actualAssets = @($release.assets)
    $expectedAssets = @($row.assets)
    if ($actualAssets.Count -ne $expectedAssets.Count) { Fail ('Legacy asset-count mismatch: ' + $tag) }
    foreach ($expected in $expectedAssets) {
        $matches = @($actualAssets | Where-Object { [string]$_.name -ceq [string]$expected.name })
        if ($matches.Count -ne 1) { Fail ('Legacy asset missing/duplicated: ' + $tag + '/' + [string]$expected.name) }
        $actual = $matches[0]
        if ([int64]$actual.size -ne [int64]$expected.size) { Fail ('Legacy asset size mismatch: ' + $tag + '/' + [string]$expected.name) }
        $digest = ([string]$actual.digest).Trim().ToLowerInvariant()
        if ($digest -notmatch '^sha256:[0-9a-f]{64}$') { Fail ('Legacy asset lacks SHA-256 digest: ' + $tag + '/' + [string]$expected.name) }
        if ($digest.Substring(7) -cne ([string]$expected.sha256).ToLowerInvariant()) { Fail ('Legacy asset SHA-256 mismatch: ' + $tag + '/' + [string]$expected.name) }
    }
    Write-Host ('Legacy release baseline: PASS. ' + $tag + '; assets=' + $actualAssets.Count + '; target=' + [string]$row.target_commit) -ForegroundColor Green
}

Write-Host ('Repository governance online enforcement: PASS. rulesets=' + $rulesets.Count + '; legacy=' + $baselineRows.Count) -ForegroundColor Green
Write-Warning 'Administration-only Actions settings and destructive ref mutations remain explicit admin-boundary operations.'
