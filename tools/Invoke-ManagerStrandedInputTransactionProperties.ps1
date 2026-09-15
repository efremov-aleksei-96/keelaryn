[CmdletBinding()]
param(
    [string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'),
    [ValidateSet('Broken','Fixed')][string]$ExpectedState='Broken',
    [string]$OutputPath=''
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$Utf8NoBom=New-Object Text.UTF8Encoding($false)

function Fail([string]$Message){throw $Message}
function Write-Utf8([string]$Path,[string]$Text){
    $parent=Split-Path -Parent $Path
    if($parent-and-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
    [IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)
}
function Write-Json([string]$Path,$Object){Write-Utf8 $Path ((($Object|ConvertTo-Json -Depth 30).Replace("`r`n","`n"))+"`n")}
function Copy-ManagedManager([string]$SourceManager,[string]$DestinationManager){
    $install=Get-Content -LiteralPath (Join-Path $SourceManager 'product\install\INSTALLATION.json') -Raw -Encoding UTF8|ConvertFrom-Json
    if([string]$install.schema-cne'keelaryn.manager.installation.v2'){Fail 'Unsupported Manager installation schema.'}
    New-Item -ItemType Directory -Force -Path $DestinationManager|Out-Null
    foreach($raw in @($install.managed_files)){
        $rel=([string]$raw).Replace('/','\');$src=Join-Path $SourceManager $rel;$dst=Join-Path $DestinationManager $rel
        if(-not(Test-Path -LiteralPath $src -PathType Leaf)){Fail('Managed source missing: '+$rel)}
        $parent=Split-Path -Parent $dst
        if($parent-and-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
        Copy-Item -LiteralPath $src -Destination $dst -Force
    }
    return [string]$install.manager_version
}
function Invoke-Runtime([string]$Runtime,[string[]]$Arguments){
    if($null-eq$Arguments){$Arguments=@()}
    $exe=Join-Path $PSHOME 'powershell.exe';$old=$ErrorActionPreference
    try{
        $ErrorActionPreference='Continue'
        $output=@(& $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Runtime @Arguments 2>&1|ForEach-Object{[string]$_})
        $code=[int]$LASTEXITCODE
    }finally{$ErrorActionPreference=$old}
    return [pscustomobject]@{ExitCode=$code;Output=@($output);Text=[string]::Join("`n",@($output))}
}
function Invoke-Required([string]$Runtime,[string[]]$Arguments,[string]$Purpose){
    $r=Invoke-Runtime $Runtime $Arguments
    foreach($line in @($r.Output)){Write-Host $line}
    if($r.ExitCode-ne0){Fail($Purpose+' failed; exit='+$r.ExitCode+'; output='+$r.Text)}
    return $r
}
function Read-Registry([string]$ManagerRoot){return Get-Content -LiteralPath (Join-Path $ManagerRoot 'state\instances.json') -Raw -Encoding UTF8|ConvertFrom-Json}
function Assert-PowerShellParses([string]$Path,[string]$Purpose){
    $tokens=$null;$errors=$null
    [void][Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){Fail($Purpose+' parser failure: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
}
function Set-PreFixStageLossInstrumentation([string]$Runtime){
    $text=[IO.File]::ReadAllText($Runtime,[Text.Encoding]::UTF8)
    $anchor='                # Fresh per-entry commit-boundary revalidation protects later entries in the batch.'
    if([regex]::Matches($text,[regex]::Escape($anchor)).Count-ne1){Fail 'MGR-DEF-0034 RED instrumentation anchor count mismatch.'}
    $probe=@'
                if($env:KEELARYN_TRANSACTION_PROPERTY_FAULT -ceq 'drop-current-source-after-verified-stage' -and $published.Count -ge 1){
                    if([string]::IsNullOrWhiteSpace([string]$plan.Stage)){throw 'transaction-property fault expected an unpublished stage'}
                    $faultStage=Get-Item -LiteralPath ([string]$plan.Stage) -Force -ErrorAction Stop
                    if($faultStage.PSIsContainer-or($faultStage.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw 'transaction-property fault stage is unsafe'}
                    $faultHash=(Get-FileHash -LiteralPath ([string]$plan.Stage) -Algorithm SHA256).Hash.ToLowerInvariant()
                    if($faultHash-ne[string]$plan.Sha256){throw 'transaction-property fault stage hash mismatch'}
                    [IO.File]::WriteAllText([string]$env:KEELARYN_TRANSACTION_PROPERTY_SENTINEL,(([string]$plan.Stage)+"`n"+([string]$plan.Sha256)+"`n"+([string]$plan.Source)),[Text.Encoding]::UTF8)
                    Remove-Item -LiteralPath ([string]$plan.Source) -Force -ErrorAction Stop
                }
'@
    Write-Utf8 $Runtime ($text.Replace($anchor,$probe+$anchor))
    Assert-PowerShellParses $Runtime 'MGR-DEF-0034 RED-instrumented runtime'
}

$propertyModelPath=Join-Path $RepositoryRoot 'tests\knowledge\stranded-input-transaction-properties.json'
if(-not(Test-Path -LiteralPath $propertyModelPath -PathType Leaf)){Fail 'Stranded-input transaction-property model is missing.'}
$model=Get-Content -LiteralPath $propertyModelPath -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$model.schema-cne'keelaryn.manager-stranded-input-transaction-properties.v1'){Fail 'Unexpected transaction-property model schema.'}
if(@($model.properties|Where-Object{[string]$_.id-ceq'SITP-001'}).Count-ne1){Fail 'SITP-001 is missing or duplicated.'}
if($ExpectedState-cne'Broken'){Fail 'Fixed-state transaction-property execution is intentionally unavailable until the claim-first product implementation lands.'}

$sourceManager=Join-Path $RepositoryRoot 'manager'
$tempRoot=Join-Path ([IO.Path]::GetTempPath()) ('keelaryn-stranded-input-red-'+[guid]::NewGuid().ToString('N'))
$keelarynRoot=Join-Path $tempRoot 'keelaryn';$managerRoot=Join-Path $keelarynRoot 'manager';$configA=Join-Path $tempRoot 'alpha.json';$configB=Join-Path $tempRoot 'beta.json'
if([string]::IsNullOrWhiteSpace($OutputPath)){$OutputPath=Join-Path ([IO.Path]::GetTempPath()) ('STRANDED_INPUT_TRANSACTION_RED_'+[guid]::NewGuid().ToString('N')+'.json')}
$version='unknown';$result=$null;$harnessError=$null;$oldFault=$env:KEELARYN_TRANSACTION_PROPERTY_FAULT;$oldSentinel=$env:KEELARYN_TRANSACTION_PROPERTY_SENTINEL

try{
    New-Item -ItemType Directory -Force -Path $keelarynRoot|Out-Null
    $version=Copy-ManagedManager $sourceManager $managerRoot
    $runtime=Join-Path $managerRoot 'product\runtime\Keelaryn__Manager.ps1'
    foreach($pair in @(@($configA,'Alpha'),@($configB,'Beta'))){
        $cfg=[ordered]@{schema='keelaryn.genesis-input.v1';language='en';purpose='mixed';timezone='UTC';areas=@('Qualification');projects=@('Stranded input transaction '+[string]$pair[1])}
        Write-Json ([string]$pair[0]) $cfg
    }
    Write-Host ('=== MANAGER STRANDED INPUT TRANSACTION / PREFIX RED / '+$version+' ===')
    $null=Invoke-Required $runtime @('-Genesis','-GenesisConfigPath',$configA,'-GenesisConfirmed') 'Alpha Genesis'
    $null=Invoke-Required $runtime @('-InitializeInstanceRegistry','-RegisterInstanceName','Alpha') 'Registry activation'
    $betaPath=Join-Path $keelarynRoot 'hubs\beta'
    $null=Invoke-Required $runtime @('-GenesisInstancePath',$betaPath,'-GenesisInstanceName','Beta','-GenesisConfigPath',$configB,'-GenesisConfirmed') 'Beta registered Genesis'

    $registry=Read-Registry $managerRoot
    $alpha=@($registry.instances|Where-Object{[string]$_.name-ceq'Alpha'});$beta=@($registry.instances|Where-Object{[string]$_.name-ceq'Beta'})
    if($alpha.Count-ne1-or$beta.Count-ne1){Fail 'Could not resolve Alpha/Beta registry rows for transaction RED proof.'}
    $alphaId=[string]$alpha[0].instance_id;$betaId=[string]$beta[0].instance_id
    $stateRoot=Join-Path $managerRoot 'state';$globalInbox=Join-Path $stateRoot 'inbox'
    $alphaCurrent=Join-Path $stateRoot ('instances\'+$alphaId+'\baseline\Keelaryn__Hub_CURRENT.zip')
    $betaCurrent=Join-Path $stateRoot ('instances\'+$betaId+'\baseline\Keelaryn__Hub_CURRENT.zip')
    $alphaInbox=Join-Path $stateRoot ('instances\'+$alphaId+'\inbox');$betaInbox=Join-Path $stateRoot ('instances\'+$betaId+'\inbox')
    foreach($p in @($alphaCurrent,$betaCurrent,$globalInbox,$alphaInbox,$betaInbox)){if(-not(Test-Path -LiteralPath $p)){Fail('Required transaction fixture path missing: '+$p)}}

    $nameA='Keelaryn__Hub_APPROVED_A_transaction-red.zip';$nameB='Keelaryn__Hub_APPROVED_B_transaction-red.zip'
    $sourceA=Join-Path $globalInbox $nameA;$sourceB=Join-Path $globalInbox $nameB
    $targetA=Join-Path $alphaInbox $nameA;$targetB=Join-Path $betaInbox $nameB
    Copy-Item -LiteralPath $alphaCurrent -Destination $sourceA -Force;Copy-Item -LiteralPath $betaCurrent -Destination $sourceB -Force
    $shaA=(Get-FileHash -LiteralPath $sourceA -Algorithm SHA256).Hash.ToLowerInvariant();$shaB=(Get-FileHash -LiteralPath $sourceB -Algorithm SHA256).Hash.ToLowerInvariant()

    Set-PreFixStageLossInstrumentation $runtime
    $sentinel=Join-Path $tempRoot 'stage-loss-sentinel.txt'
    $env:KEELARYN_TRANSACTION_PROPERTY_FAULT='drop-current-source-after-verified-stage';$env:KEELARYN_TRANSACTION_PROPERTY_SENTINEL=$sentinel
    $run=Invoke-Runtime $runtime @('-InitializeInstanceRegistry')
    foreach($line in @($run.Output)){Write-Host $line}
    if(-not(Test-Path -LiteralPath $sentinel -PathType Leaf)){Fail('Expected RED fault sentinel was not produced. output='+$run.Text)}
    $sentinelRows=@([IO.File]::ReadAllLines($sentinel,[Text.Encoding]::UTF8))
    if($sentinelRows.Count-ne3){Fail('Unexpected RED fault sentinel shape: '+$sentinelRows.Count)}
    $stagedPath=[string]$sentinelRows[0];$stagedSha=[string]$sentinelRows[1];$faultSource=[string]$sentinelRows[2]
    if($stagedSha-cne$shaB){Fail('RED fault did not target Beta artifact. expected='+$shaB+' actual='+$stagedSha)}
    if([IO.Path]::GetFullPath($faultSource)-cne[IO.Path]::GetFullPath($sourceB)){Fail('RED fault source mismatch: '+$faultSource)}
    if(-not([IO.Path]::GetFullPath($stagedPath).StartsWith([IO.Path]::GetFullPath($targetB)+'.stage.',[StringComparison]::OrdinalIgnoreCase))){Fail('RED fault stage was not the Beta destination-local verified stage: '+$stagedPath)}

    $sourceAExists=Test-Path -LiteralPath $sourceA -PathType Leaf;$sourceBExists=Test-Path -LiteralPath $sourceB -PathType Leaf
    $targetAExists=Test-Path -LiteralPath $targetA -PathType Leaf;$targetBExists=Test-Path -LiteralPath $targetB -PathType Leaf;$stageSurvives=Test-Path -LiteralPath $stagedPath -PathType Leaf
    $sourceAExact=$sourceAExists-and((Get-FileHash -LiteralPath $sourceA -Algorithm SHA256).Hash.ToLowerInvariant()-ceq$shaA)
    $forbiddenLoss=($run.ExitCode-ne0-and$sourceAExact-and-not$sourceBExists-and-not$targetAExists-and-not$targetBExists-and-not$stageSurvives)
    $result=[ordered]@{
        id='SITP-001';name='claim_survives_source_loss_before_publication';expected_state='Broken';observed='red_reproduced';pass=$forbiddenLoss;exit_code=$run.ExitCode
        verified_unpublished_stage_existed_before_fault=$true;verified_stage_sha256=$stagedSha;source_removed_by_fault=(-not$sourceBExists);destination_absent=(-not$targetBExists);verified_stage_removed_by_finally=(-not$stageSurvives)
        earlier_source_preserved_exact=$sourceAExact;earlier_destination_rolled_back=(-not$targetAExists);detail=if($forbiddenLoss){'MGR-DEF-0034 reproduced: after a later verified unpublished stage lost its source, current whole-batch cleanup removed that stage and left no transaction-owned durable copy.'}else{'Expected forbidden stage-loss trajectory was not fully observed.'}
    }
}catch{$harnessError=$_.Exception.Message}
finally{$env:KEELARYN_TRANSACTION_PROPERTY_FAULT=$oldFault;$env:KEELARYN_TRANSACTION_PROPERTY_SENTINEL=$oldSentinel}

$report=[ordered]@{
    schema='keelaryn.manager-stranded-input-transaction-result.v1';manager_version=$version;expected_state=$ExpectedState;defect='MGR-DEF-0034';semantic_owner=[string]$model.semantic_owner;primary_invariant=[string]$model.primary_invariant
    properties_executed=@($(if($null-ne$result){$result}else{@()}));pass=($null-eq$harnessError-and$null-ne$result-and[bool]$result.pass);harness_error=$harnessError;production_hub_used=$false;disposable_manager_used=$true;completed_utc=[DateTime]::UtcNow.ToString('o')
}
try{Write-Json $OutputPath $report;Write-Host ('Evidence: '+$OutputPath)}catch{if(-not$harnessError){$harnessError=$_.Exception.Message};Write-Host ('Could not write transaction RED evidence: '+$_.Exception.Message) -ForegroundColor Red}
try{if(Test-Path -LiteralPath $tempRoot){Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction Stop}}catch{Write-Warning('Disposable cleanup failed: '+$_.Exception.Message)}
if($harnessError-or$null-eq$result-or-not[bool]$result.pass){Write-Host ('MANAGER STRANDED INPUT TRANSACTION PREFIX RED: FAIL; harness_error='+[bool]$harnessError) -ForegroundColor Red;if($harnessError){Write-Host $harnessError -ForegroundColor Red};exit 1}
Write-Host 'MANAGER STRANDED INPUT TRANSACTION PREFIX RED: PASS (defect reproduced as expected)' -ForegroundColor Yellow
exit 0
