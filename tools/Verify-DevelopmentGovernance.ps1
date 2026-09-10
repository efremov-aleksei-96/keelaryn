[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[System.IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')

function Fail([string]$Message){throw $Message}
function Require-File([string]$Relative){
    $path=Join-Path $RepositoryRoot $Relative.Replace('/','\')
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){Fail('Missing development-governance file: '+$Relative)}
    return $path
}
function Read-Text([string]$Relative){return [System.IO.File]::ReadAllText((Require-File $Relative),[System.Text.Encoding]::UTF8)}
function Require-Token([string]$Text,[string]$Token,[string]$Purpose){
    if($Text.IndexOf($Token,[System.StringComparison]::Ordinal)-lt0){Fail($Purpose+' missing token: '+$Token)}
}

$policy=Get-Content -LiteralPath (Require-File 'DEVELOPMENT_GOVERNANCE.json') -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$policy.schema -cne 'keelaryn.development-governance.v1'-or [int]$policy.revision -ne 1){Fail 'Unsupported development governance contract.'}
if([string]$policy.repository -cne 'efremov-aleksei-96/keelaryn'){Fail 'Development governance repository mismatch.'}
if([string]$policy.development_branches.pattern -cne 'dev/**'){Fail 'Development branch pattern mismatch.'}
if([string]$policy.development_branches.qualification_state -cne 'unqualified'){Fail 'Development branches must remain explicitly unqualified.'}
if(-not [bool]$policy.development_branches.push_before_qualification_allowed){Fail 'Development pushes before qualification must be explicitly allowed.'}
if(-not [bool]$policy.development_branches.direct_merge_to_main_forbidden){Fail 'Development policy must forbid direct merge semantics.'}
if([string]$policy.ci.workflow -cne '.github/workflows/development-validation.yml'){Fail 'Development workflow path mismatch.'}
if([string]$policy.ci.runner -cne 'windows-2025'){Fail 'Development validation runner must be windows-2025.'}
if([string]$policy.ci.token_permissions -cne 'contents: read'){Fail 'Development validation token permission must be contents: read.'}
if(-not [bool]$policy.ci.cancel_obsolete_runs){Fail 'Development CI must cancel obsolete branch iterations.'}
if([int]$policy.ci.artifact_retention_days -ne 3){Fail 'Development evidence retention must be exactly 3 days.'}
if([bool]$policy.ci.upload_disposable_worktrees -or [bool]$policy.ci.publish_release_assets){Fail 'Development CI must not upload worktrees or publish release assets.'}
if([bool]$policy.promotion.development_validation_is_production_qualification){Fail 'Development validation must never equal production qualification.'}
if(-not [bool]$policy.promotion.pull_request_to_main_required -or -not [bool]$policy.promotion.existing_main_required_checks_remain_authoritative -or -not [bool]$policy.promotion.production_release_boundary_unchanged){Fail 'Promotion boundary is incomplete.'}

$budget=$policy.resource_budget
if([int]$budget.repository_target_mib -ne 100 -or [int]$budget.repository_warning_mib -ne 250){Fail 'Repository size budget mismatch.'}
if([int]$budget.tracked_file_target_mib -ne 1 -or [int]$budget.tracked_file_warning_mib -ne 5 -or [int]$budget.tracked_file_policy_max_mib -ne 50){Fail 'Tracked-file budget mismatch.'}
if([int]$budget.active_branch_target -ne 50 -or [int]$budget.development_artifact_retention_days -ne 3 -or [int]$budget.cache_target_mib -ne 1024){Fail 'Development resource budget mismatch.'}
if([bool]$budget.commit_generated_release_archives -or [bool]$budget.upload_tests_work -or [bool]$budget.upload_duplicate_build_artifacts){Fail 'Development resource policy must reject generated archives/worktree/duplicate uploads.'}

$workflow=Read-Text '.github/workflows/development-validation.yml'
foreach($token in @(
    'branches:',
    "'dev/**'",
    'windows-2025',
    'contents: read',
    'cancel-in-progress: true',
    'Invoke-DevelopmentValidation.ps1',
    'retention-days: 3',
    'DEVELOPMENT_VALIDATION.json'
)){Require-Token $workflow $token 'Development workflow'}
if($workflow -match '(?im)^\s*pull_request_target\s*:'){Fail 'pull_request_target is forbidden.'}
if($workflow -match '(?im)^\s*contents:\s*write\s*$'){Fail 'Development workflow must not request contents: write.'}
if($workflow -match '(?i)(gh\s+release|create-release|upload-release|GITHUB_TOKEN.*write)'){Fail 'Development workflow contains publication-like behavior.'}

$runnerPath=Require-File 'tools/Invoke-DevelopmentValidation.ps1'
$tokens=$null;$errors=$null
[void][System.Management.Automation.Language.Parser]::ParseFile($runnerPath,[ref]$tokens,[ref]$errors)
if(@($errors).Count-ne 0){Fail('Development validation runner parser error: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}

Write-Host 'Development governance: PASS. branch=dev/**; runner=windows-2025; evidence_retention=3d; publication=false' -ForegroundColor Green
