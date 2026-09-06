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
if([int]$contract.revision-ne1){Fail('Unexpected governance revision: '+[string]$contract.revision)}
if([string]$contract.default_branch-ne'main'){Fail('Governance default branch must be main.')}
if(-not[bool]$contract.merge_policy.allow_squash_merge){Fail('Governance must allow squash merge.')}
if([bool]$contract.merge_policy.allow_merge_commit){Fail('Governance must forbid merge commits.')}
if([bool]$contract.merge_policy.allow_rebase_merge){Fail('Governance must forbid rebase merge.')}
if([bool]$contract.merge_policy.allow_auto_merge){Fail('Governance must keep auto-merge disabled.')}

foreach($relative in @(
    '.github/CODEOWNERS',
    '.github/pull_request_template.md',
    '.github/workflows/repository-governance.yml',
    '.github/workflows/windows-powershell.yml',
    '.github/workflows/public-release.yml',
    'CONTRIBUTING.md',
    'SECURITY.md',
    'docs/REPOSITORY_GOVERNANCE.md',
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
    '.github/workflows/repository-governance.yml'
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
    'contents: write'
)){Require-Token $releaseSource $token 'Public release workflow'}

$governanceWorkflow=Read-Utf8 (Require-File '.github/workflows/repository-governance.yml')
Require-Token $governanceWorkflow 'repository-governance:' 'Governance workflow job identity'
Require-Token $governanceWorkflow 'Verify-RepositoryGovernance.ps1' 'Governance workflow implementation'

$requiredContexts=@($contract.main_ruleset.required_rules.required_status_checks.contexts|ForEach-Object{[string]$_})
if($requiredContexts.Count-ne2-or$requiredContexts-notcontains'source-gate'-or$requiredContexts-notcontains'repository-governance'){
    Fail('Governance required status checks must be exactly source-gate and repository-governance.')
}

Write-Host 'Repository governance source contract: PASS' -ForegroundColor Green

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

# GitHub's read-only Actions token does not expose every repository merge toggle.
# Main's actual allowed merge method is enforced below from the active branch
# rules endpoint, which is readable with Metadata: read for a public repository.
foreach($property in @('allow_squash_merge','allow_merge_commit','allow_rebase_merge','allow_auto_merge')){
    if($null-ne$repoDoc.PSObject.Properties[$property]){
        $expected=[bool]$contract.merge_policy.$property
        $actual=[bool]$repoDoc.$property
        if($actual-ne$expected){Fail('GitHub repository merge setting mismatch: '+$property+' expected='+$expected+' actual='+$actual)}
    }
}

$branchName=[string]$contract.default_branch
$branchDoc=Invoke-GitHubGet ($api+'/branches/'+[System.Uri]::EscapeDataString($branchName)) $headers
$rulesets=@(Invoke-GitHubGet ($api+'/rulesets?per_page=100') $headers)
$rules=@(Invoke-GitHubGet ($api+'/rules/branches/'+[System.Uri]::EscapeDataString($branchName)+'?per_page=100') $headers)
Write-Host ('Online governance visibility: protected='+[bool]$branchDoc.protected+'; rulesets='+$rulesets.Count+'; active_rules='+$rules.Count) -ForegroundColor DarkGray

if(-not[bool]$branchDoc.protected){Fail('Default branch is not protected by an active branch rule/ruleset.')}

$named=@($rulesets|Where-Object{[string]$_.name-eq[string]$contract.main_ruleset.name})
if($named.Count-ne1){Fail('Expected exactly one repository ruleset named '+[string]$contract.main_ruleset.name+'.')}
if([string]$named[0].target-ne'branch'){Fail('Governance ruleset target must be branch.')}
$enforcement=([string]$named[0].enforcement).ToLowerInvariant()
if($enforcement-notin@('active','enabled')){Fail('Governance ruleset is not active: '+$enforcement)}

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

Write-Host ('Repository governance online enforcement: PASS. ruleset='+[string]$named[0].name) -ForegroundColor Green
