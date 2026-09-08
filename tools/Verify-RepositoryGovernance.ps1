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
function Assert-SameStringSet([string[]]$Actual,[string[]]$Expected,[string]$Purpose){
    $a=@($Actual|ForEach-Object{([string]$_).Trim()}|Where-Object{$_})
    $e=@($Expected|ForEach-Object{([string]$_).Trim()}|Where-Object{$_})
    if($a.Count-ne$e.Count){Fail($Purpose+' count mismatch: actual='+$a.Count+' expected='+$e.Count)}
    foreach($value in $e){if($a-cnotcontains$value){Fail($Purpose+' missing value: '+$value)}}
    foreach($value in $a){if($e-cnotcontains$value){Fail($Purpose+' unexpected value: '+$value)}}
}
function Get-WorkflowTriggerPaths([string]$Text,[string]$Trigger){
    $escaped=[regex]::Escape($Trigger)
    $match=[regex]::Match($Text,'(?ms)^  '+$escaped+':\r?\n(?<trigger>.*?)(?=^  [A-Za-z_][A-Za-z0-9_-]*:|^permissions:)')
    if(-not$match.Success){Fail('Workflow is missing trigger block: '+$Trigger)}
    $paths=[regex]::Match($match.Groups['trigger'].Value,'(?ms)^    paths:\r?\n(?<paths>(?:^      - .*\r?\n?)+)')
    if(-not$paths.Success){Fail('Workflow trigger is missing paths list: '+$Trigger)}
    $result=New-Object System.Collections.ArrayList
    foreach($line in ($paths.Groups['paths'].Value -split '\r?\n')){
        if($line-match"^      - ['\"](?<path>.+?)['\"]\s*$"){ [void]$result.Add([string]$Matches['path']) }
    }
    return @($result)
}

$contractPath=Require-File 'REPOSITORY_GOVERNANCE.json'
$contract=(Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8)|ConvertFrom-Json
if([string]$contract.schema-ne'keelaryn.repository-governance.v1'){Fail('Unsupported governance schema: '+[string]$contract.schema)}
if([int]$contract.revision-ne5){Fail('Unexpected governance revision: '+[string]$contract.revision)}
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
if(-not[bool]$hygiene.freeze_preserved_branch_before_delete){Fail('Branch hygiene must freeze preserved branches before deletion.')}
if([string]$hygiene.provenance_tag_prefix-ne'provenance/'){Fail('Branch hygiene provenance tag prefix must be provenance/.')}
$preservedPrefixes=@($hygiene.preserved_prefixes|ForEach-Object{([string]$_).Trim()}|Where-Object{$_})
$expectedPrefixes=@('candidate-manager-','framework-','gate-framework-','manager-','release-manager-')
Assert-SameStringSet $preservedPrefixes $expectedPrefixes 'Branch hygiene preserved-prefix set'
if([string]::IsNullOrWhiteSpace([string]$hygiene.policy)){Fail('Branch hygiene must include a policy statement.')}

$tagRuleset=$contract.provenance_tag_ruleset
if($null-eq$tagRuleset){Fail('Governance is missing provenance_tag_ruleset.')}
if([string]$tagRuleset.name-ne'Keelaryn immutable provenance tags'){Fail('Unexpected provenance tag ruleset name.')}
if([string]$tagRuleset.target-ne'tag'){Fail('Provenance ruleset target must be tag.')}
if([string]$tagRuleset.enforcement-ne'active'){Fail('Provenance ruleset must require active enforcement.')}
Assert-SameStringSet @($tagRuleset.include_refs) @('refs/tags/v*','refs/tags/provenance/**') 'Provenance tag ruleset include refs'
if(@($tagRuleset.bypass_actors).Count-ne0){Fail('Provenance tag ruleset bypass list must be empty.')}
if(-not[bool]$tagRuleset.required_rules.non_fast_forward){Fail('Provenance tag ruleset must block non-fast-forward updates.')}
if(-not[bool]$tagRuleset.required_rules.deletion){Fail('Provenance tag ruleset must block deletion.')}

