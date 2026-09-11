[CmdletBinding()]
param(
    [string]$RepositoryRoot=(Join-Path $PSScriptRoot '..')
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$workflowRelative='.github/workflows/manager-4.17.2-p1-ambiguity-repair.yml'
$scriptRelative='tools/Apply-Manager4172AmbiguousCommitFix.ps1'
$runtimeRelative='manager/product/runtime/Keelaryn__Manager.ps1'
$regressionRelative='tools/Invoke-Manager4172ReviewRegression.ps1'
$runtimePath=Join-Path $RepositoryRoot $runtimeRelative.Replace('/','\')
$regressionPath=Join-Path $RepositoryRoot $regressionRelative.Replace('/','\')
$utf8=New-Object Text.UTF8Encoding($false)

function Assert-ExactBlob([string]$Path,[string]$Expected,[string]$Label){
    $actual=(git -C $RepositoryRoot hash-object $Path).Trim()
    if($LASTEXITCODE-ne0-or$actual-cne$Expected){throw("$Label blob drifted before repair: $actual")}
}
function Convert-Newlines([string]$Text,[string]$Newline){return [regex]::Replace($Text,"\r?\n",$Newline)}
function Replace-ExactlyOnce([string]$Text,[string]$Old,[string]$New,[string]$Label){
    $first=$Text.IndexOf($Old,[StringComparison]::Ordinal)
    if($first-lt0){throw("Patch anchor missing: $Label")}
    $second=$Text.IndexOf($Old,$first+$Old.Length,[StringComparison]::Ordinal)
    if($second-ge0){throw("Patch anchor is not unique: $Label")}
    return $Text.Substring(0,$first)+$New+$Text.Substring($first+$Old.Length)
}

$branch=(git -C $RepositoryRoot rev-parse --abbrev-ref HEAD).Trim()
if($branch-cne'dev/manager-4.17.2'){throw("Repair must run on dev/manager-4.17.2; actual=$branch")}
git -C $RepositoryRoot merge-base --is-ancestor 89f46ec0bab7dfad53562fe061f767b229d7b190 HEAD
if($LASTEXITCODE-ne0){throw 'Expected reviewed development head is not an ancestor of repair HEAD.'}
Assert-ExactBlob $runtimePath '42a82bde2059076e535c912b206211203eef846f' 'Runtime'
Assert-ExactBlob $regressionPath '9f94a60955c4521a82114b2a7caa76b16a0ad43d' 'Regression'

$runtime=[IO.File]::ReadAllText($runtimePath)
$rnl=if($runtime.Contains("`r`n")){"`r`n"}else{"`n"}
$old=Convert-Newlines @'
    $paths=$null
    $registryCommitted=$false
    try{
'@ $rnl
$new=Convert-Newlines @'
    $paths=$null
    $registryCommitted=$false
    $registryWriteStarted=$false
    try{
'@ $rnl
$runtime=Replace-ExactlyOnce $runtime $old $new 'registration write-state declaration'

$old='        Write-ManagerInstanceRegistry ([ordered]@{schema=''keelaryn.manager.instances.v1'';registry_revision=([int]$registry.registry_revision+1);instances=@($newRows)})'
$new='        $registryWriteStarted=$true'+$rnl+$old
$runtime=Replace-ExactlyOnce $runtime $old $new 'registration write-attempt boundary'

$old=Convert-Newlines @'
    }catch{
        $primary=$_.Exception.Message
        if(-not$registryCommitted){
            try{
                $after=Get-ManagerInstanceRegistry
                $durable=@($after.instances|Where-Object{
                    [string]$_.instance_id-eq$id -and
                    (Get-KeelarynNormalizedPathKey ([string]$_.vault_path))-eq$pathKey -and
                    [string]$_.name-ceq$display
                })
                if($durable.Count-eq1){$registryCommitted=$true}
            }catch{}
        }
        if(-not$registryCommitted -and $paths -and (Test-Path -LiteralPath $paths.Root)){Remove-Item -LiteralPath $paths.Root -Recurse -Force -ErrorAction SilentlyContinue}
        if($registryCommitted){throw('Hub registration durable commit succeeded, but subsequent operation failed; registered state was preserved. '+$primary)}
        throw
    }
'@ $rnl
$new=Convert-Newlines @'
    }catch{
        $primary=$_.Exception.Message
        $verificationFailure=$null
        $registryNotCommitted=$false
        if(-not$registryCommitted){
            if(-not$registryWriteStarted){
                $registryNotCommitted=$true
            }else{
                try{
                    $after=Get-ManagerInstanceRegistry
                    $durable=@($after.instances|Where-Object{
                        [string]$_.instance_id-eq$id -and
                        (Get-KeelarynNormalizedPathKey ([string]$_.vault_path))-eq$pathKey -and
                        [string]$_.name-ceq$display
                    })
                    $identityOrPath=@($after.instances|Where-Object{
                        [string]$_.instance_id-eq$id -or
                        (Get-KeelarynNormalizedPathKey ([string]$_.vault_path))-eq$pathKey
                    })
                    if($durable.Count-eq1 -and $identityOrPath.Count-eq1){
                        $registryCommitted=$true
                    }elseif($durable.Count-eq0 -and $identityOrPath.Count-eq0){
                        $registryNotCommitted=$true
                    }else{
                        $verificationFailure=('Registry verification returned ambiguous matching rows: exact={0}; identity_or_path={1}.' -f $durable.Count,$identityOrPath.Count)
                    }
                }catch{
                    $verificationFailure=$_.Exception.Message
                }
            }
        }
        if($registryNotCommitted -and $paths -and (Test-Path -LiteralPath $paths.Root)){Remove-Item -LiteralPath $paths.Root -Recurse -Force -ErrorAction SilentlyContinue}
        if($registryCommitted){throw('Hub registration durable commit succeeded, but subsequent operation failed; registered state was preserved. '+$primary)}
        if($registryWriteStarted -and -not$registryNotCommitted){
            if([string]::IsNullOrWhiteSpace([string]$verificationFailure)){$verificationFailure='Registry verification could not establish whether the write committed.'}
            throw('Hub registration registry commit status is ambiguous after a write failure; registered state was preserved. Primary failure: '+$primary+' Commit verification failure: '+$verificationFailure)
        }
        throw
    }
'@ $rnl
$runtime=Replace-ExactlyOnce $runtime $old $new 'registration catch transaction classification'
[IO.File]::WriteAllText($runtimePath,$runtime,$utf8)

$regression=[IO.File]::ReadAllText($regressionPath)
$gnl=if($regression.Contains("`r`n")){"`r`n"}else{"`n"}
$regression=Replace-ExactlyOnce $regression '# Permanent regression coverage for the three product defects found during PR #48 final review.' '# Permanent regression coverage for the PR #48 review defects plus the pre-freeze ambiguous-commit edge case.' 'regression scope comment'

$old=Convert-Newlines @'
    $script:ThrowInsideWrite=$false
    $script:RegressionMetadataMode='registration'
'@ $gnl
$new=Convert-Newlines @'
    $script:ThrowInsideWrite=$false
    $script:ThrowRegistryReadAfterWrite=$false
    $script:RegistryWriteAttempted=$false
    $script:RegressionMetadataMode='registration'
'@ $gnl
$regression=Replace-ExactlyOnce $regression $old $new 'regression fixture flags'

$old='    function Get-ManagerInstanceRegistry { return $script:RegressionRegistry }'
$new=Convert-Newlines @'
    function Get-ManagerInstanceRegistry {
        if($script:ThrowRegistryReadAfterWrite -and $script:RegistryWriteAttempted){throw 'simulated registry reread failure after write attempt'}
        return $script:RegressionRegistry
    }
'@ $gnl
$regression=Replace-ExactlyOnce $regression $old $new 'regression registry reread stub'

$old=Convert-Newlines @'
        $script:RegressionRegistry=[pscustomobject]@{
            schema='keelaryn.manager.instances.v1'
            registry_revision=[int]$Registry.registry_revision
            instances=@($Registry.instances)
        }
        if($script:ThrowInsideWrite){throw 'simulated post-publication registry verification failure'}
'@ $gnl
$new=Convert-Newlines @'
        $script:RegressionRegistry=[pscustomobject]@{
            schema='keelaryn.manager.instances.v1'
            registry_revision=[int]$Registry.registry_revision
            instances=@($Registry.instances)
        }
        $script:RegistryWriteAttempted=$true
        if($script:ThrowInsideWrite){throw 'simulated post-publication registry verification failure'}
'@ $gnl
$regression=Replace-ExactlyOnce $regression $old $new 'regression writer commit marker'

$old='    function Reset-RegistrationFixture([string]$CaseName,[bool]$ThrowInWrite){'
$new='    function Reset-RegistrationFixture([string]$CaseName,[bool]$ThrowInWrite,[bool]$ThrowOnVerifyRead=$false){'
$regression=Replace-ExactlyOnce $regression $old $new 'regression reset signature'

$old=Convert-Newlines @'
        $script:ThrowInsideWrite=$ThrowInWrite
        $script:RegressionMetadataMode='registration'
'@ $gnl
$new=Convert-Newlines @'
        $script:ThrowInsideWrite=$ThrowInWrite
        $script:ThrowRegistryReadAfterWrite=$ThrowOnVerifyRead
        $script:RegistryWriteAttempted=$false
        $script:RegressionMetadataMode='registration'
'@ $gnl
$regression=Replace-ExactlyOnce $regression $old $new 'regression reset flags'

$old=Convert-Newlines @'
    Write-Host '  PASS committed registration state survives post-commit failures'

    $script:InstanceRegistryActive=$true
'@ $gnl
$new=Convert-Newlines @'
    Write-Host '  PASS committed registration state survives post-commit failures'

    $betaPath=Reset-RegistrationFixture 'ambiguous-postcommit-reread' $true $true
    $message=$null
    try{$null=Invoke-RegisterExistingInstance $betaPath 'Beta' $true;throw 'Expected ambiguous post-commit reread case to throw.'}catch{$message=$_.Exception.Message}
    Assert ($message.Contains('registry commit status is ambiguous')) ('ambiguous-postcommit-reread: ambiguity diagnostic missing: '+$message)
    Assert ($message.Contains('registered state was preserved')) ('ambiguous-postcommit-reread: preservation diagnostic missing: '+$message)
    Assert (Test-Path -LiteralPath $script:RegressionStateRoot -PathType Container) 'ambiguous-postcommit-reread: state was deleted while commit status was unknown.'
    Assert (Test-Path -LiteralPath (Join-Path $script:RegressionStateRoot 'baseline.marker') -PathType Leaf) 'ambiguous-postcommit-reread: state marker was deleted while commit status was unknown.'
    $betaRows=@($script:RegressionRegistry.instances|Where-Object{[string]$_.instance_id-eq$betaId})
    Assert ($betaRows.Count-eq1) 'ambiguous-postcommit-reread: simulated durable registry row was lost.'
    Write-Host '  PASS ambiguous registry commit verification preserves per-instance state'

    $script:ThrowRegistryReadAfterWrite=$false
    $script:RegistryWriteAttempted=$false
    $script:InstanceRegistryActive=$true
'@ $gnl
$regression=Replace-ExactlyOnce $regression $old $new 'ambiguous commit regression case'
[IO.File]::WriteAllText($regressionPath,$regression,$utf8)

$tokens=$null;$errors=$null
[void][Management.Automation.Language.Parser]::ParseFile($runtimePath,[ref]$tokens,[ref]$errors)
if(@($errors).Count-ne0){throw('Runtime parser failed: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
$tokens=$null;$errors=$null
[void][Management.Automation.Language.Parser]::ParseFile($regressionPath,[ref]$tokens,[ref]$errors)
if(@($errors).Count-ne0){throw('Regression parser failed: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}

powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $regressionPath -RepositoryRoot $RepositoryRoot
if($LASTEXITCODE-ne0){throw("Targeted regression failed: exit=$LASTEXITCODE")}

$manifestTool=Join-Path $RepositoryRoot 'tools\Build-PublicFileManifest.ps1'
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $manifestTool -RepositoryRoot $RepositoryRoot -Write
if($LASTEXITCODE-ne0){throw("Public manifest refresh failed: exit=$LASTEXITCODE")}
$manifest=(Get-Content -LiteralPath (Join-Path $RepositoryRoot 'PUBLIC_FILE_MANIFEST.json') -Raw -Encoding UTF8)|ConvertFrom-Json
$digest=[string]$manifest.manager.gate_managed_content_sha256
if($digest-notmatch'^[0-9a-f]{64}$'){throw 'Refreshed managed-set digest is invalid.'}

$provenancePath=Join-Path $RepositoryRoot 'PUBLIC_PROVENANCE.json'
$provenance=[IO.File]::ReadAllText($provenancePath)
$provenanceObject=$provenance|ConvertFrom-Json
if([string]$provenanceObject.source_manager_gate_managed_content_sha256-cne'8dc62699f135f0a624317bb65bec6cb0563224f0a0485e139d0b4171a10f9517'){throw 'Unexpected pre-repair provenance managed digest.'}
if([int]$provenanceObject.public_candidate_revision-ne2){throw 'Unexpected pre-repair public candidate revision.'}
$provenance=[regex]::Replace($provenance,'("source_manager_gate_managed_content_sha256"\s*:\s*")[0-9a-f]{64}("\s*,)',[Text.RegularExpressions.MatchEvaluator]{param($m)$m.Groups[1].Value+$digest+$m.Groups[2].Value},1)
$provenance=[regex]::Replace($provenance,'("public_candidate_revision"\s*:\s*)2(\s*,)',[Text.RegularExpressions.MatchEvaluator]{param($m)$m.Groups[1].Value+'3'+$m.Groups[2].Value},1)
[IO.File]::WriteAllText($provenancePath,$provenance,$utf8)

powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $manifestTool -RepositoryRoot $RepositoryRoot -Check
if($LASTEXITCODE-ne0){throw("Public manifest check failed: exit=$LASTEXITCODE")}

git -C $RepositoryRoot diff --check
if($LASTEXITCODE-ne0){throw 'git diff --check failed.'}

$workflowPath=Join-Path $RepositoryRoot $workflowRelative.Replace('/','\')
$selfPath=Join-Path $RepositoryRoot $scriptRelative.Replace('/','\')
if(-not(Test-Path -LiteralPath $workflowPath -PathType Leaf)){throw 'One-shot workflow is missing before cleanup.'}
if(-not(Test-Path -LiteralPath $selfPath -PathType Leaf)){throw 'One-shot repair script is missing before cleanup.'}
git -C $RepositoryRoot rm -- $workflowRelative $scriptRelative
if($LASTEXITCODE-ne0){throw 'Failed to stage one-shot repair tooling removal.'}

$status=@(git -C $RepositoryRoot status --porcelain=v1)
$allowed=@(
    '.github/workflows/manager-4.17.2-p1-ambiguity-repair.yml',
    'PUBLIC_FILE_MANIFEST.json',
    'PUBLIC_PROVENANCE.json',
    'manager/product/runtime/Keelaryn__Manager.ps1',
    'tools/Apply-Manager4172AmbiguousCommitFix.ps1',
    'tools/Invoke-Manager4172ReviewRegression.ps1'
)
$statusPaths=@($status|ForEach-Object{if($_.Length-lt4){throw('Malformed git status row: '+$_)};$_.Substring(3)})
foreach($required in $allowed){if($statusPaths-notcontains$required){throw('Expected final change missing: '+$required)}}
foreach($actual in $statusPaths){if($allowed-notcontains$actual){throw('Unexpected final change: '+$actual)}}
if($statusPaths.Count-ne$allowed.Count){throw('Unexpected final change count: '+$statusPaths.Count)}

git -C $RepositoryRoot config user.name 'keelaryn-development-bot'
git -C $RepositoryRoot config user.email '41898282+github-actions[bot]@users.noreply.github.com'
git -C $RepositoryRoot add -- PUBLIC_FILE_MANIFEST.json PUBLIC_PROVENANCE.json $runtimeRelative $regressionRelative
git -C $RepositoryRoot commit -m 'Manager 4.17.2: fail closed on ambiguous registry commit'
if($LASTEXITCODE-ne0){throw 'Repair commit failed.'}
git -C $RepositoryRoot push origin 'HEAD:refs/heads/dev/manager-4.17.2'
if($LASTEXITCODE-ne0){throw 'Repair push failed.'}
Write-Host 'MANAGER 4.17.2 P1 AMBIGUOUS-COMMIT REPAIR: PUSHED' -ForegroundColor Green
