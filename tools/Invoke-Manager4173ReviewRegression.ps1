[CmdletBinding()]
param(
    [string]$RepositoryRoot=(Join-Path $PSScriptRoot '..')
)

# Permanent regression coverage for the two post-freeze Manager 4.17.2 review defects.
# The existing 4.17.2 regression suite remains authoritative for the earlier four fixes.
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$runtimePath=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1'
$menuPath=Join-Path $RepositoryRoot 'manager\product\tools\KeelarynMenu.ps1'
$legacyRegression=Join-Path $RepositoryRoot 'tools\Invoke-Manager4172ReviewRegression.ps1'
foreach($path in @($runtimePath,$menuPath,$legacyRegression)){
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
function Get-Sha256([string]$Path){return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}

# Preserve all prior 4.17.2 regression coverage.
$powershell=Join-Path $PSHOME 'powershell.exe'
& $powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $legacyRegression -RepositoryRoot $RepositoryRoot
if($LASTEXITCODE-ne0){throw('Manager 4.17.2 regression suite failed with ExitCode '+$LASTEXITCODE)}
Write-Host '  PASS inherited Manager 4.17.2 review regressions'

# Import only the new helpers/functions under test. Dependencies are controlled stubs.
Invoke-Expression (Get-FunctionText $runtimePath 'Move-DirectoryFailIfDestinationExists')
Invoke-Expression (Get-FunctionText $menuPath 'Ensure-ChatGPTExchangeLayout')
Invoke-Expression (Get-FunctionText $menuPath 'Get-CurrentHubTransportPath')
Invoke-Expression (Get-FunctionText $menuPath 'Copy-CurrentForChatGPT')

$temp=Join-Path ([IO.Path]::GetTempPath()) ('keelaryn_4173_review_regression_'+[guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($temp)
try{
    # Regression A: source and destination must remain bound to one captured instance context.
    $ExchangeParent=Join-Path $temp 'exchange'
    [void][IO.Directory]::CreateDirectory($ExchangeParent)
    $script:ResolverCalls=0
    function Get-RequiredFrontendInstanceContext {
        $script:ResolverCalls++
        throw 'Regression resolver must not be called when an explicit instance context was supplied.'
    }
    function Ensure-DirectorySafe([string]$Directory,[string]$Purpose){
        if(-not(Test-Path -LiteralPath $Directory)){[void][IO.Directory]::CreateDirectory($Directory)}
        $item=Get-Item -LiteralPath $Directory -Force -ErrorAction Stop
        if(-not$item.PSIsContainer-or($item.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Unsafe directory in regression: '+$Purpose)}
    }
    function Get-ChatGPTExchangeDirectoryNames {return @('workspace-input','workspace-checkouts','chat-returns','chat-manager-input','chat-manager-results','development')}
    function Get-FileSha256Hex([string]$FilePath){return Get-Sha256 $FilePath}
    function Write-UiHost {param([object]$Object,[object]$ForegroundColor) }
    function Set-ActionSemantic {param([string]$Status) }

    $aId='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
    $aRoot=Join-Path $temp 'instance-a'
    $aCurrent=Join-Path $aRoot 'baseline\Keelaryn__Hub_CURRENT.zip'
    $aExchange=Join-Path $ExchangeParent ('instances\'+$aId+'\chatgpt')
    [void][IO.Directory]::CreateDirectory((Split-Path -Parent $aCurrent))
    [IO.File]::WriteAllText($aCurrent,'instance-a-current',(New-Object Text.UTF8Encoding($false)))
    $ctxA=[pscustomobject]@{
        RegistryActive=$true;InstanceId=$aId;Name='A';HubPath=(Join-Path $temp 'hub-a')
        HubInbox=(Join-Path $aRoot 'inbox');CurrentZip=$aCurrent;ExchangeRoot=$aExchange
    }
    $rc=Copy-CurrentForChatGPT $ctxA 'workspace-input'
    Assert ($rc-eq0) 'Captured-context CURRENT preparation did not succeed.'
    Assert ($script:ResolverCalls-eq0) ('Captured-context preparation re-resolved active instance '+$script:ResolverCalls+' time(s).')
    $prepared=Join-Path $aExchange 'workspace-input\Keelaryn__Hub_CURRENT.zip'
    Assert (Test-Path -LiteralPath $prepared -PathType Leaf) 'Captured-context preparation did not write to instance A exchange.'
    Assert ((Get-Sha256 $prepared)-ceq(Get-Sha256 $aCurrent)) 'Prepared CURRENT bytes do not match captured instance A.'
    Write-Host '  PASS ChatGPT CURRENT source/destination stay on one captured instance context'

    # Regression B: directory publication must fail if the destination is occupied at commit time.
    $src1=Join-Path $temp 'publish-source-1'
    $dst1=Join-Path $temp 'publish-destination-1'
    [void][IO.Directory]::CreateDirectory($src1)
    [IO.File]::WriteAllText((Join-Path $src1 'marker.txt'),'published',(New-Object Text.UTF8Encoding($false)))
    Move-DirectoryFailIfDestinationExists $src1 $dst1
    Assert (-not(Test-Path -LiteralPath $src1)) 'Fail-if-exists directory move left the successful source behind.'
    Assert (Test-Path -LiteralPath (Join-Path $dst1 'marker.txt') -PathType Leaf) 'Fail-if-exists directory move did not publish exact source directory.'

    $src2=Join-Path $temp 'publish-source-2'
    $dst2=Join-Path $temp 'publish-destination-2'
    [void][IO.Directory]::CreateDirectory($src2)
    [void][IO.Directory]::CreateDirectory($dst2)
    [IO.File]::WriteAllText((Join-Path $src2 'source.txt'),'source',(New-Object Text.UTF8Encoding($false)))
    [IO.File]::WriteAllText((Join-Path $dst2 'foreign.txt'),'foreign',(New-Object Text.UTF8Encoding($false)))
    $blocked=$false
    try{Move-DirectoryFailIfDestinationExists $src2 $dst2}catch{$blocked=$true}
    Assert $blocked 'Occupied publication destination was not rejected.'
    Assert (Test-Path -LiteralPath (Join-Path $src2 'source.txt') -PathType Leaf) 'Rejected publication consumed its staged source.'
    Assert (Test-Path -LiteralPath (Join-Path $dst2 'foreign.txt') -PathType Leaf) 'Rejected publication modified the pre-existing destination.'
    Assert (-not(Test-Path -LiteralPath (Join-Path $dst2 (Split-Path $src2 -Leaf)))) 'Rejected publication nested the staged source below the occupied destination.'

    $genesisText=Get-FunctionText $runtimePath 'Invoke-GenesisRegisteredInstance'
    Assert ($genesisText.Contains('Move-DirectoryFailIfDestinationExists $Vault $target')) 'Registered Genesis does not use fail-if-exists publication for the Hub vault.'
    Assert ($genesisText.Contains('Move-DirectoryFailIfDestinationExists $txState $paths.Root')) 'Registered Genesis does not use fail-if-exists publication for instance state.'
    Assert (-not$genesisText.Contains('Move-Item -LiteralPath $Vault -Destination $target')) 'Registered Genesis still uses container-nesting Move-Item semantics for Hub publication.'
    Write-Host '  PASS registered Genesis publication refuses occupied destinations'

    # Source contract: the session actions capture once and pass that context through.
    $invokeAction=Get-FunctionText $menuPath 'Invoke-Action'
    Assert ($invokeAction.Contains("Copy-CurrentForChatGPT `$ctx 'workspace-input'")) 'Workspace session does not pass its captured context through to CURRENT preparation.'
    Assert ($invokeAction.Contains("Copy-CurrentForChatGPT `$ctx 'chat-manager-input'")) 'Chat Manager session does not pass its captured context through to CURRENT preparation.'

    Write-Host 'MANAGER 4.17.3 REVIEW REGRESSION: PASS' -ForegroundColor Green
}finally{
    if(Test-Path -LiteralPath $temp){Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue}
}