$ci=$contract.ci_concurrency
if($null-eq$ci){Fail('Governance is missing ci_concurrency.')}
if(-not[bool]$ci.cancel_obsolete_pull_request_runs){Fail('CI policy must cancel obsolete pull-request runs.')}
if([bool]$ci.cancel_main_push_runs){Fail('CI policy must preserve push/main evidence runs.')}

$immutable=$contract.release_policy.immutable_releases
if($null-eq$immutable){Fail('Governance is missing immutable release policy.')}
foreach($property in @('repository_setting_required','future_releases_must_be_immutable','release_attestation_required','verify_each_asset_attestation')){
    if($null-eq$immutable.PSObject.Properties[$property]-or-not[bool]$immutable.$property){Fail('Immutable release policy must require '+$property+'.')}
}
if([string]$immutable.legacy_release_baseline-ne'LEGACY_RELEASE_BASELINE.json'){Fail('Immutable release policy must bind LEGACY_RELEASE_BASELINE.json.')}
$legacyTags=@($immutable.legacy_mutable_tags|ForEach-Object{([string]$_).Trim()}|Where-Object{$_})
foreach($tag in $legacyTags){if($tag-notmatch'^v\d+\.\d+\.\d+$'){Fail('Invalid legacy mutable release tag: '+$tag)}}
if(@($legacyTags|Select-Object -Unique).Count-ne$legacyTags.Count){Fail('Legacy mutable release tags contain duplicates.')}
if([string]::IsNullOrWhiteSpace([string]$immutable.legacy_policy)){Fail('Immutable release policy must explain the legacy exception contract.')}

$baselinePath=Require-File 'LEGACY_RELEASE_BASELINE.json'
$baseline=(Get-Content -LiteralPath $baselinePath -Raw -Encoding UTF8)|ConvertFrom-Json
if([string]$baseline.schema-ne'keelaryn.legacy-release-baseline.v1'){Fail('Unsupported legacy release baseline schema.')}
if([string]$baseline.repository-ne[string]$contract.repository){Fail('Legacy release baseline repository mismatch.')}
$baselineReleases=@($baseline.releases)
if($baselineReleases.Count-eq0){Fail('Legacy release baseline must contain at least one release.')}
$baselineTags=@($baselineReleases|ForEach-Object{([string]$_.tag).Trim()})
if(@($baselineTags|Select-Object -Unique).Count-ne$baselineTags.Count){Fail('Legacy release baseline tags contain duplicates.')}
Assert-SameStringSet $legacyTags $baselineTags 'Legacy mutable tag/baseline set'
foreach($row in $baselineReleases){
    $tag=([string]$row.tag).Trim()
    if($tag-notmatch'^v\d+\.\d+\.\d+$'){Fail('Legacy baseline has invalid tag: '+$tag)}
    if(([string]$row.target_commit)-notmatch'^[0-9a-f]{40}$'){Fail('Legacy baseline has invalid target commit: '+$tag)}
    if([int64]$row.release_id-le0){Fail('Legacy baseline has invalid release id: '+$tag)}
    if([bool]$row.immutable){Fail('Legacy baseline may contain only historical mutable releases: '+$tag)}
    $assets=@($row.assets)
    if($assets.Count-eq0){Fail('Legacy baseline release has no assets: '+$tag)}
    $assetNames=@($assets|ForEach-Object{([string]$_.name).Trim()})
    if(@($assetNames|Select-Object -Unique).Count-ne$assetNames.Count){Fail('Legacy baseline contains duplicate asset names: '+$tag)}
    foreach($asset in $assets){
        if([string]::IsNullOrWhiteSpace([string]$asset.name)){Fail('Legacy baseline asset has empty name: '+$tag)}
        if([int64]$asset.size-lt0){Fail('Legacy baseline asset has invalid size: '+$tag+'/'+[string]$asset.name)}
        if(([string]$asset.sha256)-notmatch'^[0-9a-f]{64}$'){Fail('Legacy baseline asset has invalid SHA-256: '+$tag+'/'+[string]$asset.name)}
    }
}

