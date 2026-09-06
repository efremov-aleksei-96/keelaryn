[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))

$ErrorActionPreference='Stop'
$RepositoryRoot=[System.IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')

function Fail([string]$Message){throw $Message}
function Require-File([string]$Relative){
    $path=Join-Path $RepositoryRoot $Relative.Replace('/','\')
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){Fail('Missing GitHub Actions policy file: '+$Relative)}
    return $path
}
function Read-Utf8([string]$Path){return [System.IO.File]::ReadAllText($Path,[System.Text.Encoding]::UTF8)}

$contract=(Get-Content -LiteralPath (Require-File 'REPOSITORY_GOVERNANCE.json') -Raw -Encoding UTF8)|ConvertFrom-Json
if([string]$contract.schema-ne'keelaryn.repository-governance.v1'-or[int]$contract.revision-lt2){Fail('GitHub Actions policy requires repository governance revision 2 or later.')}
$policy=$contract.actions_policy
if($null-eq$policy){Fail('Repository governance is missing actions_policy.')}
if(-not[bool]$policy.enabled){Fail('GitHub Actions must remain enabled.')}
if([string]$policy.allowed_actions-ne'selected'){Fail('GitHub Actions allowed_actions must be selected.')}
if(-not[bool]$policy.sha_pinning_required){Fail('GitHub Actions policy must require full-SHA pinning.')}
if([bool]$policy.selected_actions.github_owned_allowed){Fail('Broad github_owned_allowed must remain disabled; use the explicit allowlist.')}
if([bool]$policy.selected_actions.verified_allowed){Fail('Broad verified creator allowance must remain disabled.')}
if([string]$policy.default_workflow_permissions-ne'read'){Fail('Default workflow permissions must be read.')}
if([bool]$policy.can_approve_pull_request_reviews){Fail('GitHub Actions must not be allowed to approve pull requests.')}
if(-not[bool]$policy.dependabot_github_actions_updates){Fail('Dependabot GitHub Actions updates must remain enabled in policy.')}

$patterns=@($policy.selected_actions.patterns_allowed|ForEach-Object{([string]$_).Trim()})
if($patterns.Count-eq0){Fail('GitHub Actions allowlist must not be empty.')}
if(@($patterns|Select-Object -Unique).Count-ne$patterns.Count){Fail('GitHub Actions allowlist contains duplicates.')}
foreach($pattern in $patterns){
    if($pattern-notmatch'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@\*$'){Fail('Unsupported GitHub Actions allowlist pattern: '+$pattern)}
}

$dependabot=Read-Utf8 (Require-File '.github/dependabot.yml')
foreach($pattern in @(
    '(?m)^version:\s*2\s*$',
    '(?m)^\s*-\s*package-ecosystem:\s*github-actions\s*$',
    '(?m)^\s*directory:\s*["'']?/[''\"]?\s*$',
    '(?m)^\s*interval:\s*weekly\s*$'
)){
    if($dependabot-notmatch$pattern){Fail('Dependabot GitHub Actions update configuration is incomplete; pattern='+$pattern)}
}

$workflowRoot=Join-Path $RepositoryRoot '.github\workflows'
if(-not(Test-Path -LiteralPath $workflowRoot -PathType Container)){Fail('Missing .github/workflows directory.')}
$workflowFiles=@(Get-ChildItem -LiteralPath $workflowRoot -File -Force|Where-Object{$_.Extension.ToLowerInvariant()-in@('.yml','.yaml')})
if($workflowFiles.Count-eq0){Fail('No GitHub Actions workflows found.')}

$externalCount=0
foreach($file in $workflowFiles){
    $lines=[System.IO.File]::ReadAllLines($file.FullName,[System.Text.Encoding]::UTF8)
    for($i=0;$i-lt$lines.Length;$i++){
        $line=[string]$lines[$i]
        $match=[regex]::Match($line,'^\s*(?:-\s*)?uses:\s*([^#\s]+)(?:\s+#\s*(.*))?\s*$')
        if(-not$match.Success){continue}
        $reference=[string]$match.Groups[1].Value
        if($reference.StartsWith('./',[System.StringComparison]::Ordinal)){continue}
        if($reference.StartsWith('docker://',[System.StringComparison]::OrdinalIgnoreCase)){Fail('Docker action references are not allowed by the current policy: '+$reference)}

        $externalCount++
        $refMatch=[regex]::Match($reference,'^([^@\s]+)@([0-9a-fA-F]{40})$')
        if(-not$refMatch.Success){Fail('External action must use a full 40-hex commit SHA: '+$file.Name+':'+($i+1)+' '+$reference)}
        $source=[string]$refMatch.Groups[1].Value
        $allowed=$false
        foreach($pattern in $patterns){if(($source+'@*')-like$pattern){$allowed=$true;break}}
        if(-not$allowed){Fail('External action is outside the explicit allowlist: '+$source)}

        $comment=([string]$match.Groups[2].Value).Trim()
        if($comment-notmatch'^v\d+(?:\.\d+){0,2}(?:\s|$)'){
            Fail('SHA-pinned action must retain a same-line version comment for Dependabot: '+$file.Name+':'+($i+1))
        }
    }
}
if($externalCount-eq0){Fail('No external GitHub Actions references were found to validate.')}

Write-Host ('GitHub Actions supply-chain policy: PASS. workflows='+$workflowFiles.Count+'; external_actions='+$externalCount+'; allowlist='+$patterns.Count) -ForegroundColor Green
Write-Warning 'Server-side Actions allowlist/SHA-pinning/default-token settings require repository Administration permission and are verified at the admin bootstrap boundary.'
