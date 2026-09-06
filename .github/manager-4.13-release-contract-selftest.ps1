[CmdletBinding()]
param([string]$RepositoryRoot=(Split-Path $PSScriptRoot -Parent))
$ErrorActionPreference='Stop'
$RepositoryRoot=[System.IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
function Fail([string]$Message){throw $Message}
function Test-UpdateBinding([bool]$FullGate,[AllowNull()][string]$Expected,[string]$Actual){
    $actualNorm=([string]$Actual).Trim().ToLowerInvariant()
    $expectedNorm=([string]$Expected).Trim().ToLowerInvariant()
    if($actualNorm-notmatch'^[0-9a-f]{64}$'){return $false}
    if($FullGate){return ($expectedNorm-match'^[0-9a-f]{64}$'-and$actualNorm-ceq$expectedNorm)}
    return [string]::IsNullOrWhiteSpace($expectedNorm)
}

$workflowPath=Join-Path $RepositoryRoot '.github\workflows\public-release.yml'
$workflow=[System.IO.File]::ReadAllText($workflowPath,[System.Text.Encoding]::UTF8)
foreach($token in @(
    'permissions:',
    '  contents: read',
    'Verify UPDATE identity against production qualification',
    'production_validation.tested_update_sha256',
    "if: github.event_name == 'push' && github.ref == 'refs/heads/main'",
    'contents: write',
    'Existing release assets are byte-identical; leaving release unchanged.'
)){
    if(-not$workflow.Contains($token)){Fail('Public release workflow contract token missing: '+$token)}
}
if(([regex]::Matches($workflow,'(?m)^\s*contents:\s*write\s*$')).Count-ne1){Fail('Public release workflow must contain exactly one contents: write permission elevation.')}

$prov=Get-Content -LiteralPath (Join-Path $RepositoryRoot 'PUBLIC_PROVENANCE.json') -Raw -Encoding UTF8|ConvertFrom-Json
if($null-eq$prov.production_validation.PSObject.Properties['tested_update_sha256']){Fail('Provenance tested_update_sha256 field missing.')}
if([bool]$prov.production_validation.full_gate_pass){Fail('Development candidate unexpectedly claims Full Gate qualification.')}
if(-not[string]::IsNullOrWhiteSpace([string]$prov.production_validation.tested_update_sha256)){Fail('Unqualified development candidate retained tested UPDATE identity.')}

$temp=Join-Path ([System.IO.Path]::GetTempPath()) ('Keelaryn_release_identity_'+[guid]::NewGuid().ToString('N'))
$manager=Join-Path $temp 'manager'
try{
    New-Item -ItemType Directory -Force -Path $temp|Out-Null
    Copy-Item -LiteralPath (Join-Path $RepositoryRoot 'manager') -Destination $manager -Recurse -Force
    powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $manager 'product\runtime\Keelaryn__Manager.ps1') -BuildRelease
    if($LASTEXITCODE-ne0){Fail('Disposable BuildRelease failed: ExitCode '+$LASTEXITCODE)}
    $install=Get-Content -LiteralPath (Join-Path $manager 'product\install\INSTALLATION.json') -Raw -Encoding UTF8|ConvertFrom-Json
    $version=[string]$install.manager_version
    $update=Join-Path $manager ('state\releases\Keelaryn__Manager_Update_v'+$version+'_Built.zip')
    if(-not(Test-Path -LiteralPath $update -PathType Leaf)){
        $update=Join-Path $manager ('_releases\Keelaryn__Manager_Update_v'+$version+'_Built.zip')
    }
    if(-not(Test-Path -LiteralPath $update -PathType Leaf)){Fail('Disposable BuildRelease UPDATE missing.')}
    $actual=(Get-FileHash -LiteralPath $update -Algorithm SHA256).Hash.ToLowerInvariant()
    if(-not(Test-UpdateBinding $false $null $actual)){Fail('Unqualified UPDATE binding policy failed.')}
    if(-not(Test-UpdateBinding $true $actual $actual)){Fail('Qualified exact UPDATE binding policy failed.')}
    $other=('0'*64);if($actual-ceq$other){$other=('f'*64)}
    if(Test-UpdateBinding $true $other $actual){Fail('Qualified mismatched UPDATE binding was incorrectly accepted.')}
    Write-Host ('Manager 4.13 release identity contract self-test PASS. candidate_update='+$actual) -ForegroundColor Green
    exit 0
}finally{
    if(Test-Path -LiteralPath $temp){Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue}
}