$criticalPaths=@($contract.release_policy.critical_paths|ForEach-Object{([string]$_).Trim()}|Where-Object{$_})
$expectedCritical=@('.github/workflows/public-release.yml','manager/**','PUBLIC_PROVENANCE.json','REPOSITORY_GOVERNANCE.json','LEGACY_RELEASE_BASELINE.json','README.md','GETTING_STARTED.md','docs/USING_WITH_CHATGPT.md','docs/TROUBLESHOOTING.md')
Assert-SameStringSet $criticalPaths $expectedCritical 'Release-critical paths'
$pushPaths=@($contract.release_policy.public_release_push_paths|ForEach-Object{([string]$_).Trim()}|Where-Object{$_})
$expectedPush=@('.github/workflows/public-release.yml','manager/**','PUBLIC_PROVENANCE.json','REPOSITORY_GOVERNANCE.json','LEGACY_RELEASE_BASELINE.json')
Assert-SameStringSet $pushPaths $expectedPush 'Public-release push paths'

$future=$contract.release_policy.future_provenance
if($null-eq$future-or-not[bool]$future.qualified_product_source_commit_required){Fail('Future release provenance must require the qualified product-source commit.')}
if([string]::IsNullOrWhiteSpace([string]$future.policy)){Fail('Future provenance policy text is missing.')}

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

$prCancelToken='cancel-in-progress: ${{ github.event_name == ''pull_request'' }}'
$sourceWorkflow=Read-Utf8 (Require-File '.github/workflows/windows-powershell.yml')
$governanceWorkflow=Read-Utf8 (Require-File '.github/workflows/repository-governance.yml')
$releaseSource=Read-Utf8 (Require-File '.github/workflows/public-release.yml')
Require-Token $sourceWorkflow $prCancelToken 'Windows source workflow concurrency policy'
Require-Token $governanceWorkflow $prCancelToken 'Repository governance workflow concurrency policy'
Require-Token $releaseSource $prCancelToken 'Public release workflow concurrency policy'
if($sourceWorkflow-match'(?m)^\s*cancel-in-progress:\s*true\s*$'){Fail('Windows source workflow must not unconditionally cancel main evidence runs.')}
if($governanceWorkflow-match'(?m)^\s*cancel-in-progress:\s*true\s*$'){Fail('Repository governance workflow must not unconditionally cancel main evidence runs.')}

foreach($token in @(
    'production_validation.full_gate_pass',
    'production_validation.production_doctor_pass',
    'production_validation.production_ux_smoke_pass',
    'production_validation.tested_update_sha256',
    'REPOSITORY_GOVERNANCE.json',
    'LEGACY_RELEASE_BASELINE.json',
    'legacy_mutable',
    'LEGACY_MUTABLE',
    '--draft',
    'isImmutable',
    'gh release verify',
    'gh release verify-asset',
    '--cleanup-tag',
    'contents: write',
    '.WaitForExit(15000)'
)){Require-Token $releaseSource $token 'Public release workflow'}
if($releaseSource-match'\.WaitForExit\(\)'){Fail('Public release workflow contains an unbounded parameterless WaitForExit().')}
if($releaseSource-notmatch'(?s)First-run menu smoke timed out after 15 seconds.*WaitForExit\(5000\)'){Fail('Public release workflow does not contain bounded timeout diagnostics and cleanup.')}
if($releaseSource-notmatch'(?s)New release was published without native immutability; deleting unsafe mutable release and tag.*gh release delete'){Fail('Public release workflow does not fail closed on a newly published mutable release.')}
if($releaseSource-notmatch'(?s)Legacy mutable release exception: exact published assets are byte-identical.*leaving historical release unchanged'){Fail('Public release workflow does not preserve legacy mutable releases as read-only historical exceptions.')}

