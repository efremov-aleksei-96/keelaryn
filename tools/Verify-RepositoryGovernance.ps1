[CmdletBinding()]
param(
    [string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'),
    [string]$Repository=$env:GITHUB_REPOSITORY,
    [switch]$Online
)

$ErrorActionPreference='Stop'
$RepositoryRoot=[System.IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')

function Fail([string]$Message){throw $Message}
function Read-Utf8([string]$Path){return [System.IO.File]::ReadAllText($Path,[System.Text.Encoding]::UTF8)}
function Require-File([string]$Relative){
    $path=Join-Path $RepositoryRoot $Relative.Replace('/','\')
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){Fail('Missing repository governance file: '+$Relative)}
    return $path
}
function Require-Token([string]$Text,[string]$Token,[string]$Purpose){
    if($Text.IndexOf($Token,[System.StringComparison]::Ordinal)-lt0){Fail($Purpose+' missing token: '+$Token)}
}
function Invoke-GitHubGet([string]$Uri,[hashtable]$Headers){
    try{return Invoke-RestMethod -Method Get -Uri $Uri -Headers $Headers -UseBasicParsing -ErrorAction Stop}
    catch{Fail('GitHub governance query failed: '+$Uri+'; '+$_.Exception.Message)}
}

$contractPath=Require-File 'REPOSITORY_GOVERNANCE.json'
$contract=(Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8)|ConvertFrom-Json
if([string]$contract.schema-ne'keelaryn.repository-governance.v1'){Fail('Unsupported governance schema: '+[string]$contract.schema)}
if([int]$contract.revision-ne4){Fail('Unexpected governance revision: '+[string]$contract.revision)}
if([string]$contract.default_branch-ne'main'){Fail('Governance default branch must be main.')}
if(-not[bool]$contract.merge_policy.allow_squash_merge){Fail('Governance must allow squash merge.')}
if([bool]$contract.merge_policy.allow_merge_commit){Fail('Governance must forbid merge commits.')}
if([bool]$contract.merge_policy.allow_rebase_merge){Fail('Governance must forbid rebase merge.')}
if([bool]$contract.merge_policy.allow_auto_merge){Fail('Governance must keep auto-merge disabled.')}

$hygiene=$contract.branch_hygiene
if($null-eq$hygiene){Fail('Governance is missing branch_hygiene.')}
if(-not[bool]$hygiene.delete_branch_on_merge){Fail('Branch hygiene must require delete_branch_on_merge.')}
if(-not[bool]$hygiene.cleanup_at_cycle_close){Fail('Branch hygiene must require cleanup at cycle close.')}
if(-not[bool]$hygiene.preserve_unique_qualification_refs){Fail('Branch hygiene must preserve unique qualification refs.')}
$preservedPrefixes=@($hygiene.preserved_prefixes|ForEach-Object{([string]$_).Trim()}|Where-Object{$_})
$expectedPrefixes=@('candidate-manager-','framework-','gate-framework-','manager-','release-manager-')
if($preservedPrefixes.Count-ne$expectedPrefixes.Count){Fail('Branch hygiene preserved-prefix count mismatch.')}
foreach($prefix in $expectedPrefixes){if($preservedPrefixes-notcontains$prefix){Fail('Branch hygiene missing preserved prefix: '+$prefix)}}
if([string]::IsNullOrWhiteSpace([string]$hygiene.policy)){Fail('Branch hygiene must include a policy statement.')}

$immutable=$contract.release_policy.immutable_releases
if($null-eq$immutable){Fail('Governance is missing immutable release policy.')}
foreach($property in @('repository_setting_required','future_releases_must_be_immutable','release_attestation_required','verify_each_asset_attestation')){
    if($null-eq$immutable.PSObject.Properties[$property]-or-not[bool]$immutable.$property){Fail('Immutable release policy must require '+$property+'.')}
}
$legacyTags=@();if($null-ne$immutable.legacy_mutable_tags){$legacyTags=@($immutable.legacy_mutable_tags|ForEach-Object{([string]$_).Trim()})}
foreach($tag in $legacyTags){if($tag-notmatch'^v\d+\.\d+\.\d+$'){Fail('Invalid legacy mutable release tag: '+$tag)}}
if(@($legacyTags|Select-Object -Unique).Count-ne$legacyTags.Count){Fail('Legacy mutable release tags contain duplicates.')}
if([string]::IsNullOrWhiteSpace([string]$immutable.legacy_policy)){Fail('Immutable release policy must explain the legacy exception contract.')}

$conditional=$contract.release_policy.conditional_pr_gate
if($null-eq$conditional){Fail('Governance is missing conditional PR release gate policy.')}
if([string]$conditional.required_context-ne'release-policy'){Fail('Conditional PR release gate context must be release-policy.')}
if([string]$conditional.dependency_context-ne'distribution-gate'){Fail('Conditional PR release gate dependency must be distribution-gate.')}

foreach($relative in @(
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
    'tools/Verify-GitHubActionsPolicy.ps1',
    'tools/Verify-RepositoryGovernance.ps1'
)){[void](Require-File $relative)}

$codeowners=Read-Utf8 (Require-File '.github/CODEOWNERS')
Require-Token $codeowners '* @efremov-aleksei-96' 'CODEOWNERS contract'

$security=Read-Utf8 (Require-File 'SECURITY.md')
Require-Token $security 'latest production-qualified Manager' 'Security policy'
$contrib=Read-Utf8 (Require-File 'CONTRIBUTING.md')
Require-Token $contrib 'REPOSITORY_GOVERNANCE.json' 'Contributing governance reference'

$workflowPaths=@(
    '.github/workflows/windows-powershell.yml',
    '.github/workflows/public-release.yml',
    '.github/workflows/repository-governance.yml',
    '.github/workflows/release-policy.yml'
)
foreach($relative in $workflowPaths){
    $src=Read-Utf8 (Require-File $relative)
    if($src-match'(?im)^\s*pull_request_target\s*:'){Fail('pull_request_target is forbidden in '+$relative)}
    if($src-notmatch'(?ms)^permissions:\s*\r?\n\s+contents:\s+read\s*(?:\r?\n|$)'){Fail('Workflow must default to contents: read: '+$relative)}
}

$releaseSource=Read-Utf8 (Require-File '.github/workflows/public-release.yml')
foreach($token in @(
    'production_validation.full_gate_pass',
    'production_validation.production_doctor_pass',
    'production_validation.production_ux_smoke_pass',
    'production_validation.tested_update_sha256',
    'REPOSITORY_GOVERNANCE.json',
    'legacy_mutable',
    'LEGACY_MUTABLE',
    '--draft',
    'isImmutable',
    'gh release verify',
    'gh release verify-asset',
    '--cleanup-tag',
    'contents: write'
)){Require-Token $releaseSource $token 'Public release workflow'}
if($releaseSource-notmatch'(?s)New release was published without native immutability; deleting unsafe mutable release and tag.*gh release delete'){Fail('Public release workflow does not fail closed on a newly published mutable release.')}
if($releaseSource-notmatch'(?s)Legacy mutable release exception: exact published assets are byte-identical.*leaving historical release unchanged'){Fail('Public release workflow does not preserve legacy mutable releases as read-only historical exceptions.')}

$releasePolicySource=Read-Utf8 (Require-File '.github/workflows/release-policy.yml')
foreach($token in @(
    'release-policy:',
    'distribution-gate',
    'HEAD_SHA',
    'Release-critical PR detected',
    'Release policy PASS',
    'check-runs?per_page=100'
)){Require-Token $releasePolicySource $token 'Conditional release-policy workflow'}

$governanceWorkflow=Read-Utf8 (Require-File '.github/workflows/repository-governance.yml')
Require-Token $governanceWorkflow 'repository-governance:' 'Governance workflow job identity'
Require-Token $governanceWorkflow 'Verify-RepositoryGovernance.ps1' 'Governance workflow implementation'
Require-Token $governanceWorkflow 'Verify-GitHubActionsPolicy.ps1' 'GitHub Actions policy workflow implementation'

$governanceDoc=Read-Utf8 (Require-File 'docs/REPOSITORY_GOVERNANCE.md')
foreach($token in @('immutable releases','release attestation','legacy mutable','release-policy','branch hygiene')){Require-Token $governanceDoc $token 'Repository governance documentation'}

$requiredContexts=@($contract.main_ruleset.required_rules.required_status_checks.contexts|ForEach-Object{[string]$_})
if($requiredContexts.Count-ne3-or$requiredContexts-notcontains'source-gate'-or$requiredContexts-notcontains'repository-governance'-or$requiredContexts-notcontains'release-policy'){
    Fail('Governance required status checks must be exactly source-gate, repository-governance, and release-policy.')
}

Write-Host ('Repository governance source contract: PASS. revision='+[int]$contract.revision+'; required_checks='+$requiredContexts.Count+'; legacy_mutable_tags='+$legacyTags.Count+'; preserved_prefixes='+$preservedPrefixes.Count) -ForegroundColor Green

if(-not$Online){exit 0}
if([string]::IsNullOrWhiteSpace($Repository)-or$Repository-notmatch'^[^/]+/[^/]+$'){Fail('Online governance audit requires owner/repository.')}
if([string]$contract.repository-ne$Repository){Fail('Governance contract repository mismatch: '+[string]$contract.repository+' != '+$Repository)}

$headers=@{
    'Accept'='application/vnd.github+json'
    'User-Agent'='Keelaryn-Repository-Governance'
    'X-GitHub-Api-Version'='2026-03-10'
}
if(-not[string]::IsNullOrWhiteSpace([string]$env:GITHUB_TOKEN)){$headers['Authorization']='Bearer '+[string]$env:GITHUB_TOKEN}
$api='https://api.github.com/repos/'+$Repository

$repoDoc=Invoke-GitHubGet $api $headers
if([string]$repoDoc.default_branch-ne[string]$contract.default_branch){Fail('GitHub default branch mismatch.')}

foreach($property in @('allow_squash_merge','allow_merge_commit','allow_rebase_merge','allow_auto_merge')){
    if($null-ne$repoDoc.PSObject.Properties[$property]){
        $expected=[bool]$contract.merge_policy.$property
        $actual=[bool]$repoDoc.$property
        if($actual-ne$expected){Fail('GitHub repository merge setting mismatch: '+$property+' expected='+$expected+' actual='+$actual)}
    }
}
if($null-eq$repoDoc.PSObject.Properties['delete_branch_on_merge']){Fail('GitHub repository metadata does not expose delete_branch_on_merge.')}
if([bool]$repoDoc.delete_branch_on_merge-ne[bool]$hygiene.delete_branch_on_merge){
    Fail('GitHub repository branch hygiene mismatch: delete_branch_on_merge expected='+[bool]$hygiene.delete_branch_on_merge+' actual='+[bool]$repoDoc.delete_branch_on_merge)
}

$branchName=[string]$contract.default_branch
$branchDoc=Invoke-GitHubGet ($api+'/branches/'+[System.Uri]::EscapeDataString($branchName)) $headers
$rulesetsRaw=Invoke-GitHubGet ($api+'/rulesets?per_page=100') $headers
$rulesRaw=Invoke-GitHubGet ($api+'/rules/branches/'+[System.Uri]::EscapeDataString($branchName)+'?per_page=100') $headers
$rulesets=@();if($null-ne$rulesetsRaw){$rulesets=@($rulesetsRaw)}
$rules=@();if($null-ne$rulesRaw){$rules=@($rulesRaw)}
Write-Host ('Online governance visibility: protected='+[bool]$branchDoc.protected+'; rulesets='+$rulesets.Count+'; active_rules='+$rules.Count+'; delete_branch_on_merge='+[bool]$repoDoc.delete_branch_on_merge) -ForegroundColor DarkGray

if(-not[bool]$branchDoc.protected){Fail('Default branch is not protected by an active branch rule/ruleset.')}

$named=@($rulesets|Where-Object{[string]$_.name-eq[string]$contract.main_ruleset.name})
if($named.Count-ne1){Fail('Expected exactly one repository ruleset named '+[string]$contract.main_ruleset.name+'.')}
$summaryEnforcement=([string]$named[0].enforcement).ToLowerInvariant()
if($summaryEnforcement-notin@('active','enabled')){Fail('Governance ruleset is not active: '+$summaryEnforcement)}
if($null-eq$named[0].id){Fail('Governance ruleset summary is missing id.')}

$detail=Invoke-GitHubGet ($api+'/rulesets/'+[string]$named[0].id) $headers
if([string]$detail.name-ne[string]$contract.main_ruleset.name){Fail('Governance ruleset detail name mismatch.')}
if([string]$detail.target-ne'branch'){Fail('Governance ruleset target must be branch.')}
$detailEnforcement=([string]$detail.enforcement).ToLowerInvariant()
if($detailEnforcement-notin@('active','enabled')){Fail('Governance ruleset detail is not active: '+$detailEnforcement)}

$include=@();if($null-ne$detail.conditions.ref_name.include){$include=@($detail.conditions.ref_name.include|ForEach-Object{[string]$_})}
$exclude=@();if($null-ne$detail.conditions.ref_name.exclude){$exclude=@($detail.conditions.ref_name.exclude|ForEach-Object{[string]$_})}
if($include.Count-ne1-or($include[0]-ne'refs/heads/main'-and$include[0]-ne'~DEFAULT_BRANCH')){
    Fail('Governance ruleset must target only main/default branch; include='+($include-join','))
}
if($exclude.Count-ne0){Fail('Governance ruleset must not exclude refs: '+($exclude-join','))}
if($null-ne$detail.PSObject.Properties['bypass_actors']){
    $bypass=@();if($null-ne$detail.bypass_actors){$bypass=@($detail.bypass_actors)}
    if($bypass.Count-ne0){Fail('Governance ruleset bypass list must be empty.')}
}

$types=@($rules|ForEach-Object{[string]$_.type})
foreach($requiredType in @('pull_request','required_status_checks','non_fast_forward','deletion')){
    if($types-notcontains$requiredType){Fail('Active main rules missing required rule type: '+$requiredType)}
}

$prRules=@($rules|Where-Object{[string]$_.type-eq'pull_request'})
if($prRules.Count-lt1){Fail('Active pull_request rule missing.')}
$pr=$prRules[0].parameters
if([int]$pr.required_approving_review_count-ne[int]$contract.main_ruleset.required_rules.pull_request.required_approving_review_count){Fail('Pull-request approval count mismatch.')}
if([bool]$pr.require_code_owner_review-ne[bool]$contract.main_ruleset.required_rules.pull_request.require_code_owner_review){Fail('Code-owner review rule mismatch.')}
if([bool]$pr.require_last_push_approval-ne[bool]$contract.main_ruleset.required_rules.pull_request.require_last_push_approval){Fail('Last-push approval rule mismatch.')}
if([bool]$pr.dismiss_stale_reviews_on_push-ne[bool]$contract.main_ruleset.required_rules.pull_request.dismiss_stale_reviews_on_push){Fail('Dismiss-stale-reviews rule mismatch.')}
if([bool]$pr.required_review_thread_resolution-ne[bool]$contract.main_ruleset.required_rules.pull_request.required_review_thread_resolution){Fail('Review-thread resolution rule mismatch.')}
$allowed=@($pr.allowed_merge_methods|ForEach-Object{[string]$_})
if($allowed.Count-ne1-or$allowed[0]-ne'squash'){Fail('Ruleset must allow squash merge only.')}

$statusRules=@($rules|Where-Object{[string]$_.type-eq'required_status_checks'})
if($statusRules.Count-lt1){Fail('Active required_status_checks rule missing.')}
$status=$statusRules[0].parameters
if(-not[bool]$status.strict_required_status_checks_policy){Fail('Required status checks must use strict/up-to-date policy.')}
$actualContexts=@($status.required_status_checks|ForEach-Object{[string]$_.context})
foreach($context in $requiredContexts){if($actualContexts-notcontains$context){Fail('Missing required status check: '+$context)}}
if($actualContexts.Count-ne$requiredContexts.Count){Fail('Active required status checks contain unexpected contexts: '+($actualContexts-join', '))}

foreach($tag in $legacyTags){
    $release=Invoke-GitHubGet ($api+'/releases/tags/'+[System.Uri]::EscapeDataString($tag)) $headers
    if([bool]$release.draft){Fail('Legacy mutable release exception must not be a draft: '+$tag)}
    if([string]$release.tag_name-ne$tag){Fail('Legacy mutable release tag mismatch: '+$tag)}
    if($null-ne$release.PSObject.Properties['immutable']-and[bool]$release.immutable){Fail('Legacy mutable release is already immutable and should be removed from the exception list: '+$tag)}
}

Write-Host ('Repository governance online enforcement: PASS. ruleset='+[string]$detail.name+'; required_checks='+$actualContexts.Count+'; legacy releases verified='+$legacyTags.Count+'; branch_hygiene=PASS') -ForegroundColor Green
Write-Warning 'Native immutable-releases repository setting requires Administration read/write and is intentionally verified at the admin bootstrap boundary, not through the ordinary read-only Actions token.'
