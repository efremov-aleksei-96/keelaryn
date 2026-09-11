[CmdletBinding()]
param(
    [string]$RepositoryRoot=(Join-Path $PSScriptRoot '..')
)

# Permanent regression coverage for the post-freeze Manager 4.17.3 per-instance
# state publication defect. Inherits all earlier 4.17.2/4.17.3 review regressions.
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$runtimePath=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1'
$legacyRegression=Join-Path $RepositoryRoot 'tools\Invoke-Manager4173ReviewRegression.ps1'
foreach($path in @($runtimePath,$legacyRegression)){
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw('Required regression input missing: '+$path)}
}

function Assert([bool]$Condition,[string]$Message){if(-not$Condition){throw $Message}}
function Get-FunctionText([string]$Path,[string]$Name){
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors)
    if(@($errors).Count-ne0){throw('Parser failed for '+$Path+': '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
    $rows=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$Name},$true))
    if($rows.Count-ne1){throw('Expected exactly one function '+$Name+' in '+$Path+'; actual='+$rows.Count)}
    return [string]$rows[0].Extent.Text
}

$powershell=Join-Path $PSHOME 'powershell.exe'
& $powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $legacyRegression -RepositoryRoot $RepositoryRoot
if($LASTEXITCODE-ne0){throw('Manager 4.17.3 regression suite failed with ExitCode '+$LASTEXITCODE)}
Write-Host '  PASS inherited Manager 4.17.3 review regressions'

Invoke-Expression (Get-FunctionText $runtimePath 'Move-DirectoryFailIfDestinationExists')
Invoke-Expression (Get-FunctionText $runtimePath 'New-RegisteredInstanceStateFromVault')

$temp=Join-Path ([IO.Path]::GetTempPath()) ('keelaryn_4174_review_regression_'+[guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($temp)
try{
    # Behavioral race regression: destination appears only after the staged CURRENT
    # has been fully validated. Publication must fail closed and must not nest staging.
    $script:InstancesStateRoot=Join-Path $temp 'instances'
    [void][IO.Directory]::CreateDirectory($script:InstancesStateRoot)
    $script:ExpectedId='44444444-4444-4444-4444-444444444444'
    $script:RaceRoot=Join-Path $script:InstancesStateRoot $script:ExpectedId
    $script:RaceInjected=$false

    function Get-InstanceStatePaths([string]$InstanceId){
        $root=Join-Path $script:InstancesStateRoot $InstanceId
        return [pscustomobject]@{
            Root=$root
            Inbox=Join-Path $root 'inbox'
            Current=Join-Path $root 'baseline\Keelaryn__Hub_CURRENT.zip'
            Checkpoints=Join-Path $root 'history\checkpoints'
            Rollback=Join-Path $root 'history\rollback'
        }
    }
    function Write-PortableHubZip([string]$SourceRoot,[string]$ZipPath,[string]$ZipRootName){
        [void][IO.Directory]::CreateDirectory((Split-Path -Parent $ZipPath))
        [IO.File]::WriteAllText($ZipPath,'synthetic-current',(New-Object Text.UTF8Encoding($false)))
    }
    function Open-HubZipInspectionSession([string]$ZipPath){return [pscustomobject]@{Path=$ZipPath}}
    function Read-ZipState([string]$ZipPath,$Session){return [pscustomobject]@{InstanceId=$script:ExpectedId}}
    function Read-ZipArtifactManifest([string]$ZipPath,$Session){return [pscustomobject]@{InstanceId=$script:ExpectedId}}
    function Get-PortableVaultAnalysis([string]$VaultPath){return [pscustomobject]@{ContentHash='content';PayloadHash='payload'}}
    function Get-ZipHashPair([string]$ZipPath,$Session){
        if(-not$script:RaceInjected){
            [void][IO.Directory]::CreateDirectory($script:RaceRoot)
            [IO.File]::WriteAllText((Join-Path $script:RaceRoot 'foreign.txt'),'foreign',(New-Object Text.UTF8Encoding($false)))
            $script:RaceInjected=$true
        }
        return [pscustomobject]@{ContentHash='content';PayloadHash='payload'}
    }
    function Close-HubZipInspectionSession($Session){}

    $vault=Join-Path $temp 'existing-hub'
    [void][IO.Directory]::CreateDirectory($vault)
    $blocked=$false
    try{$null=New-RegisteredInstanceStateFromVault $script:ExpectedId $vault}catch{$blocked=$true}
    Assert $blocked 'Per-instance state publication did not reject a destination created at the commit boundary.'
    Assert $script:RaceInjected 'Race regression did not inject the destination at the intended boundary.'
    Assert (Test-Path -LiteralPath (Join-Path $script:RaceRoot 'foreign.txt') -PathType Leaf) 'Fail-closed state publication modified the foreign destination.'
    $nested=@(Get-ChildItem -LiteralPath $script:RaceRoot -Directory -Force -ErrorAction SilentlyContinue)
    Assert ($nested.Count-eq0) 'Fail-closed state publication nested staging below the occupied destination.'
    Write-Host '  PASS per-instance state publication refuses commit-boundary destination races'

    $stateText=Get-FunctionText $runtimePath 'New-RegisteredInstanceStateFromVault'
    Assert ($stateText.Contains('Move-DirectoryFailIfDestinationExists $staging $paths.Root')) 'Per-instance state publication does not use fail-if-exists directory publication.'
    Assert (-not$stateText.Contains('Move-Item -LiteralPath $staging -Destination $paths.Root')) 'Per-instance state publication still uses container-nesting Move-Item semantics.'

    # Source transaction contract: published Hub/state must be freshly validated before
    # instances.json becomes authoritative, not only after the commit.
    foreach($name in @('Invoke-RegisterExistingInstance','Invoke-GenesisRegisteredInstance')){
        $text=Get-FunctionText $runtimePath $name
        $validate=$text.IndexOf('Assert-RegisteredInstanceBaseline $candidateRow',[StringComparison]::Ordinal)
        $commit=$text.IndexOf('Write-ManagerInstanceRegistry',[StringComparison]::Ordinal)
        Assert ($validate-ge0) ($name+' lacks fresh published-baseline validation before registry commit.')
        Assert ($commit-gt$validate) ($name+' validates the published baseline only after registry commit.')
    }
    Write-Host '  PASS multi-Hub registry commits revalidate published instance state at the commit boundary'

    $genesisText=Get-FunctionText $runtimePath 'Invoke-GenesisRegisteredInstance'
    Assert ($genesisText.Contains('Registered Genesis durable registry commit succeeded')) 'Registered Genesis does not distinguish durable commit from post-commit failure.'
    Write-Host '  PASS registered Genesis reports durable-commit/post-commit failure distinctly'

    Write-Host 'MANAGER 4.17.4 REVIEW REGRESSION: PASS' -ForegroundColor Green
}finally{
    if(Test-Path -LiteralPath $temp){Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue}
}