$publicPrPaths=Get-WorkflowTriggerPaths $releaseSource 'pull_request'
$publicPushPaths=Get-WorkflowTriggerPaths $releaseSource 'push'
Assert-SameStringSet $publicPrPaths $criticalPaths 'Public-release pull-request path filter'
Assert-SameStringSet $publicPushPaths $pushPaths 'Public-release push path filter'

$releasePolicySource=Read-Utf8 (Require-File '.github/workflows/release-policy.yml')
foreach($token in @(
    'release-policy:',
    'distribution-gate',
    'HEAD_SHA',
    'Release-critical PR detected',
    'Release policy PASS',
    'check-runs?per_page=100',
    'release_policy.critical_paths'
)){Require-Token $releasePolicySource $token 'Conditional release-policy workflow'}

Require-Token $governanceWorkflow 'repository-governance:' 'Governance workflow job identity'
Require-Token $governanceWorkflow 'Verify-RepositoryGovernance.ps1' 'Governance workflow implementation'
Require-Token $governanceWorkflow 'Verify-GitHubActionsPolicy.ps1' 'GitHub Actions policy workflow implementation'

$governanceDoc=Read-Utf8 (Require-File 'docs/REPOSITORY_GOVERNANCE.md')
foreach($token in @('immutable releases','release attestation','legacy mutable','release-policy','branch hygiene','LEGACY_RELEASE_BASELINE.json','provenance tag')){Require-Token $governanceDoc $token 'Repository governance documentation'}

$requiredContexts=@($contract.main_ruleset.required_rules.required_status_checks.contexts|ForEach-Object{[string]$_})
Assert-SameStringSet $requiredContexts @('source-gate','repository-governance','release-policy') 'Governance required status checks'

Write-Host ('Repository governance source contract: PASS. revision='+[int]$contract.revision+'; required_checks='+$requiredContexts.Count+'; legacy_mutable_tags='+$legacyTags.Count+'; preserved_prefixes='+$preservedPrefixes.Count+'; critical_paths='+$criticalPaths.Count) -ForegroundColor Green

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
if($null-ne$repoDoc.PSObject.Properties['delete_branch_on_merge']){
    if([bool]$repoDoc.delete_branch_on_merge-ne[bool]$hygiene.delete_branch_on_merge){Fail('GitHub repository branch hygiene mismatch: delete_branch_on_merge expected='+[bool]$hygiene.delete_branch_on_merge+' actual='+[bool]$repoDoc.delete_branch_on_merge)}
    Write-Host ('Online branch-hygiene setting visible: delete_branch_on_merge='+[bool]$repoDoc.delete_branch_on_merge) -ForegroundColor DarkGray
}else{
    Write-Warning 'delete_branch_on_merge is not exposed to the ordinary read-only Actions token; its server value is verified at the administrator governance boundary.'
}

$branchName=[string]$contract.default_branch
$branchDoc=Invoke-GitHubGet ($api+'/branches/'+[System.Uri]::EscapeDataString($branchName)) $headers
$rulesetsRaw=Invoke-GitHubGet ($api+'/rulesets?per_page=100') $headers
$rulesRaw=Invoke-GitHubGet ($api+'/rules/branches/'+[System.Uri]::EscapeDataString($branchName)+'?per_page=100') $headers
$rulesets=@();if($null-ne$rulesetsRaw){$rulesets=@($rulesetsRaw)}
$rules=@();if($null-ne$rulesRaw){$rules=@($rulesRaw)}
Write-Host ('Online governance visibility: protected='+[bool]$branchDoc.protected+'; rulesets='+$rulesets.Count+'; active_main_rules='+$rules.Count) -ForegroundColor DarkGray
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
if($include.Count-ne1-or($include[0]-ne'refs/heads/main'-and$include[0]-ne'~DEFAULT_BRANCH')){Fail('Governance ruleset must target only main/default branch; include='+($include-join','))}
if($exclude.Count-ne0){Fail('Governance ruleset must not exclude refs: '+($exclude-join','))}
if($null-ne$detail.PSObject.Properties['bypass_actors']){if(@($detail.bypass_actors).Count-ne0){Fail('Governance ruleset bypass list must be empty.')}}

