[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))

$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$RepositoryRoot=[System.IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')

function Fail([string]$Message){throw $Message}
function Read-Json([string]$Path){
    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){Fail('Required metadata file missing: '+$Path)}
    return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8)|ConvertFrom-Json
}
function Normalized-Optional([object]$Value){
    if($null-eq$Value){return ''}
    return ([string]$Value).Trim().ToLowerInvariant()
}

$installPath=Join-Path $RepositoryRoot 'manager\product\install\INSTALLATION.json'
$manifestPath=Join-Path $RepositoryRoot 'PUBLIC_FILE_MANIFEST.json'
$provenancePath=Join-Path $RepositoryRoot 'PUBLIC_PROVENANCE.json'
$frameworkRevisionPath=Join-Path $RepositoryRoot 'tests\framework\manager-gate\FRAMEWORK_REVISION.txt'
$statePath=Join-Path $RepositoryRoot 'MANAGER_DEVELOPMENT_STATE.json'

$install=Read-Json $installPath
$manifest=Read-Json $manifestPath
$provenance=Read-Json $provenancePath
$state=Read-Json $statePath

if([string]$install.schema-cne'keelaryn.manager.installation.v2'){Fail('Unsupported INSTALLATION schema: '+[string]$install.schema)}
if([string]$manifest.schema-cne'keelaryn.public-file-manifest.v2'){Fail('Unsupported PUBLIC_FILE_MANIFEST schema: '+[string]$manifest.schema)}
if([string]$provenance.schema-cne'keelaryn.public-repository-provenance.v2'){Fail('Unsupported PUBLIC_PROVENANCE schema: '+[string]$provenance.schema)}

$version=([string]$install.manager_version).Trim()
if($version-notmatch'^\d+\.\d+\.\d+$'){Fail('Invalid Manager version: '+$version)}
if([string]$manifest.manager.version-cne$version){Fail('PUBLIC_FILE_MANIFEST Manager version mismatch: manifest='+[string]$manifest.manager.version+' install='+$version)}
if([string]$provenance.source_manager_version-cne$version){Fail('PUBLIC_PROVENANCE Manager version mismatch: provenance='+[string]$provenance.source_manager_version+' install='+$version)}

$manifestInstall=Normalized-Optional $manifest.manager.installation_sha256
$provenanceInstall=Normalized-Optional $provenance.source_manager_installation_sha256
if($manifestInstall-notmatch'^[0-9a-f]{64}$'){Fail 'PUBLIC_FILE_MANIFEST installation_sha256 is invalid.'}
if($provenanceInstall-cne$manifestInstall){Fail('PUBLIC_PROVENANCE installation identity mismatch: provenance='+$provenanceInstall+' manifest='+$manifestInstall)}

$manifestManaged=Normalized-Optional $manifest.manager.gate_managed_content_sha256
$provenanceManaged=Normalized-Optional $provenance.source_manager_gate_managed_content_sha256
if($manifestManaged-notmatch'^[0-9a-f]{64}$'){Fail 'PUBLIC_FILE_MANIFEST managed digest is invalid.'}
if($provenanceManaged-cne$manifestManaged){Fail('PUBLIC_PROVENANCE managed identity mismatch: provenance='+$provenanceManaged+' manifest='+$manifestManaged)}

if(-not(Test-Path -LiteralPath $frameworkRevisionPath -PathType Leaf)){Fail 'Gate Framework revision marker missing.'}
$frameworkRevision=0
$frameworkText=(Get-Content -LiteralPath $frameworkRevisionPath -Raw -Encoding UTF8).Trim()
if(-not[int]::TryParse($frameworkText,[ref]$frameworkRevision)-or$frameworkRevision-lt1){Fail('Invalid Gate Framework revision: '+$frameworkText)}
if([int]$manifest.gate_framework.revision-ne$frameworkRevision){Fail 'PUBLIC_FILE_MANIFEST Framework revision mismatch.'}
if([int]$provenance.gate_framework.revision-ne$frameworkRevision){Fail 'PUBLIC_PROVENANCE Framework revision mismatch.'}
if([string]$provenance.gate_framework.version-cne'2.0'){Fail 'PUBLIC_PROVENANCE Framework version mismatch.'}

$baselineVersion=([string]$provenance.source_gate_baseline_manager_version).Trim()
if($baselineVersion-notmatch'^\d+\.\d+\.\d+$'){Fail('Invalid PUBLIC_PROVENANCE baseline version: '+$baselineVersion)}

$successor=([string]$state.lineage.successor_manager_version).Trim()
$lifecycle=[string]$state.lifecycle_state
if($lifecycle-ceq'unqualified_development'-and$successor-ceq$version){
    $expectedBaseline=([string]$state.lineage.production_manager_version).Trim()
    if($baselineVersion-cne$expectedBaseline){Fail('PUBLIC_PROVENANCE baseline mismatch for active development line: provenance='+$baselineVersion+' production='+$expectedBaseline)}
    $stateMaterializationVersion=([string]$state.materialization.manager_version).Trim()
    if($stateMaterializationVersion-cne$version){Fail('MANAGER_DEVELOPMENT_STATE materialization version mismatch: state='+$stateMaterializationVersion+' install='+$version)}
    $stateInstall=Normalized-Optional $state.materialization.installation_sha256
    if($stateInstall-cne$manifestInstall){Fail('MANAGER_DEVELOPMENT_STATE installation identity mismatch: state='+$stateInstall+' manifest='+$manifestInstall)}
    $stateManaged=Normalized-Optional $state.materialization.managed_content_sha256
    if($stateManaged-cne$manifestManaged){Fail('MANAGER_DEVELOPMENT_STATE managed identity mismatch: state='+$stateManaged+' manifest='+$manifestManaged)}
    if([bool]$provenance.production_validation.full_gate_pass){Fail 'Unqualified development provenance must not claim Full Gate PASS.'}
    if(-not[string]::IsNullOrWhiteSpace((Normalized-Optional $provenance.production_validation.tested_update_sha256))){Fail 'Unqualified development provenance must not retain tested_update_sha256.'}
    if([bool]$provenance.production_validation.production_doctor_pass){Fail 'Unqualified development provenance must not claim production Doctor PASS.'}
    if([bool]$provenance.production_validation.production_ux_smoke_pass){Fail 'Unqualified development provenance must not claim production UX smoke PASS.'}
}

if([int]$provenance.public_candidate_revision-lt1){Fail 'PUBLIC_PROVENANCE public_candidate_revision must be >= 1.'}

$releaseInstructions=Join-Path $RepositoryRoot 'tools\Verify-ManagerReleaseInstructions.ps1'
if(-not(Test-Path -LiteralPath $releaseInstructions -PathType Leaf)){Fail 'Manager release-instruction identity verifier is missing.'}
$powershell=Join-Path $PSHOME 'powershell.exe'
& $powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $releaseInstructions -RepositoryRoot $RepositoryRoot
if($LASTEXITCODE-ne0){Fail('Manager release-instruction identity verifier failed with exit '+$LASTEXITCODE)}

Write-Host ('Public candidate metadata consistency: PASS. Manager '+$version+'; baseline='+$baselineVersion+'; framework=r'+$frameworkRevision) -ForegroundColor Green
Write-Host ('  installation='+$manifestInstall)
Write-Host ('  managed='+$manifestManaged)
