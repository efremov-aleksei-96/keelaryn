[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$Utf8NoBom=New-Object Text.UTF8Encoding($false)

function Fail([string]$Message){throw $Message}

$source=Join-Path $RepositoryRoot 'tools\Close-Manager41711Review.ps1'
if(-not(Test-Path -LiteralPath $source -PathType Leaf)){Fail 'Closure source script missing.'}
$text=[IO.File]::ReadAllText($source,[Text.Encoding]::UTF8)
$text=$text.Replace([string][char]0x2014,'-')

$oldBootstrap="$([char]36)expectedBootstrap=@('.github/workflows/close-manager-4.17.11-review.yml','tools/Close-Manager41711Review.ps1')|Sort-Object"
$newBootstrap="$([char]36)expectedBootstrap=@('.github/workflows/close-manager-4.17.11-review.yml','tools/Close-Manager41711Review.ps1','tools/Stage-Manager41711Closure.ps1')|Sort-Object"
if(-not$text.Contains($oldBootstrap)){Fail 'Closure bootstrap identity line not found.'}
$text=$text.Replace($oldBootstrap,$newBootstrap)

$marker='& git -C $RepositoryRoot add -A'
$index=$text.IndexOf($marker,[StringComparison]::Ordinal)
if($index-lt0){Fail 'Closure commit marker not found.'}
$prefix=$text.Substring(0,$index)
$suffix=@'
$staging=Join-Path $RepositoryRoot 'tests\closure-staging-41711'
if(Test-Path -LiteralPath $staging){Remove-Item -LiteralPath $staging -Recurse -Force}
$publish=@(
    'MANAGER_DEVELOPMENT_STATE.json',
    'MANAGER_ENGINEERING_ROADMAP.md',
    'tests\knowledge\audits\post-4.17.10-public-review.json',
    'tests\knowledge\defects\manager-4.17.10-postfreeze.json',
    'tests\knowledge\risk-map.json',
    'tools\Invoke-DevelopmentValidation.ps1',
    '.github\workflows\development-validation.yml'
)
foreach($rel in $publish){
    $src=Join-Path $RepositoryRoot $rel
    if(-not(Test-Path -LiteralPath $src -PathType Leaf)){Fail('Closure publish source missing: '+$rel)}
    $dst=Join-Path $staging ('files\'+$rel)
    $parent=Split-Path -Parent $dst
    if(-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
    Copy-Item -LiteralPath $src -Destination $dst -Force
}
$manifest=[ordered]@{
    schema='keelaryn.manager-closure-staging.v1'
    manager_version='4.17.11'
    closure_evidence_run='34769051128'
    closure_evidence_head='89d593b261b4e432fef2f62484cfbf3293ecf4cc'
    source_head=(git -C $RepositoryRoot rev-parse HEAD).Trim()
    target_files=@($publish|ForEach-Object{$_.Replace('\','/')})
    delete_paths=@(
        '.github/workflows/close-manager-4.17.11-review.yml',
        '.github/workflows/diagnose-manager-4.17.11-runtime.yml',
        '.github/workflows/materialize-manager-4.17.11.yml',
        '.github/workflows/repair-manager-4.17.11-runtime.yml',
        '.github/workflows/sync-manager-4.17.11-development-metadata.yml',
        '.github/workflows/validate-manager-4.17.11-review.yml',
        'tools/Apply-Manager41711ReleaseReviewFixes.ps1',
        'tools/Close-Manager41711Review.ps1',
        'tools/Stage-Manager41711Closure.ps1'
    )
    validators='closure controls + engineering knowledge + public manifest + candidate metadata + repository verification + diff-check PASS before staging'
}
$manifestText=(($manifest|ConvertTo-Json -Depth 10).Replace("`r`n","`n"))+"`n"
[IO.File]::WriteAllText((Join-Path $staging 'MANIFEST.json'),$manifestText,$Utf8NoBom)

& git -C $RepositoryRoot reset --hard HEAD
if($LASTEXITCODE-ne0){Fail 'Could not restore canonical worktree before staging commit.'}
& git -C $RepositoryRoot clean -fd -- ':!tests/closure-staging-41711'
if($LASTEXITCODE-ne0){Fail 'Could not clean non-staging worktree after closure transform.'}
& git -C $RepositoryRoot add -- 'tests/closure-staging-41711'
$staged=@(git -C $RepositoryRoot diff --cached --name-only)
if($staged.Count-ne8){Fail('Expected 8 staging files; observed '+$staged.Count+': '+([string]::Join(', ',@($staged))))}
& git -C $RepositoryRoot config user.name 'github-actions[bot]'
& git -C $RepositoryRoot config user.email '41898282+github-actions[bot]@users.noreply.github.com'
& git -C $RepositoryRoot commit -m 'Stage validated Manager 4.17.11 review closure blobs'
if($LASTEXITCODE-ne0){Fail 'Closure staging commit failed.'}
& git -C $RepositoryRoot push origin HEAD:dev/manager-4.17.11
if($LASTEXITCODE-ne0){Fail 'Closure staging push failed.'}
Write-Host 'Validated 4.17.11 closure blobs staged remotely: PASS' -ForegroundColor Green
'@

$temp=Join-Path $env:RUNNER_TEMP 'Close-Manager41711Review-stage.ps1'
[IO.File]::WriteAllText($temp,$prefix+$suffix,$Utf8NoBom)
$tokens=$null;$errors=$null
[void][Management.Automation.Language.Parser]::ParseFile($temp,[ref]$tokens,[ref]$errors)
if(@($errors).Count){Fail('Prepared closure staging script parser failure: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}

$exe=Join-Path $PSHOME 'powershell.exe'
& $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $temp -RepositoryRoot $RepositoryRoot
if($LASTEXITCODE-ne0){Fail('Prepared closure staging script failed with exit '+$LASTEXITCODE)}