$types=@($rules|ForEach-Object{[string]$_.type})
foreach($requiredType in @('pull_request','required_status_checks','non_fast_forward','deletion')){if($types-notcontains$requiredType){Fail('Active main rules missing required rule type: '+$requiredType)}}
$prRules=@($rules|Where-Object{[string]$_.type-eq'pull_request'})
if($prRules.Count-lt1){Fail('Active pull_request rule missing.')}
$pr=$prRules[0].parameters
if([int]$pr.required_approving_review_count-ne[int]$contract.main_ruleset.required_rules.pull_request.required_approving_review_count){Fail('Pull-request approval count mismatch.')}
if([bool]$pr.require_code_owner_review-ne[bool]$contract.main_ruleset.required_rules.pull_request.require_code_owner_review){Fail('Code-owner review rule mismatch.')}
if([bool]$pr.require_last_push_approval-ne[bool]$contract.main_ruleset.required_rules.pull_request.require_last_push_approval){Fail('Last-push approval rule mismatch.')}
if([bool]$pr.dismiss_stale_reviews_on_push-ne[bool]$contract.main_ruleset.required_rules.pull_request.dismiss_stale_reviews_on_push){Fail('Dismiss-stale-reviews rule mismatch.')}
if([bool]$pr.required_review_thread_resolution-ne[bool]$contract.main_ruleset.required_rules.pull_request.required_review_thread_resolution){Fail('Review-thread resolution rule mismatch.')}
$allowed=@($pr.allowed_merge_methods|ForEach-Object{[string]$_})
Assert-SameStringSet $allowed @('squash') 'Main ruleset allowed merge methods'
$statusRules=@($rules|Where-Object{[string]$_.type-eq'required_status_checks'})
if($statusRules.Count-lt1){Fail('Active required_status_checks rule missing.')}
$status=$statusRules[0].parameters
if(-not[bool]$status.strict_required_status_checks_policy){Fail('Required status checks must use strict/up-to-date policy.')}
$actualContexts=@($status.required_status_checks|ForEach-Object{[string]$_.context})
Assert-SameStringSet $actualContexts $requiredContexts 'Active required status checks'

$serverTagRulesets=@($rulesets|Where-Object{[string]$_.name-eq[string]$tagRuleset.name})
if($serverTagRulesets.Count-eq0){
    if([string]$env:GITHUB_EVENT_NAME-eq'pull_request'){
        Write-Warning ('Provenance tag ruleset is not active yet. PR source validation allows this bootstrap state; activate '+[string]$tagRuleset.name+' before merge.')
    }else{
        Fail('Required provenance tag ruleset is not active: '+[string]$tagRuleset.name)
    }
}elseif($serverTagRulesets.Count-ne1){
    Fail('Expected exactly one provenance tag ruleset named '+[string]$tagRuleset.name+'.')
}else{
    $tagDetail=Invoke-GitHubGet ($api+'/rulesets/'+[string]$serverTagRulesets[0].id) $headers
    if([string]$tagDetail.target-ne'tag'){Fail('Server provenance ruleset target must be tag.')}
    if(([string]$tagDetail.enforcement).ToLowerInvariant()-notin@('active','enabled')){Fail('Server provenance tag ruleset is not active.')}
    $tagInclude=@();if($null-ne$tagDetail.conditions.ref_name.include){$tagInclude=@($tagDetail.conditions.ref_name.include|ForEach-Object{[string]$_})}
    Assert-SameStringSet $tagInclude @($tagRuleset.include_refs) 'Server provenance tag ruleset includes'
    $tagExclude=@();if($null-ne$tagDetail.conditions.ref_name.exclude){$tagExclude=@($tagDetail.conditions.ref_name.exclude|ForEach-Object{[string]$_})}
    if($tagExclude.Count-ne0){Fail('Server provenance tag ruleset must not exclude refs.')}
    if($null-ne$tagDetail.PSObject.Properties['bypass_actors']-and@($tagDetail.bypass_actors).Count-ne0){Fail('Server provenance tag ruleset bypass list must be empty.')}
    $tagRuleTypes=@($tagDetail.rules|ForEach-Object{[string]$_.type})
    foreach($requiredType in @('non_fast_forward','deletion')){if($tagRuleTypes-notcontains$requiredType){Fail('Server provenance tag ruleset missing rule: '+$requiredType)}}
    Write-Host ('Provenance tag ruleset: PASS. id='+[string]$serverTagRulesets[0].id) -ForegroundColor Green
}

