[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$CandidateManagerRoot,
    [Parameter(Mandatory=$true)][string]$BaselineManagerRoot,
    [Parameter(Mandatory=$true)][string]$FrameworkRoot,
    [Parameter(Mandatory=$true)][string]$WorkspaceRoot,
    [string]$CandidateRef='',
    [string]$BaselineRef='',
    [int]$GateRevision=9002
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if($PSVersionTable.PSVersion.Major-ne5-or[string]$PSVersionTable.PSEdition-ne'Desktop'){
    throw 'Disposable Manager Full Gate requires Windows PowerShell 5.1 Desktop.'
}
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
$Started=(Get-Date).ToUniversalTime().ToString('o')
$CandidateVersion=''
$BaselineVersion=''
$FrameworkRevision=0
$GateZip=''
$GateSummary=''
$EvidenceRoot=''
$Failure=$null
$Succeeded=$false

function Fail([string]$Message){throw $Message}
function Sha([string]$Path){return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}
function Write-Utf8NoBom([string]$Path,[string]$Text){
    $parent=Split-Path -Parent $Path
    if($parent-and-not(Test-Path -LiteralPath $parent)){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
    [System.IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)
}
function Assert-Version([string]$Value,[string]$Name){
    if($Value-notmatch'^\d+\.\d+\.\d+$'){Fail($Name+' must be x.y.z: '+$Value)}
}
function Assert-SafeTree([string]$Root,[string]$Purpose){
    if(-not(Test-Path -LiteralPath $Root -PathType Container)){Fail($Purpose+' directory is missing: '+$Root)}
    $rootItem=Get-Item -LiteralPath $Root -Force -ErrorAction Stop
    if(-not$rootItem.PSIsContainer-or($rootItem.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail($Purpose+' root must be a real directory: '+$Root)}
    foreach($item in @(Get-ChildItem -LiteralPath $Root -Force -Recurse -ErrorAction Stop)){
        if(($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail($Purpose+' contains a reparse point: '+$item.FullName)}
    }
}
function Get-TreeDigest([string]$Root){
    $rootFull=[System.IO.Path]::GetFullPath($Root).TrimEnd('\')
    $rows=New-Object 'System.Collections.Generic.List[string]'
    foreach($file in @(Get-ChildItem -LiteralPath $rootFull -File -Force -Recurse|Sort-Object FullName)){
        $rel=$file.FullName.Substring($rootFull.Length).TrimStart('\').Replace('\','/')
        [void]$rows.Add($rel+"`0"+(Sha $file.FullName))
    }
    $sha=[System.Security.Cryptography.SHA256]::Create()
    try{
        $bytes=[System.Text.Encoding]::UTF8.GetBytes([string]::Join("`n",@($rows)))
        return [BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-','').ToLowerInvariant()
    }finally{$sha.Dispose()}
}
function Invoke-WindowsPowerShell([string]$ScriptPath,[string[]]$Arguments,[string]$LogPath,[string]$Purpose){
    if(-not(Test-Path -LiteralPath $ScriptPath -PathType Leaf)){Fail($Purpose+' script is missing: '+$ScriptPath)}
    $exe=Join-Path $PSHOME 'powershell.exe'
    $all=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$ScriptPath)+@($Arguments)
    $lines=@(& $exe @all 2>&1|ForEach-Object{[string]$_})
    $exitCode=$LASTEXITCODE
    Write-Utf8NoBom $LogPath (([string]::Join("`n",$lines))+"`n")
    foreach($line in $lines){Write-Host $line}
    if($exitCode-ne0){Fail($Purpose+' failed with exit code '+$exitCode+'. See '+$LogPath)}
}
function Assert-GateZip([string]$Path,[string]$Version){
    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){Fail('Manager gate ZIP is missing: '+$Path)}
    $expectedRoot='manager-'+$Version+'/'
    $archive=[System.IO.Compression.ZipFile]::OpenRead($Path)
    try{
        if($archive.Entries.Count-lt1){Fail('Manager gate ZIP is empty.')}
        foreach($entry in $archive.Entries){
            $name=$entry.FullName.Replace('\','/')
            if([string]::IsNullOrWhiteSpace($name)-or$name.StartsWith('/')-or$name-match'^[A-Za-z]:' ){Fail('Unsafe absolute gate ZIP entry: '+$name)}
            $segments=@($name.Split('/')|Where-Object{$_-ne''})
            if($segments-contains'..'){Fail('Unsafe traversal gate ZIP entry: '+$name)}
            if(-not$name.StartsWith($expectedRoot,[System.StringComparison]::Ordinal)){Fail('Gate ZIP root mismatch: '+$name+' expected '+$expectedRoot)}
        }
    }finally{$archive.Dispose()}
}
function Copy-Tree([string]$Source,[string]$Destination){
    New-Item -ItemType Directory -Force -Path $Destination|Out-Null
    foreach($item in @(Get-ChildItem -LiteralPath $Source -Force -ErrorAction Stop)){
        Copy-Item -LiteralPath $item.FullName -Destination $Destination -Recurse -Force -ErrorAction Stop
    }
}
function Copy-EvidenceResults([string]$ResultsRoot,[string]$Destination){
    if(-not(Test-Path -LiteralPath $ResultsRoot -PathType Container)){return}
    if(Test-Path -LiteralPath $Destination){Fail('Evidence results destination unexpectedly already exists: '+$Destination)}
    Copy-Item -LiteralPath $ResultsRoot -Destination $Destination -Recurse -Force -ErrorAction Stop
}

try{
    if($GateRevision-lt9000){Fail 'Disposable/remote qualification gate revisions must be >= 9000 and can never represent production qualification.'}
    $CandidateManagerRoot=[System.IO.Path]::GetFullPath($CandidateManagerRoot).TrimEnd('\')
    $BaselineManagerRoot=[System.IO.Path]::GetFullPath($BaselineManagerRoot).TrimEnd('\')
    $FrameworkRoot=[System.IO.Path]::GetFullPath($FrameworkRoot).TrimEnd('\')
    $WorkspaceRoot=[System.IO.Path]::GetFullPath($WorkspaceRoot).TrimEnd('\')

    Assert-SafeTree $CandidateManagerRoot 'Candidate Manager'
    Assert-SafeTree $BaselineManagerRoot 'Baseline Manager'
    Assert-SafeTree $FrameworkRoot 'Gate Framework'

    if(Test-Path -LiteralPath $WorkspaceRoot){
        $workItem=Get-Item -LiteralPath $WorkspaceRoot -Force -ErrorAction Stop
        if(-not$workItem.PSIsContainer-or($workItem.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail('WorkspaceRoot must be a real directory: '+$WorkspaceRoot)}
        if(@(Get-ChildItem -LiteralPath $WorkspaceRoot -Force -ErrorAction Stop).Count-ne0){Fail('WorkspaceRoot must be new or empty: '+$WorkspaceRoot)}
    }else{New-Item -ItemType Directory -Force -Path $WorkspaceRoot|Out-Null}
    $EvidenceRoot=Join-Path $WorkspaceRoot 'evidence'
    New-Item -ItemType Directory -Force -Path $EvidenceRoot|Out-Null

    $candidateInstallPath=Join-Path $CandidateManagerRoot 'product\install\INSTALLATION.json'
    $baselineInstallPath=Join-Path $BaselineManagerRoot 'product\install\INSTALLATION.json'
    foreach($p in @($candidateInstallPath,$baselineInstallPath)){if(-not(Test-Path -LiteralPath $p -PathType Leaf)){Fail('INSTALLATION.json missing: '+$p)}}
    $candidateInstall=(Get-Content -LiteralPath $candidateInstallPath -Raw -Encoding UTF8)|ConvertFrom-Json
    $baselineInstall=(Get-Content -LiteralPath $baselineInstallPath -Raw -Encoding UTF8)|ConvertFrom-Json
    if([string]$candidateInstall.schema-ne'keelaryn.manager.installation.v2'-or[string]$baselineInstall.schema-ne'keelaryn.manager.installation.v2'){Fail 'Candidate and baseline must use keelaryn.manager.installation.v2.'}
    $CandidateVersion=([string]$candidateInstall.manager_version).Trim()
    $BaselineVersion=([string]$baselineInstall.manager_version).Trim()
    Assert-Version $CandidateVersion 'Candidate version'
    Assert-Version $BaselineVersion 'Baseline version'
    if([version]$CandidateVersion-le[version]$BaselineVersion){Fail('Candidate version must be newer than disposable baseline: '+$BaselineVersion+' -> '+$CandidateVersion)}

    $frameworkRevisionPath=Join-Path $FrameworkRoot 'FRAMEWORK_REVISION.txt'
    if(-not(Test-Path -LiteralPath $frameworkRevisionPath -PathType Leaf)){Fail('Gate Framework revision marker missing: '+$frameworkRevisionPath)}
    if(-not[int]::TryParse((Get-Content -LiteralPath $frameworkRevisionPath -Raw -Encoding UTF8).Trim(),[ref]$FrameworkRevision)-or$FrameworkRevision-lt1){Fail 'Invalid Gate Framework revision marker.'}
    $builder=Join-Path $FrameworkRoot 'Build-ManagerGate.ps1'
    if(-not(Test-Path -LiteralPath $builder -PathType Leaf)){Fail('Gate builder missing: '+$builder)}

    $syntheticRoot=Join-Path $WorkspaceRoot 'synthetic-production'
    $syntheticManager=Join-Path $syntheticRoot 'manager'
    $testsRoot=Join-Path $syntheticRoot 'tests'
    $workRoot=Join-Path $testsRoot 'work'
    $packageRoot=Join-Path $WorkspaceRoot 'gate-package'
    New-Item -ItemType Directory -Force -Path $syntheticRoot,$testsRoot,$workRoot,$packageRoot|Out-Null
    Copy-Tree $BaselineManagerRoot $syntheticManager

    $genesisConfig=Join-Path $WorkspaceRoot 'synthetic-genesis.json'
    $genesis=[ordered]@{
        schema='keelaryn.genesis-input.v1'
        language='en'
        purpose='mixed'
        timezone='UTC'
        areas=@('Qualification')
        projects=@('Disposable Full Gate')
    }
    Write-Utf8NoBom $genesisConfig ((($genesis|ConvertTo-Json -Depth 6).Replace("`r`n","`n"))+"`n")
    $baselineRuntime=Join-Path $syntheticManager 'product\runtime\Keelaryn__Manager.ps1'
    Invoke-WindowsPowerShell $baselineRuntime @('-Genesis','-GenesisConfigPath',$genesisConfig,'-GenesisConfirmed') (Join-Path $EvidenceRoot 'BASELINE_GENESIS.log') 'Synthetic baseline Genesis'
    Invoke-WindowsPowerShell $baselineRuntime @('-Doctor') (Join-Path $EvidenceRoot 'BASELINE_DOCTOR.log') 'Synthetic baseline Doctor'

    $syntheticHub=Join-Path $syntheticRoot 'hub'
    $syntheticCurrent=Join-Path $syntheticManager 'state\baseline\Keelaryn__Hub_CURRENT.zip'
    foreach($p in @($syntheticHub,$syntheticCurrent)){if(-not(Test-Path -LiteralPath $p)){Fail('Synthetic baseline did not materialize required path: '+$p)}}
    Assert-SafeTree $syntheticHub 'Synthetic Hub'
    $managerBefore=Get-TreeDigest $syntheticManager
    $hubBefore=Get-TreeDigest $syntheticHub
    $currentBefore=Sha $syntheticCurrent

    $GateZip=Join-Path $packageRoot ('manager-'+$CandidateVersion+'.zip')
    Invoke-WindowsPowerShell $builder @('-SourceRoot',$CandidateManagerRoot,'-BaselineVersion',$BaselineVersion,'-GateRevision',[string]$GateRevision,'-OutputPath',$GateZip,'-Force') (Join-Path $EvidenceRoot 'GATE_BUILD.log') 'Manager gate build'
    Assert-GateZip $GateZip $CandidateVersion
    Expand-Archive -LiteralPath $GateZip -DestinationPath $workRoot -Force
    $candidateRoot=Join-Path $workRoot ('manager-'+$CandidateVersion)
    $fullGate=Join-Path $candidateRoot 'gate\Run-KeelarynManagerFullGate.ps1'
    Invoke-WindowsPowerShell $fullGate @('-CandidateRoot',$candidateRoot,'-ProductionRoot',$syntheticRoot) (Join-Path $EvidenceRoot 'DISPOSABLE_FULL_GATE.console.log') 'Disposable Full Gate'

    $GateSummary=Join-Path $testsRoot ('results\manager-'+$CandidateVersion+'\GATE_SUMMARY.json')
    if(-not(Test-Path -LiteralPath $GateSummary -PathType Leaf)){Fail('Full Gate summary missing: '+$GateSummary)}
    $summary=(Get-Content -LiteralPath $GateSummary -Raw -Encoding UTF8)|ConvertFrom-Json
    if([string]$summary.status-ne'passed'){Fail('Full Gate summary status is not passed: '+[string]$summary.status)}
    if([string]$summary.manager_version-ne$CandidateVersion-or[string]$summary.baseline_version-ne$BaselineVersion){Fail 'Full Gate summary candidate/baseline identity mismatch.'}
    if([int]$summary.gate_revision-ne$GateRevision-or[int]$summary.framework_revision-ne$FrameworkRevision){Fail 'Full Gate summary gate/framework revision mismatch.'}
    if(-not[bool]$summary.production_execution_isolated-or-not[bool]$summary.production_unchanged){Fail 'Full Gate did not prove production-path execution isolation/immutability.'}
    if($null-eq$summary.production_hub_observed_change-or[int]$summary.production_hub_observed_change.changed_count-ne0){Fail 'Synthetic production Hub changed during Full Gate.'}

    if((Get-TreeDigest $syntheticManager)-cne$managerBefore){Fail 'Synthetic production Manager tree changed during Full Gate.'}
    if((Get-TreeDigest $syntheticHub)-cne$hubBefore){Fail 'Synthetic production Hub tree changed during Full Gate.'}
    if((Sha $syntheticCurrent)-cne$currentBefore){Fail 'Synthetic production CURRENT changed during Full Gate.'}
    $Succeeded=$true
}
catch{
    $Failure=$_.Exception.GetType().FullName+': '+$_.Exception.Message
    Write-Host ('DISPOSABLE FULL GATE: FAIL - '+$Failure) -ForegroundColor Red
}
finally{
    if($EvidenceRoot){
        try{
            $resultsRoot=''
            if($CandidateVersion){$resultsRoot=Join-Path $WorkspaceRoot ('synthetic-production\tests\results\manager-'+$CandidateVersion)}
            if($resultsRoot-and(Test-Path -LiteralPath $resultsRoot -PathType Container)){Copy-EvidenceResults $resultsRoot (Join-Path $EvidenceRoot 'results')}
            if($GateZip-and(Test-Path -LiteralPath $GateZip -PathType Leaf)){Copy-Item -LiteralPath $GateZip -Destination (Join-Path $EvidenceRoot ([System.IO.Path]::GetFileName($GateZip))) -Force}
            $summarySha=$null
            if($GateSummary-and(Test-Path -LiteralPath $GateSummary -PathType Leaf)){$summarySha=Sha $GateSummary}
            $gateSha=$null
            if($GateZip-and(Test-Path -LiteralPath $GateZip -PathType Leaf)){$gateSha=Sha $GateZip}
            $doc=[ordered]@{
                schema='keelaryn.manager.disposable-prequalification.v1'
                classification='synthetic_disposable_only'
                candidate_version=$CandidateVersion
                baseline_version=$BaselineVersion
                candidate_ref=$CandidateRef
                baseline_ref=$BaselineRef
                gate_revision=$GateRevision
                framework_revision=$FrameworkRevision
                gate_zip_sha256=$gateSha
                gate_summary_sha256=$summarySha
                started_utc=$Started
                completed_utc=(Get-Date).ToUniversalTime().ToString('o')
                full_gate_pass=[bool]$Succeeded
                synthetic_baseline=$true
                personal_hub_used=$false
                production_qualified=$false
                requires_real_production_validation=$true
                failure=$Failure
            }
            Write-Utf8NoBom (Join-Path $EvidenceRoot 'PREQUALIFICATION.json') ((($doc|ConvertTo-Json -Depth 8).Replace("`r`n","`n"))+"`n")
        }catch{Write-Warning ('Could not finalize disposable evidence: '+$_.Exception.Message)}
    }
}

if(-not$Succeeded){exit 1}
Write-Host ('DISPOSABLE FULL GATE: PASS. Manager '+$CandidateVersion+' over synthetic '+$BaselineVersion+'; framework=r'+$FrameworkRevision+'; gate=g'+$GateRevision) -ForegroundColor Green
Write-Host 'Classification: disposable prequalification only; real production validation is still required.' -ForegroundColor Yellow
exit 0
