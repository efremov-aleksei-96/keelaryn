[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$Utf8NoBom=New-Object Text.UTF8Encoding($false)

function Fail([string]$Message){throw $Message}
function Write-Utf8NoBom([string]$Path,[string]$Text){[IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)}

$runtimePath=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1'
$manifestPath=Join-Path $RepositoryRoot 'PUBLIC_FILE_MANIFEST.json'
$provenancePath=Join-Path $RepositoryRoot 'PUBLIC_PROVENANCE.json'
$manifestTool=Join-Path $RepositoryRoot 'tools\Build-PublicFileManifest.ps1'
foreach($path in @($runtimePath,$provenancePath,$manifestTool)){
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){Fail('Required materialization input missing: '+$path)}
}

$runtime=[IO.File]::ReadAllText($runtimePath,[Text.Encoding]::UTF8)
if(-not$runtime.Contains('$ManagerVersion = "4.17.9"')){Fail 'Runtime is not materialized as Manager 4.17.9.'}

& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $manifestTool -RepositoryRoot $RepositoryRoot -Write
if($LASTEXITCODE-ne0){Fail 'Build-PublicFileManifest -Write failed.'}
if(-not(Test-Path -LiteralPath $manifestPath -PathType Leaf)){Fail 'PUBLIC_FILE_MANIFEST.json was not generated.'}
$manifest=Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$manifest.manager.version-cne'4.17.9'){Fail('Generated public manifest version mismatch: '+[string]$manifest.manager.version)}
$installationHash=([string]$manifest.manager.installation_sha256).Trim().ToLowerInvariant()
$managedHash=([string]$manifest.manager.gate_managed_content_sha256).Trim().ToLowerInvariant()
if($installationHash-notmatch'^[0-9a-f]{64}$'-or$managedHash-notmatch'^[0-9a-f]{64}$'){Fail 'Generated public manifest hashes are invalid.'}

$prov=Get-Content -LiteralPath $provenancePath -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$prov.schema-cne'keelaryn.public-repository-provenance.v2'){Fail 'Unsupported PUBLIC_PROVENANCE schema.'}
$prov.source_manager_version='4.17.9'
$prov.source_gate_baseline_manager_version='4.17.8'
$prov.source_manager_installation_sha256=$installationHash
$prov.source_manager_gate_managed_content_sha256=$managedHash
$prov.production_validation.full_gate_pass=$false
$prov.production_validation.gate_revision=$null
$prov.production_validation.framework_revision=24
$prov.production_validation.tested_update_sha256=$null
$prov.production_validation.production_doctor_pass=$false
$prov.production_validation.production_ux_smoke_pass=$false
$prov.production_validation.production_managed_content_prefix=$null
$prov.public_candidate_revision=13
$prov.gate_framework.revision=24
$prov.gate_framework.windows_qualified=$true
$prov.gate_framework.frozen_for_manager_candidate=$false
Write-Utf8NoBom $provenancePath (($prov|ConvertTo-Json -Depth 30).Replace("`r`n","`n")+"`n")

# Re-run the manifest after provenance mutation because PUBLIC_PROVENANCE is repository metadata
# outside the Manager managed set, while this verifies the Manager identity remains unchanged.
$manifest2=Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$manifest2.manager.installation_sha256-cne$installationHash-or[string]$manifest2.manager.gate_managed_content_sha256-cne$managedHash){Fail 'Manager manifest identity changed unexpectedly during provenance finalization.'}

Write-Host ('Manager 4.17.9 metadata finalization: PASS installation='+$installationHash.Substring(0,12)+' managed='+$managedHash.Substring(0,12)) -ForegroundColor Green