foreach($row in $baselineReleases){
    $tag=([string]$row.tag).Trim()
    $release=Invoke-GitHubGet ($api+'/releases/tags/'+[System.Uri]::EscapeDataString($tag)) $headers
    if([bool]$release.draft){Fail('Legacy mutable release exception must not be a draft: '+$tag)}
    if([string]$release.tag_name-ne$tag){Fail('Legacy mutable release tag mismatch: '+$tag)}
    if([int64]$release.id-ne[int64]$row.release_id){Fail('Legacy release id mismatch: '+$tag)}
    if($null-ne$release.PSObject.Properties['immutable']-and[bool]$release.immutable-ne[bool]$row.immutable){Fail('Legacy release immutable-state mismatch: '+$tag)}
    $tagRef=Invoke-GitHubGet ($api+'/git/ref/tags/'+[System.Uri]::EscapeDataString($tag)) $headers
    if([string]$tagRef.object.type-ne'commit'){Fail('Legacy release tag must point directly to a commit: '+$tag)}
    if([string]$tagRef.object.sha-cne[string]$row.target_commit){Fail('Legacy release tag target mismatch: '+$tag)}
    $actualAssets=@($release.assets)
    $expectedAssets=@($row.assets)
    if($actualAssets.Count-ne$expectedAssets.Count){Fail('Legacy release asset-count mismatch: '+$tag+' actual='+$actualAssets.Count+' expected='+$expectedAssets.Count)}
    foreach($expected in $expectedAssets){
        $matches=@($actualAssets|Where-Object{[string]$_.name-ceq[string]$expected.name})
        if($matches.Count-ne1){Fail('Legacy release expected asset missing/duplicated: '+$tag+'/'+[string]$expected.name)}
        $actual=$matches[0]
        if([int64]$actual.size-ne[int64]$expected.size){Fail('Legacy release asset size mismatch: '+$tag+'/'+[string]$expected.name)}
        $digest=([string]$actual.digest).Trim().ToLowerInvariant()
        if($digest-notmatch'^sha256:[0-9a-f]{64}$'){Fail('Legacy release asset is missing a GitHub SHA-256 digest: '+$tag+'/'+[string]$expected.name)}
        if($digest.Substring(7)-cne([string]$expected.sha256).ToLowerInvariant()){Fail('Legacy release asset SHA-256 mismatch: '+$tag+'/'+[string]$expected.name)}
    }
    Write-Host ('Legacy release baseline PASS: '+$tag+'; assets='+$actualAssets.Count+'; target='+[string]$row.target_commit) -ForegroundColor Green
}

Write-Host ('Repository governance online enforcement: PASS. main_ruleset='+[string]$detail.name+'; required_checks='+$actualContexts.Count+'; legacy releases verified='+$baselineReleases.Count+'; branch_hygiene_source=PASS') -ForegroundColor Green
Write-Warning 'Native immutable-release enablement, server-side GitHub Actions policy, provenance tag ruleset creation/update, and destructive branch cleanup require repository Administration authority and are performed at the explicit administrator governance boundary.'
